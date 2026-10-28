import uuid
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.core.config import Settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.permissions import AuthUser
from app.core.security import (
    burn_password_check,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.repositories.denylist_repository import DenylistRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair
from app.schemas.user import UserRead, UserRole


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        tokens: RefreshTokenRepository,
        denylist: DenylistRepository,
        settings: Settings,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._denylist = denylist
        self._settings = settings

    # ------------------------------------------------------------------ R2.1
    async def register(self, payload: RegisterRequest) -> UserRead:
        doc = {
            "email": payload.email,
            "name": payload.name,
            "role": UserRole.attendee.value,  # self-registration is attendee-only
            "is_active": True,
            "password_hash": await hash_password(payload.password),
        }
        return UserRead.from_doc(await self._users.insert(doc))

    async def login(self, payload: LoginRequest) -> TokenPair:
        invalid = UnauthorizedError("Invalid email or password", code="INVALID_CREDENTIALS")
        user = await self._users.get_by_email(payload.email)
        password_hash = user.get("password_hash") if user else None
        if not password_hash:
            await burn_password_check(payload.password)  # same cost whether or not the email exists
            raise invalid
        if not await verify_password(password_hash, payload.password):
            raise invalid
        if not user["is_active"]:
            raise ForbiddenError("Account is inactive", code="ACCOUNT_INACTIVE")
        return await self._issue(user, family_id=uuid.uuid4().hex)  # new login = new family

    # ------------------------------------------------------------------ R2.3
    async def refresh(self, raw_token: str) -> TokenPair:
        token_hash = hash_token(raw_token)
        record = await self._tokens.consume(token_hash)  # atomic: only one caller can win

        if record is None:
            existing = await self._tokens.get_by_hash(token_hash)
            if existing is None:
                raise UnauthorizedError("Invalid refresh token", code="INVALID_TOKEN")
            # Known token that can no longer be used: replay (or post-logout use).
            await self._revoke_family(existing["family_id"])
            if existing["used"]:
                raise UnauthorizedError(
                    "Refresh token was already used; this login has been revoked",
                    code="REFRESH_TOKEN_REUSED",
                )
            raise UnauthorizedError("Refresh token has been revoked", code="TOKEN_REVOKED")

        if record["expires_at"] <= _now():
            raise UnauthorizedError("Refresh token has expired", code="TOKEN_EXPIRED")

        user = await self._users.get(record["user_id"])
        if user is None or not user["is_active"]:
            await self._revoke_family(record["family_id"])
            raise UnauthorizedError("Account is not available", code="INVALID_TOKEN")

        pair = await self._issue(user, family_id=record["family_id"])

        # Close the race with a concurrent logout / reuse-revocation that landed between
        # consuming the old token and inserting the new one.
        if await self._tokens.family_has_revoked(record["family_id"]):
            await self._revoke_family(record["family_id"])
            raise UnauthorizedError("Refresh token has been revoked", code="TOKEN_REVOKED")
        return pair

    # ------------------------------------------------------------------ R2.4
    async def logout(self, *, refresh_token: str | None, access_token: str | None) -> None:
        """Ends the whole login: every refresh token and every access token issued by it."""
        if refresh_token is None and access_token is None:
            raise UnauthorizedError("Provide the access token or a refresh token to log out")

        families: set[str] = set()
        denied: list[tuple[str, datetime]] = []

        if access_token is not None:
            try:
                claims = decode_access_token(access_token, self._settings.jwt_secret)
            except UnauthorizedError:
                if refresh_token is None:
                    raise  # nothing else identifies the session
            else:
                denied.append((claims["jti"], claims["exp_at"]))
                record = await self._tokens.get_by_access_jti(claims["jti"])
                if record:
                    families.add(record["family_id"])

        if refresh_token is not None:
            record = await self._tokens.get_by_hash(hash_token(refresh_token))
            if record:
                families.add(record["family_id"])

        for family_id in families:
            await self._revoke_family(family_id)
        await self._denylist.add_many(denied)

    # ------------------------------------------------------------------ per-request auth
    async def authenticate(self, access_token: str) -> AuthUser:
        claims = decode_access_token(access_token, self._settings.jwt_secret)
        if await self._denylist.contains(claims["jti"]):
            raise UnauthorizedError("Access token has been revoked", code="TOKEN_REVOKED")
        user = await self._users.get(ObjectId(claims["sub"]))
        if user is None:
            raise UnauthorizedError("Invalid access token", code="INVALID_TOKEN")
        if not user["is_active"]:
            raise ForbiddenError("Account is inactive", code="ACCOUNT_INACTIVE")
        # Role comes from the database so role changes / deactivation apply immediately.
        return AuthUser(id=str(user["_id"]), role=user["role"])

    # ------------------------------------------------------------------ internals
    async def _issue(self, user: dict, *, family_id: str) -> TokenPair:
        s = self._settings
        access = create_access_token(
            user_id=str(user["_id"]),
            role=user["role"],
            secret=s.jwt_secret,
            ttl=timedelta(minutes=s.access_token_minutes),
        )
        raw_refresh = new_refresh_token()
        await self._tokens.insert(
            {
                "token_hash": hash_token(raw_refresh),
                "user_id": user["_id"],
                "family_id": family_id,
                "access_jti": access.jti,  # lets us denylist this login's access tokens later
                "access_exp": access.expires_at,
                "expires_at": _now() + timedelta(days=s.refresh_token_days),
                "used": False,
                "revoked": False,
            }
        )
        return TokenPair(
            access_token=access.token,
            refresh_token=raw_refresh,
            expires_in=s.access_token_minutes * 60,
        )

    async def _revoke_family(self, family_id: str) -> None:
        live = await self._tokens.revoke_family(family_id, _now())
        await self._denylist.add_many([(r["access_jti"], r["access_exp"]) for r in live])
