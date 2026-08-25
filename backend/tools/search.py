"""Hybrid retrieval: vector + FTS fused by reciprocal rank fusion.

The two rankers fail in opposite directions — vectors miss exact names,
lexical search misses paraphrases — and their scores are not comparable
numbers, so RRF throws the scores away and keeps only the ranks:
RRF(d) = sum over rankers of 1 / (k + rank(d)), with k = 60 (see
.ai-concepts part A §6, the spec's default).

Searches are scoped to the latest indexed SHA per repo: old SHAs stay in
the table so pinned citations keep resolving, but search must not surface
stale code.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, TypeVar

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from tools.base import SEARCH_MAX_CHUNKS, ToolContext, ToolResult

logger = logging.getLogger(__name__)

RRF_K = 60
CANDIDATE_K = 50  # candidates fetched per ranker before fusing

T = TypeVar("T")


@dataclass
class Hit:
    """One retrieval result."""

    repo_id: int
    owner: str
    name: str
    sha: str
    path: str
    start_line: int
    end_line: int
    symbol_name: str | None
    content: str
    score: float  # fused RRF score, higher is better


def rrf_fuse[T](
    ranked_lists: list[list[T]], *, k: int = RRF_K
) -> list[tuple[T, float]]:
    """Merge ranked lists of the same items by reciprocal rank.

    Items are compared by identity, so callers pass a common key type
    (chunk ids here). Output is sorted by fused score, descending.
    """
    scores: dict[T, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            scores[item] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


_HIT_COLUMNS = """
    c.id, r.owner, r.name, c.sha, c.path, c.start_line, c.end_line,
    c.symbol_name, c.content
"""

# Only chunks of the latest indexed SHA per repo.
_LATEST_SCOPE = "r.last_indexed_sha = c.sha"


def hybrid_search(
    conn: psycopg.Connection[Any],
    query: str,
    query_vector: list[float],
    *,
    k: int = 10,
    candidate_k: int = CANDIDATE_K,
    repo_id: int | None = None,
    sha: str | None = None,
) -> list[Hit]:
    """Run both rankers, fuse, and return the top `k` hits.

    With `repo_id` set (agent tools), scopes to one repo at one SHA; the
    CLI and evals search all latest indexes.
    """
    register_vector(conn)
    scope, scope_params = _scope(repo_id, sha)
    vector_ids = [
        row[0]
        for row in _vector_search(conn, query_vector, candidate_k, scope, scope_params)
    ]
    # With no vector half to fuse with, lexical search has to answer on
    # its own, so it broadens rather than returning nothing.
    fts_ids = [
        row[0]
        for row in _fts_search(
            conn,
            query,
            candidate_k,
            scope,
            scope_params,
            broaden=not vector_ids,
        )
    ]
    fused = rrf_fuse([vector_ids, fts_ids])
    top_ids = [chunk_id for chunk_id, _ in fused[:k]]

    if not top_ids:
        return []
    by_id = {row[0]: row for row in _fetch_hits(conn, top_ids)}
    by_score = {chunk_id: score for chunk_id, score in fused}
    return [
        Hit(
            repo_id=row[0],
            owner=row[1],
            name=row[2],
            sha=row[3],
            path=row[4],
            start_line=row[5],
            end_line=row[6],
            symbol_name=row[7],
            content=row[8],
            score=by_score[chunk_id],
        )
        for chunk_id in top_ids
        if (row := by_id.get(chunk_id)) is not None
    ]


# Question words carry no signal about code. The index deliberately uses
# the `simple` config so identifiers survive intact, which means nothing
# strips these for us — so they are dropped from the query instead. Left
# in, they match nearly every chunk and the lexical ranking becomes
# noise that crowds out the vector half during fusion.
STOPWORDS = frozenset(
    """a an the and or but if then than that this these those of in on at to
    for from by with without into over under is are was were be been being do
    does did doing have has had having how what when where which who whom why
    can could should would will shall may might must it its as i you we they
    them their there here about across after against all also any because
    before between both during each few more most other our out same some
    such through up down very work works working use used using get gets
    getting make makes made does like""".split()
)


def lexical_query(query: str) -> str:
    """Build a broad OR tsquery, for when lexical search is on its own.

    This exists for repos whose embeddings have not landed yet. It is
    deliberately not used alongside vector search: OR'ing question terms
    there measured *worse* (0.92 to 0.85) because words like "how" match
    nearly every chunk, and that noise crowds out good vector hits during
    fusion. With no vector half to dilute, noisy results still beat none.

    Tokens are reduced to word characters so the result is always valid
    tsquery syntax.
    """
    terms = [
        token
        for token in re.split(r"\W+", query.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]
    # A query of nothing but stopwords should fall back to the whole
    # thing rather than returning no lexical results at all.
    if not terms:
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 1]
    return " | ".join(terms)


def _scope(repo_id: int | None, sha: str | None) -> tuple[str, tuple]:
    """Where clause and params for the caller's scope."""
    if repo_id is None:
        return _LATEST_SCOPE, ()
    return "c.repo_id = %s AND c.sha = %s", (repo_id, sha)


def _vector_search(
    conn: psycopg.Connection[Any],
    query_vector: list[float],
    limit: int,
    scope: str,
    scope_params: tuple,
) -> list[tuple[int, ...]]:
    rows = conn.execute(
        f"""
        SELECT {_HIT_COLUMNS}
        FROM chunks c JOIN repos r ON r.id = c.repo_id
        WHERE {scope} AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %s
        LIMIT %s
        """,
        (*scope_params, Vector(query_vector), limit),
    ).fetchall()
    return rows


def _fts_search(
    conn: psycopg.Connection[Any],
    query: str,
    limit: int,
    scope: str,
    scope_params: tuple,
    broaden: bool = False,
) -> list[tuple[int, ...]]:
    # Alongside vectors, keep websearch_to_tsquery's AND semantics: it
    # makes this a precise identifier boost, and the eval says that beats
    # a broader lexical opinion. Alone, broaden or return nothing.
    if broaden:
        tsquery = lexical_query(query)
        if not tsquery:
            return []
        builder = "to_tsquery('simple', %s)"
    else:
        tsquery = query
        builder = "websearch_to_tsquery('simple', %s)"
    rows = conn.execute(
        f"""
        SELECT {_HIT_COLUMNS},
               ts_rank(c.tsv, {builder}) AS rank
        FROM chunks c JOIN repos r ON r.id = c.repo_id
        WHERE {scope} AND c.tsv @@ {builder}
        ORDER BY rank DESC
        LIMIT %s
        """,
        # The SELECT clause's ts_rank placeholder precedes the WHERE
        # clause's scope placeholders in the SQL text.
        (tsquery, *scope_params, tsquery, limit),
    ).fetchall()
    return rows


def _fetch_hits(
    conn: psycopg.Connection[Any], chunk_ids: list[int]
) -> list[tuple[int, ...]]:
    rows = conn.execute(
        f"""
        SELECT {_HIT_COLUMNS}
        FROM chunks c JOIN repos r ON r.id = c.repo_id
        WHERE c.id = ANY(%s)
        """,
        (chunk_ids,),
    ).fetchall()
    return rows


def search_code(ctx: ToolContext, query: str, k: int = SEARCH_MAX_CHUNKS) -> ToolResult:
    """Hybrid retrieval, capped per the agent rules."""
    query_vector = ctx.embedder.embed_query(query)
    hits = hybrid_search(
        ctx.conn,
        query,
        query_vector,
        k=min(k, SEARCH_MAX_CHUNKS),
        repo_id=ctx.repo_id,
        sha=ctx.sha,
    )
    if not hits:
        return ToolResult(
            summary=f"search_code {query!r}: no results", content="no results"
        )
    lines = [
        f"{hit.path}:{hit.start_line}-{hit.end_line} ({hit.symbol_name or 'module'})\n"
        f"{hit.content}"
        for hit in hits
    ]
    return ToolResult(
        summary=f"search_code: {len(hits)} chunk(s) for {query!r}",
        content="\n\n".join(lines),
        files_read=[hit.path for hit in hits],
    )
