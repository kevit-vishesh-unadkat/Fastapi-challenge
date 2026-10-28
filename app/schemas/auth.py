from typing import Annotated

from pydantic import BaseModel, Field

from app.common.types import EmailStr, LoginPassword, Password
from app.schemas.base import StrictModel
from app.schemas.user import Name

RefreshTokenStr = Annotated[str, Field(min_length=1, max_length=512)]


class RegisterRequest(StrictModel):
    # No `role` here: unknown fields are rejected, so self-registration can only make attendees.
    email: EmailStr
    name: Name
    password: Password


class LoginRequest(StrictModel):
    email: EmailStr
    password: LoginPassword


class RefreshRequest(StrictModel):
    refresh_token: RefreshTokenStr


class LogoutRequest(StrictModel):
    refresh_token: RefreshTokenStr | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires
