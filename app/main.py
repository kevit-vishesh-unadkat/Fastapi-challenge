import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.core.config import get_settings
from app.core.database import create_client, ensure_indexes
from app.core.handlers import register_exception_handlers
from app.dependencies import get_current_user
from app.routers import auth, bookings, events, health, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = create_client(settings)
    db = client[settings.mongodb_db]
    await ensure_indexes(db)
    app.state.settings = settings
    app.state.db = db
    try:
        yield
    finally:
        await client.close()


app = FastAPI(title="TicketHub", version="2.0.0", lifespan=lifespan)
register_exception_handlers(app)

# Public: /auth/* and /health only.
app.include_router(auth.router)
app.include_router(health.router)

# Everything else requires a valid access token. Applying it at router level is a safety net:
# even a route that forgot `require(...)` cannot be reached anonymously.
_protected = [Depends(get_current_user)]
app.include_router(users.router, dependencies=_protected)
app.include_router(events.router, dependencies=_protected)
app.include_router(bookings.router, dependencies=_protected)
