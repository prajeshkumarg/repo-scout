"""Pydantic models for the API boundary. No raw dicts cross it."""

from typing import Literal

from pydantic import BaseModel, Field


class DependencyStatus(BaseModel):
    """Reachability of one backing service."""

    ok: bool
    detail: str | None = Field(
        default=None, description="Error detail when ok is false."
    )


class HealthResponse(BaseModel):
    """Liveness plus the state of everything the API needs to do its job."""

    status: Literal["ok", "degraded"]
    version: str
    dependencies: dict[str, DependencyStatus]


class ErrorResponse(BaseModel):
    """Structured error body: what went wrong and whether to try again."""

    code: str
    message: str
    retryable: bool
