from datetime import datetime

from pymongo import UpdateOne
from pymongo.asynchronous.collection import AsyncCollection


class DenylistRepository:
    """R2.4 - revoked access-token ids. A TTL index on `exp` removes entries automatically."""

    def __init__(self, collection: AsyncCollection) -> None:
        self._col = collection

    async def contains(self, jti: str) -> bool:
        return await self._col.find_one({"_id": jti}, {"_id": 1}) is not None

    async def add_many(self, entries: list[tuple[str, datetime]]) -> None:
        ops = [
            UpdateOne({"_id": jti}, {"$setOnInsert": {"exp": exp}}, upsert=True)
            for jti, exp in entries
        ]
        if ops:
            await self._col.bulk_write(ops, ordered=False)
