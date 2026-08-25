"""Index write tests against real Postgres (skip when unreachable)."""

import pytest

from chunking.chunker import Chunk, Symbol
from config import get_settings
from db.conn import connect
from db.schema import ensure_schema
from ingest.write import write_index


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


def sample_chunks() -> list[Chunk]:
    return [
        Chunk(
            path="src/a.py",
            language="python",
            symbol_kind="function",
            symbol_name="one",
            start_line=1,
            end_line=2,
            content="def one():\n    pass\n",
        ),
        Chunk(
            path="src/b.py",
            language="python",
            symbol_kind="class",
            symbol_name="Two",
            start_line=3,
            end_line=4,
            content="class Two:\n    pass\n",
        ),
    ]


def embeddings_for(chunks: list[Chunk]) -> list[list[float]]:
    return [[0.1] * get_settings().embedding_dim for _ in chunks]


@pytest.fixture
def conn():
    with connect() as connection:
        connection.autocommit = True
        yield connection
        with connection.transaction():
            connection.execute("DELETE FROM chunks")
            connection.execute("DELETE FROM repos")


def count_chunks(connection) -> int:
    return connection.execute("SELECT count(*) FROM chunks").fetchone()[0]


def test_write_is_idempotent_per_sha(conn):
    ensure_schema(conn)
    chunks = sample_chunks()
    embeddings = embeddings_for(chunks)

    write_index(
        conn, "owner", "repo", "main", "sha1", chunks, embeddings, files=[], symbols=[]
    )
    write_index(
        conn, "owner", "repo", "main", "sha1", chunks, embeddings, files=[], symbols=[]
    )

    assert count_chunks(conn) == 2  # rewritten, not duplicated


def test_write_keeps_older_shas(conn):
    ensure_schema(conn)
    chunks = sample_chunks()
    embeddings = embeddings_for(chunks)

    write_index(
        conn, "owner", "repo", "main", "sha1", chunks, embeddings, files=[], symbols=[]
    )
    write_index(
        conn, "owner", "repo", "main", "sha2", chunks, embeddings, files=[], symbols=[]
    )

    # Citations pin SHAs; old rows must keep resolving after a reindex.
    assert count_chunks(conn) == 4
    repo_id = conn.execute(
        "SELECT id, last_indexed_sha FROM repos WHERE owner = 'owner'"
    ).fetchone()
    assert repo_id[1] == "sha2"


def test_fixture_index_does_not_move_latest_pointer(conn):
    ensure_schema(conn)
    chunks = sample_chunks()
    embeddings = embeddings_for(chunks)

    write_index(
        conn, "owner", "repo", "main", "sha1", chunks, embeddings, files=[], symbols=[]
    )
    # An eval indexing an old pinned SHA must not drag the pointer back.
    write_index(
        conn,
        "owner",
        "repo",
        "main",
        "sha0",
        chunks,
        embeddings,
        files=[],
        symbols=[],
        update_latest=False,
    )

    latest = conn.execute(
        "SELECT last_indexed_sha FROM repos WHERE owner = 'owner'"
    ).fetchone()[0]
    assert latest == "sha1"
    assert count_chunks(conn) == 4  # both SHAs' rows present


def test_files_and_symbols_are_written_idempotently(conn):
    ensure_schema(conn)
    chunks = sample_chunks()
    embeddings = embeddings_for(chunks)
    files = [("src/a.py", "def one():\n    pass\n", "abc|a|2026-01-01|first")]
    symbols = [Symbol(path="src/a.py", name="one", kind="function", line=1)]

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

    counts = conn.execute(
        "SELECT (SELECT count(*) FROM files), (SELECT count(*) FROM symbols)"
    ).fetchone()
    assert counts == (1, 1)  # rewritten, not duplicated
    row = conn.execute("SELECT git_log FROM files WHERE path = 'src/a.py'").fetchone()[
        0
    ]
    assert row == "abc|a|2026-01-01|first"


def test_record_run_writes_a_row_even_when_unfinished(conn):
    from agent.loop import StepRecord
    from agent.runs import record_run

    ensure_schema(conn)
    repo_id = conn.execute(
        "INSERT INTO repos (owner, name) VALUES ('o', 'r') RETURNING id"
    ).fetchone()[0]

    record_run(
        conn,
        repo_id=repo_id,
        sha="sha1",
        mode="deep",
        question="q",
        steps=[StepRecord(tool="grep", args={"pattern": "x"}, summary="1 match", ms=5)],
        tokens=100,
        latency_ms=2000,
        finished=False,
    )

    row = conn.execute(
        "SELECT steps, tokens, finished FROM agent_runs WHERE repo_id = %s",
        (repo_id,),
    ).fetchone()
    assert row[0][0]["tool"] == "grep"
    assert row[1] == 100
    assert row[2] is False
