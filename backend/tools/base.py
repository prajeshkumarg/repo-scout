"""Tool context and result shapes shared by the agent tools.

Agent rules: tools return structured data plus a one-line human-readable
summary; the summary is what a UI trace shows, the content is what goes
back to the model. Every cap truncates with an explicit marker so the
model knows there was more.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from embedding import Embedder

# Output caps, per .claude/rules/agent.md.
READ_FILE_MAX_LINES = 400
GREP_MAX_MATCHES = 50
SEARCH_MAX_CHUNKS = 10
FIND_MAX_RESULTS = 20


@dataclass
class ToolContext:
    """Everything a tool needs, scoped to one indexed (repo, sha)."""

    conn: psycopg.Connection
    repo_id: int
    sha: str
    embedder: Embedder


@dataclass
class ToolResult:
    """One tool execution: a trace summary plus model-facing content."""

    summary: str
    content: str
    # Paths the agent has now read (or at least learned about); the eval
    # measures deep-mode recall over the union of these.
    files_read: list[str] = field(default_factory=list)


def error_result(message: str) -> ToolResult:
    """A tool failure, returned to the model as an error, not an exception."""
    return ToolResult(summary=f"error: {message}", content=f"error: {message}")
