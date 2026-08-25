"""Browse endpoints: what the code viewer and landing page read.

Orientation here is structural, not generated: entry points, stack, and
top-level symbols come from what indexing already produced, so opening a
repo costs zero LLM calls. A written overview would be one cached call;
it is deliberately not here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.conn import connect

logger = logging.getLogger(__name__)

router = APIRouter()

# Filenames that mark a way into a repo, most telling first.
ENTRY_POINT_HINTS = (
    "main.py",
    "__main__.py",
    "manage.py",
    "app.py",
    "cli.py",
    "index.ts",
    "index.js",
    "server.ts",
    "Dockerfile",
    "Makefile",
)
STARTER_QUESTION_COUNT = 5
ORIENTATION_FILE_COUNT = 5


class RepoSummary(BaseModel):
    """One indexed repo."""

    owner: str
    name: str
    sha: str
    status: str
    files: int
    chunks: int


class FileContent(BaseModel):
    """One file at the indexed revision."""

    path: str
    content: str
    lines: int


class SymbolEntry(BaseModel):
    """A definition site, for the outline."""

    name: str
    kind: str
    line: int
    parent: str | None = None


class Orientation(BaseModel):
    """The landing payload, derived without calling a model."""

    owner: str
    name: str
    sha: str
    languages: dict[str, int]
    entry_points: list[str]
    key_files: list[str]
    top_symbols: list[SymbolEntry]
    readme: str | None
    starter_questions: list[str]


class MessageEntry(BaseModel):
    """One stored message in a conversation."""

    role: str
    content: str
    citations: list[str]


def _repo(conn: psycopg.Connection[Any], owner: str, name: str) -> tuple[int, str]:
    row = conn.execute(
        """
        SELECT id, last_indexed_sha FROM repos
        WHERE owner = %s AND name = %s AND last_indexed_sha IS NOT NULL
        """,
        (owner, name),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{owner}/{name} is not indexed")
    return row[0], row[1]


@router.get("/repos", response_model=list[RepoSummary])
def list_repos() -> list[RepoSummary]:
    """Every indexed repo, for the picker."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.owner, r.name, r.last_indexed_sha, r.status,
                   (SELECT count(*) FROM files f
                    WHERE f.repo_id = r.id AND f.sha = r.last_indexed_sha),
                   (SELECT count(*) FROM chunks c
                    WHERE c.repo_id = r.id AND c.sha = r.last_indexed_sha)
            FROM repos r
            WHERE r.last_indexed_sha IS NOT NULL
            ORDER BY r.owner, r.name
            """
        ).fetchall()
    return [
        RepoSummary(owner=o, name=n, sha=s, status=st, files=f, chunks=c)
        for o, n, s, st, f, c in rows
    ]


@router.get("/repos/{owner}/{name}/tree", response_model=list[str])
def repo_tree(owner: str, name: str) -> list[str]:
    """Every indexed path, for the file tree."""
    with connect() as conn:
        repo_id, sha = _repo(conn, owner, name)
        rows = conn.execute(
            "SELECT path FROM files WHERE repo_id = %s AND sha = %s ORDER BY path",
            (repo_id, sha),
        ).fetchall()
    return [row[0] for row in rows]


@router.get("/repos/{owner}/{name}/file", response_model=FileContent)
def repo_file(owner: str, name: str, path: str = Query(...)) -> FileContent:
    """One file's content at the indexed revision."""
    with connect() as conn:
        repo_id, sha = _repo(conn, owner, name)
        row = conn.execute(
            "SELECT content FROM files WHERE repo_id = %s AND sha = %s AND path = %s",
            (repo_id, sha, path),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no file {path!r} at {sha[:8]}")
    return FileContent(path=path, content=row[0], lines=len(row[0].splitlines()))


@router.get("/repos/{owner}/{name}/symbols", response_model=list[SymbolEntry])
def repo_symbols(
    owner: str, name: str, path: str | None = Query(default=None)
) -> list[SymbolEntry]:
    """Definition sites, optionally scoped to one file (the outline)."""
    with connect() as conn:
        repo_id, sha = _repo(conn, owner, name)
        if path:
            rows = conn.execute(
                """
                SELECT name, kind, line, parent_symbol FROM symbols
                WHERE repo_id = %s AND sha = %s AND path = %s ORDER BY line
                """,
                (repo_id, sha, path),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT name, kind, line, parent_symbol FROM symbols
                WHERE repo_id = %s AND sha = %s AND parent_symbol IS NULL
                ORDER BY name LIMIT 200
                """,
                (repo_id, sha),
            ).fetchall()
    return [SymbolEntry(name=n, kind=k, line=line, parent=p) for n, k, line, p in rows]


@router.get("/repos/{owner}/{name}/orientation", response_model=Orientation)
def repo_orientation(owner: str, name: str) -> Orientation:
    """Structural orientation: no model call, only what indexing produced."""
    with connect() as conn:
        repo_id, sha = _repo(conn, owner, name)
        paths = [
            row[0]
            for row in conn.execute(
                "SELECT path FROM files WHERE repo_id = %s AND sha = %s ORDER BY path",
                (repo_id, sha),
            ).fetchall()
        ]
        languages = dict(
            conn.execute(
                """
                SELECT language, count(DISTINCT path) FROM chunks
                WHERE repo_id = %s AND sha = %s GROUP BY language
                """,
                (repo_id, sha),
            ).fetchall()
        )
        # "Key files" = the files holding the most definitions: a decent
        # structural proxy for where a newcomer should start reading.
        key_files = [
            row[0]
            for row in conn.execute(
                """
                SELECT path, count(*) AS defs FROM symbols
                WHERE repo_id = %s AND sha = %s
                  AND path NOT LIKE 'test%%' AND path NOT LIKE '%%/test%%'
                  AND path NOT LIKE 'example%%'
                GROUP BY path ORDER BY defs DESC LIMIT %s
                """,
                (repo_id, sha, ORIENTATION_FILE_COUNT),
            ).fetchall()
        ]
        # Public classes from the densest source files, in the order they
        # are defined. Alphabetical would lead with "Abort", and private
        # helpers like _AtomicFile are not what a newcomer needs first.
        top_symbols = [
            SymbolEntry(name=n, kind=k, line=line, parent=None)
            for n, k, line in conn.execute(
                """
                SELECT s.name, s.kind, s.line
                FROM symbols s
                JOIN (
                    SELECT path, count(*) AS defs,
                           row_number() OVER (ORDER BY count(*) DESC) AS rank
                    FROM symbols
                    WHERE repo_id = %s AND sha = %s
                      AND path NOT LIKE 'test%%' AND path NOT LIKE '%%/test%%'
                      AND path NOT LIKE 'example%%'
                    GROUP BY path ORDER BY defs DESC LIMIT 5
                ) dense ON dense.path = s.path
                WHERE s.repo_id = %s AND s.sha = %s AND s.kind = 'class'
                  AND s.parent_symbol IS NULL AND left(s.name, 1) <> '_'
                ORDER BY dense.rank, s.line
                LIMIT 10
                """,
                (repo_id, sha, repo_id, sha),
            ).fetchall()
        ]
        readme_row = conn.execute(
            """
            SELECT content FROM files
            WHERE repo_id = %s AND sha = %s AND lower(path) LIKE 'readme%%'
            LIMIT 1
            """,
            (repo_id, sha),
        ).fetchone()

    # Rank entry points by how likely they are to be the real way in:
    # a tests/ or examples/ file named main.py is a decoy.
    def entry_rank(path: str) -> tuple[int, int]:
        noise = any(
            part in {"tests", "test", "examples", "docs", "scripts"}
            for part in path.split("/")
        )
        return (1 if noise else 0, path.count("/"))

    entry_points = sorted(
        (p for p in paths if p.split("/")[-1] in ENTRY_POINT_HINTS), key=entry_rank
    )
    return Orientation(
        owner=owner,
        name=name,
        sha=sha,
        languages=languages,
        entry_points=entry_points[:ORIENTATION_FILE_COUNT],
        key_files=key_files,
        top_symbols=top_symbols,
        readme=readme_row[0] if readme_row else None,
        starter_questions=_starter_questions(top_symbols, entry_points, key_files),
    )


def _starter_questions(
    symbols: list[SymbolEntry], entry_points: list[str], key_files: list[str]
) -> list[str]:
    """Questions built from real symbols, so they are never generic."""
    questions = [f"What does the {s.name} class do?" for s in symbols[:3]]
    if entry_points:
        questions.append(f"What happens when {entry_points[0]} runs?")
    if key_files:
        questions.append(f"Walk me through {key_files[0]}")
    questions.append("How do I run this project locally?")
    return questions[:STARTER_QUESTION_COUNT]


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageEntry],
)
def conversation_messages(conversation_id: int) -> list[MessageEntry]:
    """Stored messages, so a reload does not lose the thread."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT role, content, citations FROM messages
            WHERE conversation_id = %s ORDER BY id
            """,
            (conversation_id,),
        ).fetchall()
    return [
        MessageEntry(
            role=r,
            content=c,
            citations=json.loads(cit) if isinstance(cit, str) else (cit or []),
        )
        for r, c, cit in rows
    ]
