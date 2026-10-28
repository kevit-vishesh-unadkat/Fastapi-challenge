"""R2.5 - the ONE place that maps roles to permission strings.

Routes never look at roles; they declare `Depends(require("<permission>"))`.
Scope permissions (`*:read_all`, `*:read_own`, ...) decide *which rows* a role can see;
the services turn them into query filters (R2.6).
"""
from dataclasses import dataclass

from bson import ObjectId

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        # users
        "user:create", "user:read", "user:update", "user:delete",
        # events
        "event:create", "event:read", "event:update", "event:publish", "event:delete",
        "event:read_all",     # scope: every event, any status
        "event:read_own",     # scope: only events the user organizes
        "event:read_detail",  # may see the full EventRead (sales + organizer fields), not EventPublic
        "event:manage_any",   # may create/edit events on behalf of other organizers
        # bookings
        "booking:create", "booking:read", "booking:update", "booking:delete",
        "booking:cancel", "booking:check_in",
        "booking:pay",        # reserved: no route until payments arrive in a later level
        "booking:manage",     # set any status (confirm/expire/refund/...)
        "booking:read_all",   # scope: every booking
        "booking:read_own_events",  # scope: bookings for events the user organizes
        "booking:read_own",   # scope: the user's own bookings
        "booking:manage_any",  # may act on / create bookings for other users
    }
)

_ORGANIZER = {
    "event:create", "event:read", "event:read_own", "event:read_detail",
    "event:update", "event:publish",
    "booking:read", "booking:read_own_events",
}
_STAFF = {"event:read", "event:read_all", "event:read_detail", "booking:check_in"}
_ATTENDEE = {
    "event:read",
    "booking:create", "booking:read", "booking:read_own",
    "booking:update", "booking:cancel", "booking:pay",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "organizer": frozenset(_ORGANIZER),
    "staff": frozenset(_STAFF),
    "attendee": frozenset(_ATTENDEE),
}

# A PATCH that sets one of these statuses needs the extra permission (besides the *:update one).
EVENT_STATUS_PERMISSION: dict[str, str] = {"published": "event:publish"}
BOOKING_STATUS_PERMISSION: dict[str, str] = {
    "cancelled": "booking:cancel",
    "checked_in": "booking:check_in",
}
BOOKING_STATUS_DEFAULT_PERMISSION = "booking:manage"

# Fail at import time on typos rather than silently denying/allowing at runtime.
for _role, _perms in ROLE_PERMISSIONS.items():
    assert _perms <= ALL_PERMISSIONS, f"{_role} has unknown permissions: {_perms - ALL_PERMISSIONS}"
for _perm in (*EVENT_STATUS_PERMISSION.values(), *BOOKING_STATUS_PERMISSION.values(),
              BOOKING_STATUS_DEFAULT_PERMISSION):
    assert _perm in ALL_PERMISSIONS, f"unknown permission {_perm}"


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


@dataclass(frozen=True, slots=True)
class AuthUser:
    """The authenticated caller, as loaded fresh from the database on every request."""

    id: str
    role: str

    @property
    def oid(self) -> ObjectId:
        return ObjectId(self.id)

    def can(self, permission: str) -> bool:
        return has_permission(self.role, permission)
