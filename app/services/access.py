"""R2.6 - ownership / visibility rules, expressed as Mongo filters derived from permissions.

Rows outside the filter simply are not found, so callers get 404 (never 403) for other
people's resources and existence is not leaked.
"""
from typing import Any

from app.core.errors import ForbiddenError
from app.core.permissions import AuthUser


def event_read_scope(user: AuthUser) -> dict[str, Any]:
    if user.can("event:read_all"):
        return {}
    if user.can("event:read_own"):
        return {"organizer_id": user.oid}
    return {"status": "published"}  # safest default: only what is public


def event_write_scope(user: AuthUser) -> dict[str, Any]:
    return {} if user.can("event:manage_any") else {"organizer_id": user.oid}


def booking_read_scope(user: AuthUser) -> dict[str, Any]:
    if user.can("booking:read_all"):
        return {}
    if user.can("booking:read_own_events"):
        return {"organizer_id": user.oid}
    if user.can("booking:read_own"):
        return {"user_id": user.oid}
    raise ForbiddenError("You do not have permission to view bookings")


def booking_write_scope(user: AuthUser) -> dict[str, Any]:
    return {} if user.can("booking:manage_any") else {"user_id": user.oid}
