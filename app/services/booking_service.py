import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.common.pagination import decode_id_cursor, slice_page
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.permissions import AuthUser
from app.repositories.booking_repository import BookingRepository
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.schemas.base import Page
from app.schemas.booking import BookingCreate, BookingRead, BookingStatus, BookingUpdate
from app.services.access import booking_read_scope, booking_write_scope

logger = logging.getLogger("tickethub")

S = BookingStatus
# R1.6 booking lifecycle (6 states). Edit here if your diagram differs.
_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    S.pending_payment: {S.confirmed, S.cancelled, S.expired},
    S.confirmed: {S.checked_in, S.cancelled},
    S.checked_in: set(),
    S.cancelled: {S.refunded},
    S.expired: set(),
    S.refunded: set(),
}
_HOLDS_SEATS = {S.pending_payment, S.confirmed, S.checked_in}
_RELEASES_SEATS_ON = {S.cancelled, S.expired}


def _not_found() -> NotFoundError:
    return NotFoundError("Booking not found", code="BOOKING_NOT_FOUND")


class BookingService:
    def __init__(
        self,
        bookings: BookingRepository,
        events: EventRepository,
        users: UserRepository,
        hold_minutes: int,
    ) -> None:
        self._bookings = bookings
        self._events = events
        self._users = users
        self._hold = timedelta(minutes=hold_minutes)

    async def create(self, payload: BookingCreate, actor: AuthUser) -> BookingRead:
        # Attendees can only book for themselves; admins book on someone's behalf.
        if actor.can("booking:manage_any"):
            if payload.user_id is None:
                raise UnprocessableError("user_id is required", code="USER_ID_REQUIRED")
            user_id = payload.user_id
        else:
            if payload.user_id not in (None, actor.id):
                raise ForbiddenError("You can only create bookings for yourself")
            user_id = actor.id

        event_oid, user_oid = ObjectId(payload.event_id), ObjectId(user_id)

        user = await self._users.get(user_oid)
        if user is None:
            raise NotFoundError("User not found", code="USER_NOT_FOUND")
        if not user["is_active"]:
            raise ConflictError("User account is inactive", code="USER_INACTIVE")

        # R1.2: one atomic guarded $inc - no read-then-write race.
        event = await self._events.reserve_seats(event_oid, payload.tier, payload.quantity)
        if event is None:
            await self._raise_reservation_failure(event_oid, payload.tier, actor)

        tier = next(t for t in event["ticket_tiers"] if t["name"] == payload.tier)
        doc = {
            "event_id": event_oid,
            "organizer_id": event["organizer_id"],  # denormalised: lets organizers list their bookings
            "user_id": user_oid,
            "tier": payload.tier,
            "quantity": payload.quantity,
            "amount_inr": tier["price_inr"] * payload.quantity,  # always server-computed
            "status": S.pending_payment.value,
            "hold_expires_at": datetime.now(timezone.utc) + self._hold,
        }
        try:
            doc = await self._bookings.insert(doc)
        except BaseException:
            # Seats were taken but the booking was not stored: give them back.
            await self._safe_release(event_oid, payload.tier, payload.quantity)
            raise
        return BookingRead.from_doc(doc)

    async def get(self, booking_id: str, actor: AuthUser) -> BookingRead:
        doc = await self._bookings.get(ObjectId(booking_id), booking_read_scope(actor))
        if doc is None:
            raise _not_found()  # R2.6: someone else's booking looks non-existent
        return BookingRead.from_doc(doc)

    async def list(self, limit: int, cursor: str | None, actor: AuthUser) -> Page[BookingRead]:
        after = decode_id_cursor(cursor) if cursor else None
        docs = await self._bookings.list_page(after, limit, booking_read_scope(actor))
        docs, next_cursor = slice_page(docs, limit, lambda d: {"id": str(d["_id"])})
        return Page[BookingRead](items=[BookingRead.from_doc(d) for d in docs], next_cursor=next_cursor)

    async def update(self, booking_id: str, payload: BookingUpdate, actor: AuthUser) -> BookingRead:
        current = await self._bookings.get(ObjectId(booking_id), booking_write_scope(actor))
        if current is None:
            raise _not_found()
        return await self._apply_transition(current, S(payload.status))

    async def check_in(self, booking_id: str) -> BookingRead:
        # Door staff are not tied to one event, so there is no ownership scope here;
        # the route's permission is the gate.
        current = await self._bookings.get(ObjectId(booking_id))
        if current is None:
            raise _not_found()
        return await self._apply_transition(current, S.checked_in)

    async def delete(self, booking_id: str) -> None:
        deleted = await self._bookings.delete(ObjectId(booking_id))
        if deleted is None:
            raise _not_found()
        if S(deleted["status"]) in _HOLDS_SEATS:  # don't leak seats
            await self._safe_release(deleted["event_id"], deleted["tier"], deleted["quantity"])

    # ------------------------------------------------------------------
    async def _apply_transition(self, current: dict, target: BookingStatus) -> BookingRead:
        source = S(current["status"])
        if target is S.confirmed:
            raise ConflictError(
                "A booking can only be confirmed by the payment webhook", code="ILLEGAL_TRANSITION"
            )
        if target not in _TRANSITIONS[source]:
            raise ConflictError(
                f"Cannot move booking from {source.value} to {target.value}",
                code="ILLEGAL_TRANSITION",
            )

        updated = await self._bookings.transition(current["_id"], source.value, target.value)
        if updated is None:  # lost a race with another transition/delete
            if await self._bookings.get(current["_id"]) is None:
                raise _not_found()
            raise ConflictError("Booking changed concurrently; retry", code="CONCURRENT_MODIFICATION")

        if target in _RELEASES_SEATS_ON and source in _HOLDS_SEATS:
            await self._safe_release(updated["event_id"], updated["tier"], updated["quantity"])
        return BookingRead.from_doc(updated)

    async def _raise_reservation_failure(
        self, event_oid: ObjectId, tier_name: str, actor: AuthUser
    ) -> None:
        event = await self._events.get(event_oid)
        if event is None:
            raise NotFoundError("Event not found", code="EVENT_NOT_FOUND")
        if event["status"] != "published":
            if not actor.can("event:read_all"):  # attendees must not learn about unpublished events
                raise NotFoundError("Event not found", code="EVENT_NOT_FOUND")
            raise ConflictError("Event is not open for booking", code="EVENT_NOT_BOOKABLE")
        if not any(t["name"] == tier_name for t in event["ticket_tiers"]):
            raise UnprocessableError(f"Unknown ticket tier '{tier_name}'", code="UNKNOWN_TIER")
        raise ConflictError("Not enough seats left in this tier", code="SOLD_OUT")

    async def _safe_release(self, event_oid: ObjectId, tier: str, quantity: int) -> None:
        try:
            await self._events.release_seats(event_oid, tier, quantity)
        except Exception:
            logger.exception("failed to release seats event=%s tier=%s qty=%s", event_oid, tier, quantity)
