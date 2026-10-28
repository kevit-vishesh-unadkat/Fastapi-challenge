import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from bson import ObjectId

from app.common.types import OBJECT_ID_RE
from app.core.errors import UnprocessableError

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ONE_MS = timedelta(milliseconds=1)


def _invalid() -> UnprocessableError:
    return UnprocessableError("Invalid cursor", code="INVALID_CURSOR")


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> dict[str, Any]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except ValueError:  # covers binascii.Error, JSONDecodeError, UnicodeDecodeError
        raise _invalid()
    if not isinstance(data, dict):
        raise _invalid()
    return data


def _object_id(raw: Any) -> ObjectId:
    if not isinstance(raw, str) or not OBJECT_ID_RE.fullmatch(raw):
        raise _invalid()
    return ObjectId(raw)


def decode_id_cursor(cursor: str) -> ObjectId:
    return _object_id(_decode(cursor).get("id"))


def decode_event_cursor(cursor: str) -> tuple[datetime, ObjectId]:
    data = _decode(cursor)
    millis = data.get("s")
    if isinstance(millis, bool) or not isinstance(millis, int):
        raise _invalid()
    try:
        starts_at = _EPOCH + millis * _ONE_MS
    except OverflowError:
        raise _invalid()
    return starts_at, _object_id(data.get("id"))


def event_cursor_payload(doc: dict[str, Any]) -> dict[str, Any]:
    return {"s": (doc["starts_at"] - _EPOCH) // _ONE_MS, "id": str(doc["_id"])}


def slice_page(
    docs: list[dict[str, Any]], limit: int, make_cursor: Callable[[dict[str, Any]], dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """Repos fetch limit+1 rows; the extra row only signals that another page exists."""
    if len(docs) <= limit:
        return docs, None
    page = docs[:limit]
    return page, encode_cursor(make_cursor(page[-1]))
