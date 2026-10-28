from bson import ObjectId

from app.common.pagination import decode_id_cursor, slice_page
from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password
from app.repositories.booking_repository import BookingRepository
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.schemas.base import Page
from app.schemas.user import UserCreate, UserRead, UserUpdate


def _not_found() -> NotFoundError:
    return NotFoundError("User not found", code="USER_NOT_FOUND")


class UserService:
    def __init__(
        self, users: UserRepository, events: EventRepository, bookings: BookingRepository
    ) -> None:
        self._users = users
        self._events = events
        self._bookings = bookings

    async def create(self, payload: UserCreate) -> UserRead:
        data = payload.model_dump(exclude={"password"})
        data["password_hash"] = await hash_password(payload.password)
        doc = await self._users.insert(data)
        return UserRead.from_doc(doc)

    async def get(self, user_id: str) -> UserRead:
        doc = await self._users.get(ObjectId(user_id))
        if doc is None:
            raise _not_found()
        return UserRead.from_doc(doc)

    async def list(self, limit: int, cursor: str | None) -> Page[UserRead]:
        after = decode_id_cursor(cursor) if cursor else None
        docs = await self._users.list_page(after, limit)
        docs, next_cursor = slice_page(docs, limit, lambda d: {"id": str(d["_id"])})
        return Page[UserRead](items=[UserRead.from_doc(d) for d in docs], next_cursor=next_cursor)

    async def update(self, user_id: str, payload: UserUpdate) -> UserRead:
        doc = await self._users.update(ObjectId(user_id), payload.model_dump(exclude_unset=True))
        if doc is None:
            raise _not_found()
        return UserRead.from_doc(doc)

    async def delete(self, user_id: str) -> None:
        oid = ObjectId(user_id)
        if await self._users.get(oid) is None:
            raise _not_found()
        if await self._bookings.exists_for_user(oid):
            raise ConflictError("User has bookings and cannot be deleted", code="USER_HAS_BOOKINGS")
        if await self._events.exists_for_organizer(oid):
            raise ConflictError("User organizes events and cannot be deleted", code="USER_HAS_EVENTS")
        if not await self._users.delete(oid):
            raise _not_found()
