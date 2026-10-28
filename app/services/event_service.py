from datetime import datetime, timezone

from bson import ObjectId

from app.common.pagination import decode_event_cursor, event_cursor_payload, slice_page
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.permissions import AuthUser
from app.repositories.booking_repository import BookingRepository
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.schemas.base import Page
from app.schemas.event import EventCreate, EventPublic, EventRead, EventStatus, EventUpdate
from app.services.access import event_read_scope, event_write_scope

# R1.6 - draft -> published -> completed, or cancelled (checked separately: only before start).
_TRANSITIONS: dict[str, set[str]] = {
    EventStatus.draft: {EventStatus.published, EventStatus.cancelled},
    EventStatus.published: {EventStatus.completed, EventStatus.cancelled},
    EventStatus.completed: set(),
    EventStatus.cancelled: set(),
}
_TERMINAL = {EventStatus.completed, EventStatus.cancelled}


def _not_found() -> NotFoundError:
    return NotFoundError("Event not found", code="EVENT_NOT_FOUND")


def _version_conflict() -> ConflictError:
    return ConflictError(
        "Event was modified by someone else; fetch the latest version and retry",
        code="VERSION_CONFLICT",
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class EventService:
    def __init__(
        self, events: EventRepository, users: UserRepository, bookings: BookingRepository
    ) -> None:
        self._events = events
        self._users = users
        self._bookings = bookings

    async def create(self, payload: EventCreate, user: AuthUser) -> EventRead:
        if user.can("event:manage_any"):
            if payload.organizer_id is None:
                raise UnprocessableError("organizer_id is required", code="ORGANIZER_REQUIRED")
            organizer_id = payload.organizer_id
        else:
            if payload.organizer_id not in (None, user.id):
                raise ForbiddenError("You can only create events for yourself")
            organizer_id = user.id

        organizer = await self._users.get(ObjectId(organizer_id))
        if organizer is None:
            raise NotFoundError("Organizer not found", code="ORGANIZER_NOT_FOUND")
        if not organizer["is_active"]:
            raise ConflictError("Organizer account is inactive", code="ORGANIZER_INACTIVE")
        if organizer["role"] not in ("organizer", "admin"):
            raise UnprocessableError(
                "organizer_id must reference an organizer or admin user", code="INVALID_ORGANIZER"
            )

        data = payload.model_dump(exclude={"organizer_id"})
        doc = {
            **data,
            "organizer_id": ObjectId(organizer_id),
            "ticket_tiers": [{**t, "remaining": t["quota"]} for t in data["ticket_tiers"]],
            "status": EventStatus.draft.value,
            "version": 1,
        }
        return EventRead.from_doc(await self._events.insert(doc))

    async def get(self, event_id: str, user: AuthUser) -> EventRead | EventPublic:
        doc = await self._events.get(ObjectId(event_id), event_read_scope(user))
        if doc is None:
            raise _not_found()  # also covers "exists but not yours / not public" (R2.6)
        return self._present(doc, user)

    async def list(
        self,
        *,
        city: str | None,
        status: EventStatus | None,
        date_from: datetime | None,
        date_to: datetime | None,
        q: str | None,
        limit: int,
        cursor: str | None,
        user: AuthUser,
    ) -> Page[EventRead] | Page[EventPublic]:
        date_from = _as_utc(date_from) if date_from else None
        date_to = _as_utc(date_to) if date_to else None
        if date_from and date_to and date_from > date_to:
            raise UnprocessableError("date_from must not be after date_to")
        after = decode_event_cursor(cursor) if cursor else None
        docs = await self._events.list_page(
            city=city.strip() if city and city.strip() else None,
            status=status.value if status else None,
            date_from=date_from,
            date_to=date_to,
            q=q.strip() if q and q.strip() else None,
            after=after,
            limit=limit,
            scope=event_read_scope(user),
        )
        docs, next_cursor = slice_page(docs, limit, event_cursor_payload)
        # R2.7: choose the model by permission - fields are never deleted from a fuller model.
        if user.can("event:read_detail"):
            return Page[EventRead](items=[EventRead.from_doc(d) for d in docs], next_cursor=next_cursor)
        return Page[EventPublic](items=[EventPublic.from_doc(d) for d in docs], next_cursor=next_cursor)

    async def update(
        self, event_id: str, expected_version: int, payload: EventUpdate, user: AuthUser
    ) -> EventRead:
        oid = ObjectId(event_id)
        current = await self._events.get(oid, event_write_scope(user))  # R2.6: not yours -> 404
        if current is None:
            raise _not_found()
        if current["version"] != expected_version:
            raise _version_conflict()

        changes = payload.model_dump(exclude_unset=True)
        current_status = EventStatus(current["status"])
        starts_at = changes.get("starts_at", current["starts_at"])
        ends_at = changes.get("ends_at", current["ends_at"])

        # Lifecycle (R1.6)
        new_status = changes.get("status")
        if new_status is not None:
            target = EventStatus(new_status)
            if target not in _TRANSITIONS[current_status]:
                raise ConflictError(
                    f"Cannot move event from {current_status.value} to {target.value}",
                    code="ILLEGAL_TRANSITION",
                )
            if target is EventStatus.cancelled and datetime.now(timezone.utc) >= starts_at:
                raise ConflictError(
                    "An event can only be cancelled before it starts", code="ILLEGAL_TRANSITION"
                )
        elif current_status in _TERMINAL:
            raise ConflictError(
                f"A {current_status.value} event can no longer be edited", code="EVENT_NOT_EDITABLE"
            )

        # Seat structure is frozen once the event leaves draft, so seat counts stay correct.
        if ("capacity" in changes or "ticket_tiers" in changes) and current_status != EventStatus.draft:
            raise ConflictError(
                "capacity and ticket_tiers can only be changed while the event is a draft",
                code="EVENT_NOT_EDITABLE",
            )

        # Validate the merged result (the schema could only see the payload).
        if ends_at <= starts_at:
            raise UnprocessableError("ends_at must be after starts_at")
        capacity = changes.get("capacity", current["capacity"])
        tiers = changes.get("ticket_tiers", current["ticket_tiers"])
        if sum(t["quota"] for t in tiers) > capacity:
            raise UnprocessableError(
                "sum of ticket tier quotas must not exceed capacity",
                code="QUOTA_EXCEEDS_CAPACITY",
            )
        if "ticket_tiers" in changes:
            changes["ticket_tiers"] = [{**t, "remaining": t["quota"]} for t in changes["ticket_tiers"]]

        updated = await self._events.update_versioned(oid, expected_version, changes)
        if updated is None:  # changed or deleted between our read and write
            if await self._events.get(oid) is None:
                raise _not_found()
            raise _version_conflict()
        return EventRead.from_doc(updated)

    async def delete(self, event_id: str) -> None:
        oid = ObjectId(event_id)
        current = await self._events.get(oid)
        if current is None:
            raise _not_found()
        if current["status"] == EventStatus.published.value:
            raise ConflictError(
                "A published event must be completed or cancelled before it can be deleted",
                code="EVENT_NOT_DELETABLE",
            )
        if await self._bookings.exists_for_event(oid):
            raise ConflictError("Event has bookings and cannot be deleted", code="EVENT_HAS_BOOKINGS")
        if not await self._events.delete_unless_published(oid):
            if await self._events.get(oid) is None:
                raise _not_found()
            raise ConflictError("Event changed concurrently; retry", code="EVENT_NOT_DELETABLE")

    @staticmethod
    def _present(doc: dict, user: AuthUser) -> EventRead | EventPublic:
        return EventRead.from_doc(doc) if user.can("event:read_detail") else EventPublic.from_doc(doc)
