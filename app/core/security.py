import asyncio
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.common.types import OBJECT_ID_RE
from app.core.errors import UnauthorizedError

ALGORITHM = "HS256"  # fixed on purpose: never driven by config or by the token header

_hasher = PasswordHasher()  # argon2id
_DUMMY_HASH = _hasher.hash("tickethub-dummy-password")  # to equalise timing for unknown emails


# ---- passwords (CPU heavy -> thread pool so the event loop stays free) ----------------
async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(_verify)


async def burn_password_check(password: str) -> None:
    await verify_password(_DUMMY_HASH, password)


# ---- access tokens (JWT) -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    jti: str
    expires_at: datetime


def create_access_token(*, user_id: str, role: str, secret: str, ttl: timedelta) -> AccessToken:
    now = datetime.now(timezone.utc)
    expires_at = now + ttl
    jti = uuid.uuid4().hex
    token = jwt.encode(
        {"sub": user_id, "role": role, "jti": jti, "typ": "access", "iat": now, "exp": expires_at},
        secret,
        algorithm=ALGORITHM,
    )
    return AccessToken(token=token, jti=jti, expires_at=expires_at)


def decode_access_token(token: str, secret: str) -> dict:
    """Returns the claims, plus `exp_at` (datetime). Raises 401 TOKEN_EXPIRED / INVALID_TOKEN."""
    invalid = UnauthorizedError("Invalid access token", code="INVALID_TOKEN")
    try:
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub", "jti"]}
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Access token has expired", code="TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise invalid
    if (
        claims.get("typ") != "access"
        or not isinstance(claims["sub"], str)
        or not OBJECT_ID_RE.fullmatch(claims["sub"])
        or not isinstance(claims["jti"], str)
    ):
        raise invalid
    claims["exp_at"] = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    return claims


# ---- refresh tokens (opaque, high entropy; only the SHA-256 is stored) ----------------
def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
