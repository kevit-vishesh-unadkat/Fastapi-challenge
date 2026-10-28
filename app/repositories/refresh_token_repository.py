from datetime import datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection


class RefreshTokenRepository:
    """Only SHA-256 hashes of refresh tokens are ever stored (R2.2)."""

    def __init__(self, collection: AsyncCollection) -> None:
        self._col = collection

    async def insert(self, doc: dict[str, Any]) -> None:
        await self._col.insert_one(doc)

    async def consume(self, token_hash: str) -> dict[str, Any] | None:
        """Atomically mark an unused, unrevoked token as used. Exactly one caller can win."""
        return await self._col.find_one_and_update(
            {"token_hash": token_hash, "used": False, "revoked": False},
            {"$set": {"used": True}},
            return_document=ReturnDocument.AFTER,
        )

    async def get_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        return await self._col.find_one({"token_hash": token_hash})

    async def get_by_access_jti(self, jti: str) -> dict[str, Any] | None:
        return await self._col.find_one({"access_jti": jti})

    async def revoke_family(self, family_id: str, now: datetime) -> list[dict[str, Any]]:
        """Revoke every refresh token of one login; return its still-live access tokens."""
        await self._col.update_many(
            {"family_id": family_id, "revoked": False}, {"$set": {"revoked": True}}
        )
        cursor = self._col.find(
            {"family_id": family_id, "access_exp": {"$gt": now}}, {"access_jti": 1, "access_exp": 1}
        )
        return await cursor.to_list(None)

    async def family_has_revoked(self, family_id: str) -> bool:
        return await self._col.find_one({"family_id": family_id, "revoked": True}, {"_id": 1}) is not None
