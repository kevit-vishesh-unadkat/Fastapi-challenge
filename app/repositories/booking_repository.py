from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection


class BookingRepository:
    def __init__(self, collection: AsyncCollection) -> None:
        self._col = collection

    async def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        result = await self._col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def get(
        self, booking_id: ObjectId, scope: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """`scope` is an ownership filter (R2.6); rows outside it look non-existent."""
        return await self._col.find_one({"_id": booking_id, **(scope or {})})

    async def list_page(
        self, after: ObjectId | None, limit: int, scope: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = dict(scope or {})
        if after:
            query["_id"] = {"$gt": after}
        return await self._col.find(query).sort("_id", 1).limit(limit + 1).to_list(limit + 1)

    async def transition(
        self, booking_id: ObjectId, from_status: str, to_status: str
    ) -> dict[str, Any] | None:
        """Compare-and-set on status so two concurrent transitions cannot both win."""
        return await self._col.find_one_and_update(
            {"_id": booking_id, "status": from_status},
            {"$set": {"status": to_status}},
            return_document=ReturnDocument.AFTER,
        )

    async def delete(self, booking_id: ObjectId) -> dict[str, Any] | None:
        """Atomic: returns the deleted document exactly once."""
        return await self._col.find_one_and_delete({"_id": booking_id})

    async def exists_for_event(self, event_id: ObjectId) -> bool:
        return await self._col.find_one({"event_id": event_id}, {"_id": 1}) is not None

    async def exists_for_user(self, user_id: ObjectId) -> bool:
        return await self._col.find_one({"user_id": user_id}, {"_id": 1}) is not None
