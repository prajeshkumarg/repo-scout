"""Search tests: pure RRF math, plus hybrid search against real Postgres."""

import pytest

from config import get_settings
from db.conn import connect
from db.schema import ensure_schema
from tools.search import hybrid_search, lexical_query, rrf_fuse


def test_lexical_query_drops_question_words():
    # Only used when there are no embeddings to fuse with. Question words
    # match nearly every chunk, so they are dropped; identifiers survive
    # intact because the index uses the `simple` config.
    assert lexical_query("how does click handle option parsing") == (
        "click | handle | option | parsing"
    )
    assert lexical_query("SessionStore") == "sessionstore"
    assert lexical_query("find_symbol()") == "find_symbol"


def test_lexical_query_of_only_stopwords_still_searches():
    # Better to search badly than to return nothing at all.
    assert lexical_query("how does it work") != ""


def test_rrf_fuse_combines_ranks():
    fused = rrf_fuse([["a", "b", "c"], ["c", "a"]])

    order = [item for item, _ in fused]
    scores = {item: score for item, score in fused}
    # a: rank 1 + rank 2, c: rank 3 + rank 1, b: rank 2 only.
    assert order[0] == "a"
    assert abs(scores["a"] - (1 / 61 + 1 / 62)) < 1e-12
    assert abs(scores["c"] - (1 / 63 + 1 / 61)) < 1e-12
    assert abs(scores["b"] - 1 / 62) < 1e-12


# --- hybrid search against Postgres -----------------------------------------


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

DIMS = get_settings().embedding_dim


def one_hot(position: int) -> str:
    """A vector literal with 1.0 at `position`, 0 elsewhere."""
    values = ["1.0" if i == position else "0.0" for i in range(DIMS)]
    return "[" + ",".join(values) + "]"


@pytest.fixture
def indexed(conn):
    ensure_schema(conn)
    repo_id = conn.execute(
        """
        INSERT INTO repos (owner, name, default_branch, last_indexed_sha, status)
        VALUES ('owner', 'repo', 'main', 'sha1', 'ready')
        ON CONFLICT (owner, name) DO UPDATE SET last_indexed_sha = 'sha1'
        RETURNING id
        """
    ).fetchone()[0]

    def insert(sha: str, path: str, content: str, embedding_pos: int | None) -> None:
        embedding = one_hot(embedding_pos) if embedding_pos is not None else "NULL"
        conn.execute(
            f"""
            INSERT INTO chunks (repo_id, sha, path, language, symbol_kind,
                                start_line, end_line, content, embedding)
            VALUES (%s, %s, %s, 'python', 'function', 1, 2, %s, '{embedding}'::vector)
            """,
            (repo_id, sha, path, content),
        )

    # c: matches both rankers (token + vector). a: FTS only. b: vector only.
    # stale: correct content but an old SHA — must never surface.
    insert("sha1", "src/c.py", "class SessionStore:\n    pass\n", 0)
    insert("sha1", "src/a.py", "class SessionStore:\n    pass\n", 3)
    insert("sha1", "src/b.py", "class Unrelated:\n    pass\n", 1)
    insert("sha0", "src/stale.py", "class SessionStore:\n    pass\n", 0)
    yield repo_id


@pytest.fixture
def conn():
    with connect() as connection:
        connection.autocommit = True
        yield connection
        with connection.transaction():
            connection.execute("DELETE FROM chunks")
            connection.execute("DELETE FROM repos")


def test_hybrid_search_fuses_and_scopes_to_latest_sha(indexed, conn):
    query_vector = [1.0] + [0.0] * (DIMS - 1)

    hits = hybrid_search(conn, "SessionStore", query_vector, k=3)

    paths = [hit.path for hit in hits]
    # The chunk that wins on both rankers comes first; the SHA-scoped
    # exclusion keeps stale rows out entirely.
    assert paths[0] == "src/c.py"
    assert set(paths[1:]) == {"src/a.py", "src/b.py"}
    assert all(hit.sha == "sha1" for hit in hits)


def test_hybrid_search_empty_index_returns_nothing(indexed, conn):
    conn.execute("DELETE FROM chunks")
    assert hybrid_search(conn, "SessionStore", [0.0] * DIMS) == []
