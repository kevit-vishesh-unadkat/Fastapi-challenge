from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

from app.common.types import ObjectIdStr
from app.schemas.base import StrictModel, UpdateModel


class BookingStatus(str, Enum):
    pending_payment = "pending_payment"
    confirmed = "confirmed"
    checked_in = "checked_in"
    cancelled = "cancelled"
    expired = "expired"
    refunded = "refunded"


class BookingCreate(StrictModel):
    # amount_inr and status are server-controlled and therefore not accepted here.
    event_id: ObjectIdStr
    user_id: ObjectIdStr | None = None  # attendees: defaults to self; admins: required
    tier: Annotated[str, Field(min_length=1, max_length=50)]
    quantity: Annotated[int, Field(strict=True, ge=1, le=6)]


class BookingUpdate(UpdateModel):
    status: BookingStatus


class BookingRead(BaseModel):
    id: str
    event_id: str
    user_id: str
    tier: str
    quantity: int
    amount_inr: int
    status: BookingStatus
    hold_expires_at: datetime

    @classmethod
    def from_doc(cls, doc: dict) -> "BookingRead":
        return cls.model_validate(
            {
                **doc,
                "id": str(doc["_id"]),
                "event_id": str(doc["event_id"]),
                "user_id": str(doc["user_id"]),
            }
        )
