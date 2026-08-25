"""The typed SSE event contract (docs/SPEC.md, "Streaming contract").

These models ARE the contract: the shapes here, the names in
web/lib/events.ts, and the spec block must stay identical. Adding an
event type means editing the spec in the same commit (rules/api.md).
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel


class StepStart(BaseModel):
    """A tool call is about to run."""

    type: Literal["step_start"] = "step_start"
    step: int
    tool: str
    args: dict


class StepResult(BaseModel):
    """A tool call finished; `summary` is the one-line trace text."""

    type: Literal["step_result"] = "step_result"
    step: int
    summary: str


class Token(BaseModel):
    """A piece of the answer text."""

    type: Literal["token"] = "token"
    text: str


class Citation(BaseModel):
    """A validated `path:start-end` the answer relies on."""

    type: Literal["citation"] = "citation"
    path: str
    start: int
    end: int


class Done(BaseModel):
    """Terminal event for a successful run, with its accounting."""

    type: Literal["done"] = "done"
    steps: int
    tokens: int
    ms: int
    cost_usd: float = 0.0


class Progress(BaseModel):
    """Indexing progress: one event per pipeline stage boundary."""

    type: Literal["progress"] = "progress"
    stage: str
    message: str
    percent: int | None = None


class ErrorEvent(BaseModel):
    """A stream that dies must emit this before closing (rules/api.md)."""

    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool


Event = StepStart | StepResult | Token | Citation | Done | Progress | ErrorEvent


def sse(event: BaseModel) -> str:
    """Serialize one event as an SSE `data:` frame."""
    return f"data: {json.dumps(event.model_dump())}\n\n"
