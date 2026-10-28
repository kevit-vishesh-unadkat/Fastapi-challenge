from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection


class EventRepository:
    def __init__(self, collection: AsyncCollection) -> None:
        self._col = collection

    async def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        result = await self._col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def get(
        self, event_id: ObjectId, scope: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """`scope` is an ownership/visibility filter (R2.6); rows outside it look non-existent."""
        return await self._col.find_one({"_id": event_id, **(scope or {})})

    async def list_page(
        self,
        *,
        city: str | None,
        status: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        q: str | None,
        after: tuple[datetime, ObjectId] | None,
        limit: int,
        scope: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[dict[str, Any]] = []
        if scope:
            clauses.append(scope)
        if status:
            clauses.append({"status": status})
        if city:
            clauses.append({"venue.city": city})
        if date_from or date_to:
            window: dict[str, datetime] = {}
            if date_from:
                window["$gte"] = date_from
            if date_to:
                window["$lte"] = date_to
            clauses.append({"starts_at": window})
        if q:
            clauses.append({"$text": {"$search": q}})
        if after:
            starts_at, last_id = after
            # Keyset pagination on (starts_at, _id): stable even with equal start times.
            clauses.append(
                {
                    "$or": [
                        {"starts_at": {"$gt": starts_at}},
                        {"starts_at": starts_at, "_id": {"$gt": last_id}},
                    ]
                }
            )
        query = {"$and": clauses} if clauses else {}
        cursor = self._col.find(query).sort([("starts_at", 1), ("_id", 1)]).limit(limit + 1)
        return await cursor.to_list(limit + 1)

    async def update_versioned(
        self, event_id: ObjectId, version: int, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Optimistic lock: applies only if the stored version still matches."""
        return await self._col.find_one_and_update(
            {"_id": event_id, "version": version},
            {"$set": changes, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )

    async def delete_unless_published(self, event_id: ObjectId) -> bool:
        result = await self._col.delete_one({"_id": event_id, "status": {"$ne": "published"}})
        return result.deleted_count == 1

    async def exists_for_organizer(self, user_id: ObjectId) -> bool:
        return await self._col.find_one({"organizer_id": user_id}, {"_id": 1}) is not None

    # --- seat accounting (R1.2) -------------------------------------------------
    async def reserve_seats(
        self, event_id: ObjectId, tier: str, quantity: int
    ) -> dict[str, Any] | None:
        """Single atomic update: matches only if the event is published AND the tier
        still has >= quantity remaining. Returns the updated event, or None."""
        return await self._col.find_one_and_update(
            {
                "_id": event_id,
                "status": "published",
                "ticket_tiers": {"$elemMatch": {"name": tier, "remaining": {"$gte": quantity}}},
            },
            {"$inc": {"ticket_tiers.$.remaining": -quantity}},
            return_document=ReturnDocument.AFTER,
        )

    async def release_seats(self, event_id: ObjectId, tier: str, quantity: int) -> None:
        await self._col.update_one(
            {"_id": event_id, "ticket_tiers.name": tier},
            {"$inc": {"ticket_tiers.$.remaining": quantity}},
        )
