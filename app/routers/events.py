from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response

from app.common.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.common.types import ObjectIdStr
from app.core.permissions import AuthUser
from app.dependencies import (
    Authorized,
    authorize_event_update,
    get_event_service,
    require,
    require_if_match,
)
from app.schemas.base import Page
from app.schemas.event import EventCreate, EventPublic, EventRead, EventStatus
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventRead, status_code=201)
async def create_event(
    payload: EventCreate,
    user: AuthUser = Depends(require("event:create")),
    service: EventService = Depends(get_event_service),
):
    return await service.create(payload, user)


# The service picks EventRead or EventPublic from the caller's permissions (R2.7).
@router.get("", response_model=Page[EventRead] | Page[EventPublic])
async def list_events(
    city: str | None = Query(None, max_length=80),
    status: EventStatus | None = None,
    date_from: datetime | None = Query(None, description="starts_at >= this (ISO 8601)"),
    date_to: datetime | None = Query(None, description="starts_at <= this (ISO 8601)"),
    q: str | None = Query(None, max_length=100, description="text search on title"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=512),
    user: AuthUser = Depends(require("event:read")),
    service: EventService = Depends(get_event_service),
):
    return await service.list(
        city=city,
        status=status,
        date_from=date_from,
        date_to=date_to,
        q=q,
        limit=limit,
        cursor=cursor,
        user=user,
    )


@router.get("/{event_id}", response_model=EventRead | EventPublic)
async def get_event(
    event_id: ObjectIdStr,
    user: AuthUser = Depends(require("event:read")),
    service: EventService = Depends(get_event_service),
):
    return await service.get(event_id, user)


@router.patch("/{event_id}", response_model=EventRead)
async def update_event(
    event_id: ObjectIdStr,
    auth: Authorized = Depends(authorize_event_update),  # event:update (+ event:publish to publish)
    version: int = Depends(require_if_match),
    service: EventService = Depends(get_event_service),
):
    return await service.update(event_id, version, auth.payload, auth.user)


@router.delete(
    "/{event_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require("event:delete"))],
)
async def delete_event(event_id: ObjectIdStr, service: EventService = Depends(get_event_service)):
    await service.delete(event_id)
    return Response(status_code=204)
