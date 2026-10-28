from datetime import timezone

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings


def create_client(settings: Settings) -> AsyncMongoClient:
    return AsyncMongoClient(
        settings.mongodb_uri,
        tz_aware=True,
        tzinfo=timezone.utc,
        serverSelectionTimeoutMS=5000,
    )


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Idempotent. R1.4 indexes, R2.4 TTL denylist, plus supporting lookups."""
    # --- R1.4 ---
    await db.users.create_index("email", unique=True, name="uniq_users_email")
    await db.events.create_index(
        [("status", ASCENDING), ("starts_at", ASCENDING)], name="events_status_starts_at"
    )
    await db.events.create_index([("title", "text")], name="events_title_text")
    await db.bookings.create_index(
        [("status", ASCENDING), ("hold_expires_at", ASCENDING)],
        name="bookings_status_hold_expires_at",
    )
    # --- supporting indexes (delete guards, ownership-scoped listing) ---
    await db.bookings.create_index("event_id", name="bookings_event_id")
    await db.bookings.create_index([("user_id", ASCENDING), ("_id", ASCENDING)], name="bookings_user_id_id")
    await db.bookings.create_index(
        [("organizer_id", ASCENDING), ("_id", ASCENDING)], name="bookings_organizer_id_id"
    )
    await db.events.create_index("organizer_id", name="events_organizer_id")
    # --- R2.4: denylisted access-token ids vanish once the token would have expired anyway ---
    await db.token_denylist.create_index("exp", expireAfterSeconds=0, name="denylist_exp_ttl")
    # --- R2.2/R2.3: refresh tokens (hash only) ---
    await db.refresh_tokens.create_index("token_hash", unique=True, name="uniq_refresh_token_hash")
    await db.refresh_tokens.create_index("family_id", name="refresh_family_id")
    await db.refresh_tokens.create_index("access_jti", name="refresh_access_jti")
    await db.refresh_tokens.create_index("expires_at", expireAfterSeconds=0, name="refresh_expires_ttl")
