from fastapi import APIRouter, Depends, Query, Response

from app.common.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.common.types import ObjectIdStr
from app.core.permissions import AuthUser
from app.dependencies import Authorized, authorize_booking_update, get_booking_service, require
from app.schemas.base import Page
from app.schemas.booking import BookingCreate, BookingRead
from app.services.booking_service import BookingService

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingRead, status_code=201)
async def create_booking(
    payload: BookingCreate,
    user: AuthUser = Depends(require("booking:create")),
    service: BookingService = Depends(get_booking_service),
):
    return await service.create(payload, user)


@router.get("", response_model=Page[BookingRead])
async def list_bookings(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=512),
    user: AuthUser = Depends(require("booking:read")),
    service: BookingService = Depends(get_booking_service),
):
    return await service.list(limit, cursor, user)


@router.get("/{booking_id}", response_model=BookingRead)
async def get_booking(
    booking_id: ObjectIdStr,
    user: AuthUser = Depends(require("booking:read")),
    service: BookingService = Depends(get_booking_service),
):
    return await service.get(booking_id, user)


@router.patch("/{booking_id}", response_model=BookingRead)
async def update_booking(
    booking_id: ObjectIdStr,
    auth: Authorized = Depends(authorize_booking_update),  # booking:update + per-status permission
    service: BookingService = Depends(get_booking_service),
):
    return await service.update(booking_id, auth.payload, auth.user)


@router.post(
    "/{booking_id}/check-in",
    response_model=BookingRead,
    dependencies=[Depends(require("booking:check_in"))],
)
async def check_in_booking(
    booking_id: ObjectIdStr, service: BookingService = Depends(get_booking_service)
):
    return await service.check_in(booking_id)


@router.delete(
    "/{booking_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require("booking:delete"))],
)
async def delete_booking(
    booking_id: ObjectIdStr, service: BookingService = Depends(get_booking_service)
):
    await service.delete(booking_id)
    return Response(status_code=204)
