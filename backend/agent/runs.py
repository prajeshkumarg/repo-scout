"""agent_runs persistence: every run writes a row, even failures."""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg

from agent.loop import StepRecord

logger = logging.getLogger(__name__)


def record_run(
    conn: psycopg.Connection[Any],
    *,
    repo_id: int,
    sha: str,
    mode: str,
    question: str,
    steps: list[StepRecord],
    tokens: int,
    latency_ms: int,
    finished: bool,
    message_id: int | None = None,
) -> None:
    """Write one agent_runs row.

    cost_usd stays 0 while the agent runs on a free tier; a real
    estimate arrives with paid models.
    """
    conn.execute(
        """
        INSERT INTO agent_runs
            (repo_id, sha, mode, question, steps, tokens, cost_usd,
             latency_ms, finished, message_id)
        VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
        """,
        (
            repo_id,
            sha,
            mode,
            question,
            json.dumps([_step_json(step) for step in steps]),
            tokens,
            latency_ms,
            finished,
            message_id,
        ),
    )


def _step_json(step: StepRecord) -> dict:
    return {
        "tool": step.tool,
        "args": step.args,
        "summary": step.summary,
        "ms": step.ms,
    }
