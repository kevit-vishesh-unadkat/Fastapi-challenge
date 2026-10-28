import re
from datetime import timezone
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, EmailStr, PlainValidator

OBJECT_ID_RE = re.compile(r"[0-9a-fA-F]{24}")


def _object_id(value: str) -> str:
    if not OBJECT_ID_RE.fullmatch(value):
        raise ValueError("must be a valid 24-character hex ObjectId")
    return value.lower()


def _to_utc(value):
    return value.astimezone(timezone.utc)


ObjectIdStr = Annotated[str, AfterValidator(_object_id)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]  # tz required, stored as UTC
Email = Annotated[EmailStr, AfterValidator(str.lower)]


# Passwords must NOT be whitespace-trimmed like other strings, so a plain validator is used
# (it bypasses the model-wide str_strip_whitespace setting).
def _new_password(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("must be a string")
    if len(value) < 12:
        raise ValueError("must be at least 12 characters")
    if len(value) > 128:
        raise ValueError("must be at most 128 characters")
    return value


def _login_password(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("must be a non-empty string")
    if len(value) > 128:
        raise ValueError("must be at most 128 characters")
    return value


Password = Annotated[str, PlainValidator(_new_password, json_schema_input_type=str)]
LoginPassword = Annotated[str, PlainValidator(_login_password, json_schema_input_type=str)]
