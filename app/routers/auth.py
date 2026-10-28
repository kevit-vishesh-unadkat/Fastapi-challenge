from fastapi import APIRouter, Body, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.core.permissions import AuthUser
from app.dependencies import (
    bearer_scheme,
    get_auth_service,
    get_current_user,
    get_user_service,
)
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, TokenPair
from app.schemas.user import UserRead
from app.services.auth_service import AuthService
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: RegisterRequest, service: AuthService = Depends(get_auth_service)):
    return await service.register(payload)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, service: AuthService = Depends(get_auth_service)):
    return await service.login(payload)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, service: AuthService = Depends(get_auth_service)):
    return await service.refresh(payload.refresh_token)


@router.post("/logout", status_code=204, response_class=Response)
async def logout(
    payload: LogoutRequest | None = Body(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    service: AuthService = Depends(get_auth_service),
):
    await service.logout(
        refresh_token=payload.refresh_token if payload else None,
        access_token=credentials.credentials if credentials else None,
    )
    return Response(status_code=204)


@router.get("/me", response_model=UserRead)
async def me(
    user: AuthUser = Depends(get_current_user), service: UserService = Depends(get_user_service)
):
    return await service.get(user.id)
