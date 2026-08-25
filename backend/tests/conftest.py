"""Test isolation: tests run against their own database, never dev.

The schema/write/search tests mutate rows; pointing them at the dev
database would let `make test` wipe real indexes. This conftest forces a
dedicated test database (created on demand) via the environment, before
any Settings object is built.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_DATABASE_URL = "postgresql://scout:scout@localhost:5432/repo_scout_test"
ADMIN_DATABASE_URL = "postgresql://scout:scout@localhost:5432/postgres"

# Set before backend modules are imported so pydantic-settings picks it up.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
sys.path.insert(0, str(Path(__file__).parent.parent))


def _ensure_test_database() -> None:
    """Create the test database if it does not exist.

    Swallows connection failures: when Postgres is not running, tests
    that need it skip via their own probes instead of failing here.
    """
    import psycopg

    try:
        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = 'repo_scout_test'"
            ).fetchone()
            if exists is None:
                conn.execute("CREATE DATABASE repo_scout_test")
    except Exception:  # no Postgres available; skip-if probes will handle it
        pass


_ensure_test_database()


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("SELECT 1")
    except Exception:  # probing; any failure means "not available"
        return False
    return True


import pytest  # noqa: E402


@pytest.fixture
def tool_ctx():
    """A small indexed repo in the test database, as a ToolContext.

    Used by the tool tests and the agent loop tests. Skips when Postgres
    is not reachable.
    """
    if not _postgres_available():
        pytest.skip("local Postgres not reachable")

    from chunking.chunker import Chunk, Symbol
    from config import get_settings
    from db.conn import connect
    from db.schema import ensure_schema
    from ingest.write import write_index
    from tools.base import ToolContext

    class FakeEmbedder:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            dims = get_settings().embedding_dim
            return [[0.5] * dims for _ in texts]

        def embed_query(self, text: str) -> list[float]:
            return [0.5] * get_settings().embedding_dim

    with connect() as conn:
        conn.autocommit = True
        ensure_schema(conn)
        files = [
            (
                "src/app.py",
                "SESSION_STORE = {}\n"
                + "\n".join(f"line_{i} = {i}" for i in range(3))
                + "\n",
                "abc|dev|2026-01-01|init\n",
            ),
            (
                "src/nested/util.py",
                "def helper():\n    return 1\n",
                "def|dev|2026-01-02|second",
            ),
        ]
        symbols = [
            Symbol(path="src/app.py", name="find_me", kind="function", line=4),
            Symbol(path="src/nested/util.py", name="helper", kind="function", line=1),
        ]
        chunks = [
            Chunk(
                path="src/app.py",
                language="python",
                symbol_kind="function",
                symbol_name="find_me",
                start_line=4,
                end_line=5,
                content="def find_me():\n    return 4\n",
            ),
            Chunk(
                path="src/nested/util.py",
                language="python",
                symbol_kind="module",
                start_line=1,
                end_line=2,
                content="def helper():\n    return 1\n",
            ),
        ]
        embeddings = [[0.1] * get_settings().embedding_dim for _ in chunks]
        write_index(
            conn,
            "owner",
            "repo",
            "main",
            "sha1",
            chunks,
            embeddings,
            files=files,
            symbols=symbols,
        )
        repo_id = conn.execute("SELECT id FROM repos WHERE owner = 'owner'").fetchone()[
            0
        ]
        yield ToolContext(
            conn=conn, repo_id=repo_id, sha="sha1", embedder=FakeEmbedder()
        )
        with conn.transaction():
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM files")
            conn.execute("DELETE FROM symbols")
            conn.execute("DELETE FROM repos")
