from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import (
    ForbiddenError,
    PreconditionRequiredError,
    UnauthorizedError,
    UnprocessableError,
)
from app.core.permissions import (
    ALL_PERMISSIONS,
    BOOKING_STATUS_DEFAULT_PERMISSION,
    BOOKING_STATUS_PERMISSION,
    EVENT_STATUS_PERMISSION,
    AuthUser,
)
from app.repositories.booking_repository import BookingRepository
from app.repositories.denylist_repository import DenylistRepository
from app.repositories.event_repository import EventRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.booking import BookingUpdate
from app.schemas.event import EventUpdate
from app.services.auth_service import AuthService
from app.services.booking_service import BookingService
from app.services.event_service import EventService
from app.services.user_service import UserService

bearer_scheme = HTTPBearer(auto_error=False, description="Access token from /auth/login")


# ---------------------------------------------------------------- wiring
def get_db(request: Request) -> AsyncDatabase:
    return request.app.state.db


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def _repos(db: AsyncDatabase):
    return UserRepository(db.users), EventRepository(db.events), BookingRepository(db.bookings)


def get_user_service(db: AsyncDatabase = Depends(get_db)) -> UserService:
    users, events, bookings = _repos(db)
    return UserService(users, events, bookings)


def get_event_service(db: AsyncDatabase = Depends(get_db)) -> EventService:
    users, events, bookings = _repos(db)
    return EventService(events, users, bookings)


def get_booking_service(
    db: AsyncDatabase = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> BookingService:
    users, events, bookings = _repos(db)
    return BookingService(bookings, events, users, settings.booking_hold_minutes)


def get_auth_service(
    db: AsyncDatabase = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> AuthService:
    return AuthService(
        UserRepository(db.users),
        RefreshTokenRepository(db.refresh_tokens),
        DenylistRepository(db.token_denylist),
        settings,
    )


# ---------------------------------------------------------------- authentication / RBAC
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth: AuthService = Depends(get_auth_service),
) -> AuthUser:
    if credentials is None:
        raise UnauthorizedError("Authentication required")
    return await auth.authenticate(credentials.credentials)


def require(permission: str):
    """R2.5: `Depends(require("event:publish"))`. Routes never inspect roles."""
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")

    async def checker(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not user.can(permission):
            raise ForbiddenError(f"Missing permission: {permission}")
        return user

    return checker


@dataclass(frozen=True)
class Authorized:
    user: AuthUser
    payload: Any


async def authorize_event_update(
    payload: EventUpdate, user: AuthUser = Depends(require("event:update"))
) -> Authorized:
    """PATCH /events/{id}: publishing needs the extra `event:publish` permission."""
    needed = EVENT_STATUS_PERMISSION.get(payload.status) if payload.status else None
    if needed and not user.can(needed):
        raise ForbiddenError(f"Missing permission: {needed}")
    return Authorized(user, payload)


async def authorize_booking_update(
    payload: BookingUpdate, user: AuthUser = Depends(require("booking:update"))
) -> Authorized:
    """PATCH /bookings/{id}: each target status maps to its own permission."""
    needed = BOOKING_STATUS_PERMISSION.get(payload.status, BOOKING_STATUS_DEFAULT_PERMISSION)
    if not user.can(needed):
        raise ForbiddenError(f"Missing permission: {needed}")
    return Authorized(user, payload)


# ---------------------------------------------------------------- R1.5
async def require_if_match(if_match: str | None = Header(default=None, alias="If-Match")) -> int:
    """Missing -> 428, malformed -> 422. Accepts 3, "3" and W/"3"."""
    if if_match is None or not if_match.strip():
        raise PreconditionRequiredError("If-Match header with the event version is required")
    value = if_match.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    if not (value.isascii() and value.isdigit()):
        raise UnprocessableError("If-Match must be an integer version", code="INVALID_IF_MATCH")
    return int(value)
