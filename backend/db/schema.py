"""Schema for the retrieval store.

M1 keeps this deliberately simple: one idempotent module run at ingest
startup. Real migrations (alembic) land once the schema starts changing
under a released system.
"""

from typing import Any

import psycopg

from config import get_settings

# The tsvector column uses the `simple` config (no stemming, no stopwords)
# because it exists for exact identifier search, not prose. The `english`
# config stems source-code identifiers and drops stopwords inside them,
# which is exactly wrong for names like `create_session`.
# See .claude/notes/ai-concepts.md part A §4.

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
-- Trigram index for grep. Without it, searching a large repo means
-- reading every file; with it, Postgres narrows to candidates first.
-- Same idea as Zoekt's trigram index, native to Postgres.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS repos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    default_branch TEXT,
    stars INTEGER,
    last_indexed_sha TEXT,
    status TEXT NOT NULL DEFAULT 'indexing',
    UNIQUE (owner, name)
);

CREATE TABLE IF NOT EXISTS chunks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    symbol_name TEXT,
    symbol_kind TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    parent_symbol TEXT,
    imports TEXT[] NOT NULL DEFAULT '{{}}',
    content TEXT NOT NULL,
    embedding vector({dim}),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', content || ' ' || coalesce(symbol_name, ''))
    ) STORED,
    -- Ingest rewrites its own (repo_id, sha) rows in one transaction; this
    -- is the backstop that makes a duplicate insert fail loudly instead.
    UNIQUE (repo_id, sha, path, start_line)
);

CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks
    USING hnsw (embedding vector_cosine_ops);

-- Definition sites powering find_symbol/find_references (M3).
CREATE TABLE IF NOT EXISTS symbols (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    line INTEGER NOT NULL,
    parent_symbol TEXT
);

CREATE INDEX IF NOT EXISTS symbols_name_idx
    ON symbols (repo_id, sha, name);

-- Full file contents for read_file/list_dir/grep, plus a shallow per-file
-- git log for git_log. Keyed like chunks so re-indexing rewrites them.
CREATE TABLE IF NOT EXISTS files (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    path TEXT NOT NULL,
    content TEXT NOT NULL,
    git_log TEXT NOT NULL DEFAULT '',
    UNIQUE (repo_id, sha, path)
);

-- Narrows grep to candidate files instead of scanning every one.
CREATE INDEX IF NOT EXISTS files_content_trgm
    ON files USING GIN (content gin_trgm_ops);

-- A chat thread against one repo, and its messages (M4).
CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id BIGINT NOT NULL
        REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_conversation_idx
    ON messages (conversation_id, id);

-- One indexing job: status and per-stage stats, streamed while running.
CREATE TABLE IF NOT EXISTS index_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id BIGINT REFERENCES repos(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    sha TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    stats JSONB NOT NULL DEFAULT '{{}}'
);

-- Every agent run, including failed and cancelled ones (rules/agent.md).
-- message_id joins M4's conversations; nullable until then.
CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id BIGINT,
    repo_id BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    mode TEXT NOT NULL,
    question TEXT NOT NULL,
    steps JSONB NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd NUMERIC(10, 6) NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    finished BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def ensure_schema(conn: psycopg.Connection[Any]) -> None:
    """Create tables and indexes if they do not exist. Safe to re-run."""
    # The dimension is a config value, interpolated as an integer literal so
    # no SQL injection is possible.
    conn.execute(SCHEMA_SQL.format(dim=get_settings().embedding_dim))
