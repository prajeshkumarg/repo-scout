"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.conversations import router as conversations_router
from api.health import router as health_router
from api.indexing import router as indexing_router
from api.repos import router as repos_router
from config import get_settings
from db.conn import connect
from db.schema import ensure_schema

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the schema once, before the first request.

    Read-only endpoints used to query tables that a fresh database has
    never had: only the write paths called ensure_schema, so a brand new
    deployment failed on whichever endpoint was hit first. Doing it here
    means a handler can assume the tables exist.
    """
    try:
        with connect() as conn:
            conn.autocommit = True
            ensure_schema(conn)
    except Exception:  # health reports it; do not refuse to boot
        logger.exception("could not ensure the schema at startup")
    yield


app = FastAPI(title="repo-scout", version="0.1.0", lifespan=lifespan)

# In development the origin is not always localhost: opening `make dev`
# from a phone or another machine arrives as http://192.168.x.x:3000, and
# a localhost-only allowlist rejects it with an opaque failed fetch. Those
# private ranges are allowed only until ALLOWED_ORIGINS is set — once a
# deployment names its origin, that is the whole list, because a public
# server has no reason to trust anyone's LAN.
_settings = get_settings()
_LAN_ORIGINS = (
    r"http://(192\.168\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):3000"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.origin_list
    or ["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=None if _settings.origin_list else _LAN_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(indexing_router)
app.include_router(conversations_router)
app.include_router(repos_router)
