"""The background indexing job.

Indexing is always a background job, never work done in a request
handler (CLAUDE.md). Progress is published to a Redis channel per
index run; the API subscribes and re-emits it as SSE.
"""

from __future__ import annotations

import json
import logging

from config import get_settings
from db.conn import connect
from db.schema import ensure_schema
from ingest.pipeline import embed_pending
from ingest.pipeline import run as index_repo
from worker.queue import get_indexing_queue, get_redis

logger = logging.getLogger(__name__)


def progress_channel(run_id: int) -> str:
    """The Redis pub/sub channel carrying one run's progress."""
    return f"index:{run_id}"


def publish_progress(
    run_id: int, stage: str, message: str, percent: int | None = None
) -> None:
    """Publish one progress update. Never fails the job."""
    try:
        get_redis().publish(
            progress_channel(run_id),
            json.dumps({"stage": stage, "message": message, "percent": percent}),
        )
    except Exception:  # progress is best effort; indexing is not
        logger.warning("could not publish progress for run %s", run_id)


def index_repo_job(run_id: int, url: str) -> None:
    """Index a repo, recording status and stats on the index_runs row."""
    settings = get_settings()
    with connect() as conn:
        conn.autocommit = True
        ensure_schema(conn)
        conn.execute(
            "UPDATE index_runs SET status = 'running' WHERE id = %s", (run_id,)
        )
        try:
            # Structure only: clone, parse, and store files, symbols and
            # the text index. Seconds, not minutes — and enough for the
            # repo to be browsable and for every agent tool except vector
            # search to work.
            stats = index_repo(
                url,
                settings,
                embed=False,
                on_stage=lambda stage, message, percent: publish_progress(
                    run_id, stage, message, percent
                ),
            )
        except Exception as exc:
            logger.exception("index run %s failed", run_id)
            conn.execute(
                """
                UPDATE index_runs
                SET status = 'failed', error = %s, finished_at = now()
                WHERE id = %s
                """,
                (str(exc), run_id),
            )
            publish_progress(run_id, "failed", str(exc))
            raise

        repo_id = conn.execute(
            "SELECT id FROM repos WHERE owner = %s AND name = %s",
            (stats.owner, stats.name),
        ).fetchone()
        conn.execute(
            """
            UPDATE index_runs
            SET status = 'done', repo_id = %s, sha = %s, finished_at = now(),
                stats = %s
            WHERE id = %s
            """,
            (
                repo_id[0] if repo_id else None,
                stats.sha,
                json.dumps(
                    {
                        "files": stats.files,
                        "skipped_files": stats.skipped_files,
                        "chunks": stats.chunks,
                        "stage_ms": stats.stage_ms,
                    }
                ),
                run_id,
            ),
        )
        # The repo is usable now. Vectors are a second job, so nobody
        # waits on the slowest stage before asking a question.
        publish_progress(run_id, "ready", f"{stats.files} files, {stats.chunks} chunks")
        get_indexing_queue().enqueue(
            embed_repo_job,
            run_id,
            stats.owner,
            stats.name,
            stats.sha,
            job_timeout=24 * 3600,
        )


def embed_repo_job(run_id: int, owner: str, name: str, sha: str) -> None:
    """Fill in vectors after the structure pass, upgrading search.

    Failure here degrades search rather than breaking the repo: lexical
    results keep working, so this logs and gives up instead of marking
    the whole index failed.
    """
    settings = get_settings()
    try:
        filled = embed_pending(
            owner,
            name,
            sha,
            settings,
            on_stage=lambda stage, message, percent: publish_progress(
                run_id, stage, message, percent
            ),
        )
        publish_progress(run_id, "done", f"{filled} chunks embedded")
    except Exception as exc:
        logger.exception("embedding %s/%s failed", owner, name)
        publish_progress(run_id, "embed_failed", str(exc))
