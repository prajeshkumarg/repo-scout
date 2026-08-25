"""The RQ queue shared by the API (which enqueues) and the worker (which runs).

Indexing is always a background job, never work done in a request handler.
"""

import redis
from rq import Queue

from config import get_settings

INDEXING_QUEUE = "indexing"


def get_redis() -> redis.Redis:
    """Redis connection built from settings."""
    return redis.Redis.from_url(get_settings().redis_url)


def get_indexing_queue() -> Queue:
    """The queue indexing jobs are enqueued onto."""
    return Queue(INDEXING_QUEUE, connection=get_redis())
