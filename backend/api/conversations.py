"""Conversation endpoints: ask a question, stream the agent's work.

The agent loop is synchronous and blocking, so it runs in a worker
thread while the request handler drains its events onto the SSE stream.
That keeps the handler free to notice a client disconnect and set the
cancel token, which the loop checks between steps.

Note on `token` events: citations are post-validated (invalid ones are
stripped and the model gets one retry), so the text that goes on the
wire is the validated answer, not the raw generation. Streaming raw
tokens would mean streaming citations we are about to delete.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from collections.abc import AsyncIterator

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.ask import ask_deep
from agent.citations import CITATION_PATTERN, Validation
from agent.llm import GeminiClient
from agent.loop import AgentRun, StepRecord
from agent.runs import record_run
from api.events import (
    HEARTBEAT_SECONDS,
    Citation,
    Done,
    ErrorEvent,
    StepResult,
    StepStart,
    Token,
    heartbeat,
    sse,
)
from config import get_settings
from db.conn import connect
from db.schema import ensure_schema
from embedding import LocalEmbedder
from tools.base import ToolContext

logger = logging.getLogger(__name__)

router = APIRouter()

# How long the drain loop waits on the queue before re-checking state.
DRAIN_TIMEOUT = 0.1


class ConversationRequest(BaseModel):
    """Start a conversation against one indexed repo."""

    repo: str  # "owner/name"


class ConversationResponse(BaseModel):
    """The created conversation."""

    conversation_id: int
    repo: str
    sha: str


class MessageRequest(BaseModel):
    """Ask a question in a conversation."""

    question: str


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(request: ConversationRequest) -> ConversationResponse:
    """Open a conversation against an indexed repo."""
    if "/" not in request.repo:
        raise HTTPException(status_code=400, detail="repo must be 'owner/name'")
    owner, name = request.repo.split("/", 1)

    with connect() as conn:
        conn.autocommit = True
        ensure_schema(conn)
        row = conn.execute(
            """
            SELECT id, last_indexed_sha FROM repos
            WHERE owner = %s AND name = %s AND last_indexed_sha IS NOT NULL
            """,
            (owner, name),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"{request.repo} is not indexed"
            )
        repo_id, sha = row
        conversation_id = conn.execute(
            "INSERT INTO conversations (repo_id) VALUES (%s) RETURNING id",
            (repo_id,),
        ).fetchone()[0]

    return ConversationResponse(
        conversation_id=conversation_id, repo=request.repo, sha=sha
    )


@router.post("/conversations/{conversation_id}/messages")
async def ask(
    conversation_id: int, body: MessageRequest, request: Request
) -> StreamingResponse:
    """Answer a question, streaming the agent's steps and answer."""
    settings = get_settings()
    if not settings.google_api_key:
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY is not configured")

    with connect() as conn:
        row = conn.execute(
            """
            SELECT c.repo_id, r.last_indexed_sha
            FROM conversations c JOIN repos r ON r.id = c.repo_id
            WHERE c.id = %s
            """,
            (conversation_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no conversation {conversation_id}"
        )
    repo_id, sha = row

    return StreamingResponse(
        _agent_events(conversation_id, repo_id, sha, body.question, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _agent_events(
    conversation_id: int,
    repo_id: int,
    sha: str,
    question: str,
    request: Request,
) -> AsyncIterator[str]:
    """Run the agent in a thread and stream its events as they happen."""
    settings = get_settings()
    events: queue.Queue = queue.Queue()
    cancel = threading.Event()
    outcome: dict = {}

    def on_step(step: StepRecord) -> None:
        events.put(("step", step))

    def work() -> None:
        # The loop blocks, so it gets its own connection and thread.
        try:
            with connect() as conn:
                embedder = LocalEmbedder(
                    model_name=settings.embedding_model,
                    batch_size=settings.embed_batch_size,
                )
                ctx = ToolContext(
                    conn=conn, repo_id=repo_id, sha=sha, embedder=embedder
                )
                client = GeminiClient(
                    settings.google_api_key, settings.google_agent_model
                )
                run, validation = ask_deep(
                    question, ctx, client, on_step=on_step, cancel=cancel
                )
                outcome["run"] = run
                outcome["validation"] = validation
                _persist(conn, conversation_id, repo_id, sha, question, run, validation)
        except Exception as exc:  # surfaced as an error event, not a 500
            logger.exception("agent run failed")
            outcome["error"] = exc
        finally:
            events.put(("end", None))

    thread = threading.Thread(target=work, daemon=True)
    thread.start()

    step_number = 0
    last_sent = time.monotonic()
    try:
        while True:
            if await request.is_disconnected():
                cancel.set()  # propagates into the loop between steps
                logger.info("client disconnected; cancelling run")
                return
            try:
                kind, payload = events.get(timeout=DRAIN_TIMEOUT)
            except queue.Empty:
                # A tool call waiting out a rate limit can leave the
                # stream silent for minutes; proxies cut that as dead.
                if time.monotonic() - last_sent > HEARTBEAT_SECONDS:
                    last_sent = time.monotonic()
                    yield heartbeat()
                await asyncio.sleep(0)
                continue
            last_sent = time.monotonic()
            if kind == "step":
                step_number += 1
                yield sse(
                    StepStart(step=step_number, tool=payload.tool, args=payload.args)
                )
                yield sse(StepResult(step=step_number, summary=payload.summary))
            elif kind == "end":
                break

        if "error" in outcome:
            yield sse(
                ErrorEvent(
                    code="agent_failed",
                    message=str(outcome["error"]),
                    retryable=True,
                )
            )
            return

        run, validation = outcome["run"], outcome["validation"]
        yield sse(Token(text=validation.answer))
        for match in CITATION_PATTERN.finditer(validation.answer):
            start = int(match.group(2))
            yield sse(
                Citation(
                    path=match.group(1),
                    start=start,
                    # A single-line citation is a range of one line.
                    end=int(match.group(3)) if match.group(3) else start,
                )
            )
        yield sse(Done(steps=len(run.steps), tokens=run.tokens, ms=run.latency_ms))
    except Exception as exc:  # a dying stream must say so before closing
        logger.exception("agent event stream failed")
        yield sse(ErrorEvent(code="stream_failed", message=str(exc), retryable=True))


def _persist(
    conn: psycopg.Connection,
    conversation_id: int,
    repo_id: int,
    sha: str,
    question: str,
    run: AgentRun,
    validation: Validation,
) -> None:
    """Store the exchange: both messages plus the agent_runs row."""
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content)
            VALUES (%s, 'user', %s)
            """,
            (conversation_id, question),
        )
        message_id = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, citations)
            VALUES (%s, 'assistant', %s, %s) RETURNING id
            """,
            (conversation_id, validation.answer, json.dumps(validation.valid)),
        ).fetchone()[0]
    record_run(
        conn,
        repo_id=repo_id,
        sha=sha,
        mode="deep",
        question=question,
        steps=run.steps,
        tokens=run.tokens,
        latency_ms=run.latency_ms,
        finished=run.finished,
        message_id=message_id,
    )
