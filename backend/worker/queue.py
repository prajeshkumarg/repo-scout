"""The RQ queue shared by the API (which enqueues) and the worker (which runs).

Indexing is always a background job, never work done in a request handler.
"""

import redis
from rq import Queue

from config import get_settings

INDEXING_QUEUE = "indexing"
# Vector backlog. A separate queue so the worker can drain interactive
# structure passes first; embedding is the slow stage and nobody waits
# on it to browse or ask questions.
EMBEDDING_QUEUE = "embedding"


def get_redis() -> redis.Redis:
    """Redis connection built from settings."""
    return redis.Redis.from_url(get_settings().redis_url)


def get_indexing_queue() -> Queue:
    """The queue indexing jobs are enqueued onto."""
    return Queue(INDEXING_QUEUE, connection=get_redis())


def get_embedding_queue() -> Queue:
    """The queue the vector backlog is worked through on."""
    return Queue(EMBEDDING_QUEUE, connection=get_redis())
