"""Schema tests against a real Postgres.

These need the docker compose database (`make deps`). When Postgres is not
reachable they skip rather than fail, so `make test` still works on a clean
clone with no services running.
"""

import psycopg
import pytest

from db.conn import connect
from db.schema import ensure_schema


def _postgres_available() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
    except Exception:  # probing; any failure means "not available"
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="local Postgres not reachable"
)


@pytest.fixture
def clean_chunks():
    with connect() as conn:
        # Autocommit keeps DDL from opening implicit transactions, so tests
        # can manage BEGIN/ROLLBACK themselves.
        conn.autocommit = True
        yield conn
        with conn.transaction():
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM repos")


def test_ensure_schema_is_idempotent(clean_chunks):
    ensure_schema(clean_chunks)
    ensure_schema(clean_chunks)


def test_duplicate_chunk_row_is_rejected(clean_chunks):
    ensure_schema(clean_chunks)
    # Explicit BEGIN/ROLLBACK instead of psycopg's transaction() context,
    # which commits on clean exit and would fail after the expected abort.
    repo_id = clean_chunks.execute(
        "INSERT INTO repos (owner, name) VALUES ('a', 'b') RETURNING id"
    ).fetchone()[0]
    args = (
        repo_id,
        "deadbeef",
        "src/x.py",
        "python",
        "function",
        10,
        20,
        "def x(): pass",
    )
    clean_chunks.execute("BEGIN")
    try:
        clean_chunks.execute(
            """
            INSERT INTO chunks
                (repo_id, sha, path, language, symbol_kind,
                 start_line, end_line, content)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            args,
        )
        with pytest.raises(
            psycopg.errors.UniqueViolation,
            match="chunks_repo_id_sha_path_start_line",
        ):
            clean_chunks.execute(
                """
                INSERT INTO chunks
                    (repo_id, sha, path, language, symbol_kind,
                     start_line, end_line, content)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                args,
            )
    finally:
        clean_chunks.execute("ROLLBACK")


def test_tsv_matches_exact_identifiers(clean_chunks):
    """The FTS column must find `SessionStore` exactly, not a stem of it."""
    ensure_schema(clean_chunks)
    repo_id = clean_chunks.execute(
        "INSERT INTO repos (owner, name) VALUES ('c', 'd') RETURNING id"
    ).fetchone()[0]
    clean_chunks.execute(
        """
        INSERT INTO chunks
            (repo_id, sha, path, language, symbol_kind,
             start_line, end_line, content, symbol_name)
        VALUES (%s, 'sha1', 'src/session.py', 'python', 'class',
                1, 5, 'class SessionStore:', 'SessionStore')
        """,
        (repo_id,),
    )
    # camelCase identifiers stay whole under the `simple` config.
    hit = clean_chunks.execute(
        """
        SELECT count(*) FROM chunks
        WHERE tsv @@ plainto_tsquery('simple', 'SessionStore')
        """
    ).fetchone()[0]
    assert hit == 1
