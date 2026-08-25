"""Index endpoints: enqueue a repo, stream its progress over SSE.

Indexing never runs in the request handler; POST enqueues an RQ job and
returns immediately, and the SSE endpoint follows the job's Redis
progress channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.events import Done, ErrorEvent, Progress, sse
from db.conn import connect
from db.schema import ensure_schema
from ingest.clone import parse_github_url
from worker.jobs import index_repo_job, progress_channel
from worker.queue import get_indexing_queue, get_redis

logger = logging.getLogger(__name__)

router = APIRouter()

# How long the SSE stream waits for a message before re-checking state.
POLL_SECONDS = 1.0
# A run that never reaches a terminal state must not hold a stream open
# forever: an RQ work-horse can die without updating its own row.
STREAM_TIMEOUT_SECONDS = 3600.0


class IndexRequest(BaseModel):
    """Ask for a repo to be indexed."""

    url: str


class IndexResponse(BaseModel):
    """The accepted job: follow `events_url` for progress."""

    run_id: int
    status: str
    events_url: str


@router.post("/index", response_model=IndexResponse, status_code=202)
def create_index_run(request: IndexRequest) -> IndexResponse:
    """Enqueue an indexing job and return its run id."""
    try:
        parse_github_url(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with connect() as conn:
        conn.autocommit = True
        ensure_schema(conn)
        run_id = conn.execute(
            "INSERT INTO index_runs (url, status) VALUES (%s, 'queued') RETURNING id",
            (request.url,),
        ).fetchone()[0]

    get_indexing_queue().enqueue(index_repo_job, run_id, request.url, job_timeout=3600)
    return IndexResponse(
        run_id=run_id, status="queued", events_url=f"/index/{run_id}/events"
    )


@router.get("/index/{run_id}/events")
async def stream_index_events(run_id: int) -> StreamingResponse:
    """Stream one indexing run's progress as SSE."""
    with connect() as conn:
        row = conn.execute(
            "SELECT status FROM index_runs WHERE id = %s", (run_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no index run {run_id}")

    return StreamingResponse(
        _events(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _events(run_id: int) -> AsyncIterator[str]:
    """Yield SSE frames until the run reaches a terminal state."""
    pubsub = get_redis().pubsub()
    pubsub.subscribe(progress_channel(run_id))
    started = time.monotonic()
    try:
        while True:
            if time.monotonic() - started > STREAM_TIMEOUT_SECONDS:
                yield sse(
                    ErrorEvent(
                        code="stream_timeout",
                        message="indexing did not finish in time",
                        retryable=True,
                    )
                )
                return
            # get_message blocks; off the event loop it would stall every
            # other request served by this process.
            message = await asyncio.to_thread(
                pubsub.get_message,
                ignore_subscribe_messages=True,
                timeout=POLL_SECONDS,
            )
            if message is not None:
                payload = json.loads(message["data"])
                yield sse(
                    Progress(
                        stage=payload["stage"],
                        message=payload["message"],
                        percent=payload.get("percent"),
                    )
                )

            # The row reaches 'done' when the structure pass finishes,
            # but embedding continues after it, so the stream also waits
            # for the vector backlog to clear. That is read from the
            # database rather than from a "finished" message: pub/sub is
            # fire-and-forget, and a stream that waits for a message it
            # may never receive hangs until its timeout.
            status, error, stats, pending = await asyncio.to_thread(_run_state, run_id)
            if status == "done" and pending == 0:
                yield sse(
                    Done(
                        steps=0,
                        tokens=0,
                        ms=int(sum((stats or {}).get("stage_ms", {}).values())),
                    )
                )
                return
            if status == "failed":
                yield sse(
                    ErrorEvent(
                        code="index_failed",
                        message=error or "indexing failed",
                        retryable=True,
                    )
                )
                return
            await asyncio.sleep(0)
    except Exception as exc:  # a dying stream must say so before closing
        logger.exception("index event stream failed for run %s", run_id)
        yield sse(ErrorEvent(code="stream_failed", message=str(exc), retryable=True))
    finally:
        pubsub.close()


def _run_state(run_id: int) -> tuple[str, str | None, dict | None, int]:
    """Status of a run, plus how many chunks still lack a vector."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.status, r.error, r.stats,
                   coalesce((
                       SELECT count(*) FROM chunks c
                       WHERE c.repo_id = r.repo_id AND c.sha = r.sha
                         AND c.embedding IS NULL
                   ), 0)
            FROM index_runs r WHERE r.id = %s
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return ("failed", "run vanished", None, 0)
    return (row[0], row[1], row[2], row[3])
