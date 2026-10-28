from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError

from app.core.errors import ConflictError


def _duplicate_email() -> ConflictError:
    return ConflictError("A user with this email already exists", code="EMAIL_ALREADY_EXISTS")


class UserRepository:
    def __init__(self, collection: AsyncCollection) -> None:
        self._col = collection

    async def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._col.insert_one(doc)
        except DuplicateKeyError:
            raise _duplicate_email()
        doc["_id"] = result.inserted_id
        return doc

    async def get(self, user_id: ObjectId) -> dict[str, Any] | None:
        return await self._col.find_one({"_id": user_id})

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        return await self._col.find_one({"email": email})

    async def list_page(self, after: ObjectId | None, limit: int) -> list[dict[str, Any]]:
        query = {"_id": {"$gt": after}} if after else {}
        return await self._col.find(query).sort("_id", 1).limit(limit + 1).to_list(limit + 1)

    async def update(self, user_id: ObjectId, changes: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return await self._col.find_one_and_update(
                {"_id": user_id}, {"$set": changes}, return_document=ReturnDocument.AFTER
            )
        except DuplicateKeyError:
            raise _duplicate_email()

    async def delete(self, user_id: ObjectId) -> bool:
        return (await self._col.delete_one({"_id": user_id})).deleted_count == 1
