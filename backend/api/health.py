"""Health endpoint.

The probes are module-level functions so tests can replace them without
touching the network.
"""

import psycopg
import redis
from fastapi import APIRouter

from api.models import DependencyStatus, HealthResponse
from config import get_settings

router = APIRouter()

VERSION = "0.1.0"

# Health must answer fast even when a dependency is wedged.
PROBE_TIMEOUT_SECONDS = 2


def check_postgres() -> DependencyStatus:
    """Open a connection and run the cheapest possible statement."""
    settings = get_settings()
    try:
        with psycopg.connect(
            settings.database_url, connect_timeout=PROBE_TIMEOUT_SECONDS
        ) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        return DependencyStatus(ok=False, detail=str(exc).strip())
    return DependencyStatus(ok=True)


def check_redis() -> DependencyStatus:
    """Ping Redis."""
    settings = get_settings()
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
            socket_timeout=PROBE_TIMEOUT_SECONDS,
        )
        client.ping()
    except redis.RedisError as exc:
        return DependencyStatus(ok=False, detail=str(exc).strip())
    return DependencyStatus(ok=True)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report liveness and dependency reachability.

    Always returns 200. A dependency being down is reported in the body as
    "degraded" rather than as an HTTP error, so a load balancer can keep the
    process in rotation while the UI can still show what is broken.
    """
    dependencies = {
        "postgres": check_postgres(),
        "redis": check_redis(),
    }
    all_ok = all(dep.ok for dep in dependencies.values())
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        version=VERSION,
        dependencies=dependencies,
    )
