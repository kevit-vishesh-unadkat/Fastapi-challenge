from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.common.types import ObjectIdStr, UtcDatetime
from app.schemas.base import StrictModel, UpdateModel



class EventStatus(str, Enum):
    draft = "draft"
    published = "published"
    completed = "completed"
    cancelled = "cancelled"


class Venue(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    city: Annotated[str, Field(min_length=1, max_length=80)]


class TicketTierIn(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=50)]
    price_inr: Annotated[int, Field(strict=True, ge=0)]
    quota: Annotated[int, Field(strict=True, ge=1)]


def _unique_tier_names(tiers: list[TicketTierIn]) -> list[TicketTierIn]:
    names = [t.name.lower() for t in tiers]
    if len(set(names)) != len(names):
        raise ValueError("ticket tier names must be unique")
    return tiers


TierList = Annotated[list[TicketTierIn], Field(min_length=1), AfterValidator(_unique_tier_names)]
Title = Annotated[str, Field(min_length=5, max_length=120)]
Capacity = Annotated[int, Field(strict=True, ge=1, le=50_000)]


def _check_quota(capacity: int, tiers: list[TicketTierIn]) -> None:
    if sum(t.quota for t in tiers) > capacity:
        raise ValueError("sum of ticket tier quotas must not exceed capacity")


class EventCreate(StrictModel):
    title: Title
    venue: Venue
    starts_at: UtcDatetime
    ends_at: UtcDatetime
    capacity: Capacity
    ticket_tiers: TierList
    organizer_id: ObjectIdStr | None = None  # organizers: defaults to self; admins: required

    @model_validator(mode="after")
    def _cross_checks(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        _check_quota(self.capacity, self.ticket_tiers)
        return self


class EventUpdate(UpdateModel):
    title: Title | None = None
    venue: Venue | None = None
    starts_at: UtcDatetime | None = None
    ends_at: UtcDatetime | None = None
    capacity: Capacity | None = None
    ticket_tiers: TierList | None = None
    status: EventStatus | None = None

    @model_validator(mode="after")
    def _cross_checks(self):
        # Only checks what is visible in this payload; the service checks the merged result.
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.capacity and self.ticket_tiers:
            _check_quota(self.capacity, self.ticket_tiers)
        return self


class TicketTierRead(BaseModel):
    name: str
    price_inr: int
    quota: int
    remaining: int


class EventRead(BaseModel):
    id: str
    title: str
    venue: Venue
    starts_at: datetime
    ends_at: datetime
    capacity: int
    ticket_tiers: list[TicketTierRead]
    status: EventStatus
    organizer_id: str
    version: int

    @classmethod
    def from_doc(cls, doc: dict) -> "EventRead":
        return cls.model_validate(
            {**doc, "id": str(doc["_id"]), "organizer_id": str(doc["organizer_id"])}
        )


class TicketTierPublic(BaseModel):
    name: str
    price_inr: int
    available: bool  # no quota / remaining / sold counts


class EventPublic(BaseModel):
    """R2.7 - what attendees get: no per-tier sales, no organizer or versioning fields."""

    id: str
    title: str
    venue: Venue
    starts_at: datetime
    ends_at: datetime
    ticket_tiers: list[TicketTierPublic]

    @classmethod
    def from_doc(cls, doc: dict) -> "EventPublic":
        tiers = [
            {"name": t["name"], "price_inr": t["price_inr"], "available": t["remaining"] > 0}
            for t in doc["ticket_tiers"]
        ]
        return cls.model_validate({**doc, "id": str(doc["_id"]), "ticket_tiers": tiers})
