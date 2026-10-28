from fastapi import APIRouter, Depends, Query, Response

from app.common.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.common.types import ObjectIdStr
from app.dependencies import get_user_service, require
from app.schemas.base import Page
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "", response_model=UserRead, status_code=201, dependencies=[Depends(require("user:create"))]
)
async def create_user(payload: UserCreate, service: UserService = Depends(get_user_service)):
    return await service.create(payload)


@router.get("", response_model=Page[UserRead], dependencies=[Depends(require("user:read"))])
async def list_users(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=512),
    service: UserService = Depends(get_user_service),
):
    return await service.list(limit, cursor)


@router.get("/{user_id}", response_model=UserRead, dependencies=[Depends(require("user:read"))])
async def get_user(user_id: ObjectIdStr, service: UserService = Depends(get_user_service)):
    return await service.get(user_id)


@router.patch("/{user_id}", response_model=UserRead, dependencies=[Depends(require("user:update"))])
async def update_user(
    user_id: ObjectIdStr, payload: UserUpdate, service: UserService = Depends(get_user_service)
):
    return await service.update(user_id, payload)


@router.delete(
    "/{user_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require("user:delete"))],
)
async def delete_user(user_id: ObjectIdStr, service: UserService = Depends(get_user_service)):
    await service.delete(user_id)
    return Response(status_code=204)
