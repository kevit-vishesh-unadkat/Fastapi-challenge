from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StrictBool

from app.common.types import Email, Password
from app.schemas.base import StrictModel, UpdateModel

Name = Annotated[str, Field(min_length=1, max_length=100)]


class UserRole(str, Enum):
    admin = "admin"
    organizer = "organizer"
    staff = "staff"
    attendee = "attendee"


class UserCreate(StrictModel):
    email: Email
    name: Name
    password: Password
    role: UserRole = UserRole.attendee
    is_active: StrictBool = True


class UserUpdate(UpdateModel):
    email: Email | None = None
    name: Name | None = None
    role: UserRole | None = None
    is_active: StrictBool | None = None


class UserRead(BaseModel):
    id: str
    email: str
    name: str
    role: UserRole
    is_active: bool

    @classmethod
    def from_doc(cls, doc: dict) -> "UserRead":
        return cls.model_validate({**doc, "id": str(doc["_id"])})
