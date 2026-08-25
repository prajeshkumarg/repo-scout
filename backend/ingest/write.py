"""Writing a finished index to Postgres."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from chunking.chunker import Chunk, Symbol
from db.schema import ensure_schema

logger = logging.getLogger(__name__)

_INSERT_CHUNK = """
INSERT INTO chunks
    (repo_id, sha, path, language, symbol_kind, start_line, end_line,
     symbol_name, parent_symbol, imports, content, embedding)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_FILE = """
INSERT INTO files (repo_id, sha, path, content, git_log)
VALUES (%s, %s, %s, %s, %s)
"""

_INSERT_SYMBOL = """
INSERT INTO symbols (repo_id, sha, name, kind, path, line, parent_symbol)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def write_index(
    conn: psycopg.Connection[Any],
    owner: str,
    name: str,
    default_branch: str,
    sha: str,
    chunks: list[Chunk],
    embeddings: list[list[float]] | None,
    *,
    files: list[tuple[str, str, str]],
    symbols: list[Symbol],
    update_latest: bool = True,
) -> None:
    """Rewrite the (repo, sha) index atomically.

    Re-running ingest on the same SHA replaces its rows in one transaction,
    so the index for a SHA is always complete or absent, never mixed.
    Rows for older SHAs are kept: conversations cite pinned commits, and
    those citations must keep resolving after a reindex.

    With `update_latest=False` the repos row keeps its current
    last_indexed_sha: fixture indexes (evals) write old SHAs and must not
    make the search CLI serve stale code.

    `embeddings` may be None: chunks are then stored with null vectors and
    filled in by a later pass. Everything except vector search works in
    the meantime, which is what lets a repo be usable in seconds rather
    than minutes.
    """
    ensure_schema(conn)
    register_vector(conn)
    with conn.transaction():
        repo_id = conn.execute(
            """
            INSERT INTO repos (owner, name, default_branch, last_indexed_sha, status)
            VALUES (%s, %s, %s, %s, 'indexing')
            ON CONFLICT (owner, name)
            DO UPDATE SET
                default_branch = EXCLUDED.default_branch,
                last_indexed_sha = CASE WHEN %s THEN EXCLUDED.last_indexed_sha
                                        ELSE repos.last_indexed_sha END,
                status = CASE WHEN %s THEN EXCLUDED.status
                              ELSE repos.status END
            RETURNING id
            """,
            (owner, name, default_branch, sha, update_latest, update_latest),
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM chunks WHERE repo_id = %s AND sha = %s", (repo_id, sha)
        )
        conn.execute(
            "DELETE FROM files WHERE repo_id = %s AND sha = %s", (repo_id, sha)
        )
        conn.execute(
            "DELETE FROM symbols WHERE repo_id = %s AND sha = %s", (repo_id, sha)
        )
        with conn.cursor() as cursor:
            cursor.executemany(_INSERT_CHUNK, _rows(repo_id, sha, chunks, embeddings))
            cursor.executemany(
                _INSERT_FILE,
                [
                    (repo_id, sha, path, content, git_log)
                    for path, content, git_log in files
                ],
            )
            cursor.executemany(
                _INSERT_SYMBOL,
                [
                    (repo_id, sha, s.name, s.kind, s.path, s.line, s.parent)
                    for s in symbols
                ],
            )
        conn.execute("UPDATE repos SET status = 'ready' WHERE id = %s", (repo_id,))


def _rows(
    repo_id: int,
    sha: str,
    chunks: list[Chunk],
    embeddings: list[list[float]] | None,
) -> list[tuple[Any, ...]]:
    vectors: list[Vector | None] = (
        [Vector(embedding) for embedding in embeddings]
        if embeddings is not None
        else [None] * len(chunks)
    )
    return [
        (
            repo_id,
            sha,
            chunk.path,
            chunk.language,
            chunk.symbol_kind,
            chunk.start_line,
            chunk.end_line,
            chunk.symbol_name,
            chunk.parent_symbol,
            chunk.imports,
            chunk.content,
            vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
