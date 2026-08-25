"""The ingest pipeline: clone -> filter -> chunk -> embed -> write.

M1 logs a line at every stage boundary. The Redis progress events the UI
streams land in M4 when this runs inside the worker.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pgvector import Vector
from pgvector.psycopg import register_vector

from chunking.chunker import Chunk, Symbol, chunk_file, symbols_for
from config import Settings
from db.conn import connect
from embedding import LocalEmbedder, embedding_text
from ingest.clone import clone_repo, git_log_for
from ingest.filters import iter_doc_files, iter_source_files, within_budget
from ingest.write import write_index

logger = logging.getLogger(__name__)


@dataclass
class IndexStats:
    """What one ingest run did, for the CLI's final line."""

    owner: str = ""
    name: str = ""
    sha: str = ""
    files: int = 0
    skipped_files: int = 0
    chunks: int = 0
    stage_ms: dict[str, float] = field(default_factory=dict)


def run(
    url: str,
    settings: Settings,
    sha: str | None = None,
    *,
    update_latest: bool = True,
    embed: bool = True,
    on_stage: Callable[[str, str, int | None], None] | None = None,
) -> IndexStats:
    """Index one public GitHub repo end to end.

    With `sha` set, indexes exactly that commit; evals pin their fixture
    repos so measurements cannot drift, and pass update_latest=False so
    evaluating an old fixture does not move the search pointer back.

    `on_stage(stage, message, percent)` fires at every stage boundary and,
    during embedding, after each batch; the worker turns those into the
    progress events the UI streams.

    With `embed=False` the chunks are stored without vectors and the run
    finishes in seconds. Everything except vector search works straight
    away; `embed_pending` fills the vectors in afterwards.
    """

    def announce(stage: str, message: str, percent: int | None = None) -> None:
        logger.info("[%s] %s", stage, message)
        if on_stage is not None:
            on_stage(stage, message, percent)

    stats = IndexStats()
    with tempfile.TemporaryDirectory(prefix="repo-scout-") as tmp:
        repo_root = Path(tmp) / "repo"

        start = time.monotonic()
        repo = clone_repo(url, repo_root, sha=sha)
        stats.owner, stats.name, stats.sha = repo.owner, repo.name, repo.sha
        announce(
            "clone",
            f"{repo.owner}/{repo.name} @ {repo.sha[:8]} "
            f"in {_stage(stats, 'clone', start):.1f}s",
        )

        start = time.monotonic()
        paths = iter_source_files(repo_root)
        # A repo larger than the budget is indexed in part rather than
        # refused: source before tests, shallow before deep. Saying so
        # matters — a partial index that claims to be whole is worse
        # than one that admits what it left out.
        paths, skipped = within_budget(repo_root, paths)
        stats.files = len(paths)
        stats.skipped_files = skipped
        elapsed = _stage(stats, "filter", start)
        message = f"{len(paths)} source files kept in {elapsed:.1f}s"
        if skipped:
            message += f" ({skipped} skipped: repo is over the size budget)"
        announce("filter", message)

        start = time.monotonic()
        chunks = []
        symbols: list[Symbol] = []
        files: list[tuple[str, str, str]] = []
        # Parsing a large repo takes minutes, so report progress as files
        # are read rather than going silent until the stage ends. Around
        # twenty updates either way: a per-file event on a small repo is
        # just noise on the stream.
        step = max(1, len(paths) // 20)
        for position, path in enumerate(paths, start=1):
            source = (repo_root / path).read_text(encoding="utf-8", errors="replace")
            chunks.extend(chunk_file(path, source, settings.chunk_max_chars))
            symbols.extend(symbols_for(path, source))
            files.append((path, source, git_log_for(repo_root, path)))
            if len(paths) > 20 and (position % step == 0 or position == len(paths)):
                announce(
                    "chunk",
                    f"{position} of {len(paths)} files parsed",
                    percent=int(position * 100 / len(paths)),
                )
        # Orientation context: stored, never chunked or embedded. Paths
        # already collected as source are skipped: files is keyed on
        # (repo_id, sha, path) and a duplicate fails the whole write.
        seen = {path for path, _, _ in files}
        for path in iter_doc_files(repo_root):
            if path in seen:
                continue
            source = (repo_root / path).read_text(encoding="utf-8", errors="replace")
            files.append((path, source, git_log_for(repo_root, path)))
        stats.chunks = len(chunks)
        announce(
            "chunk",
            f"{len(chunks)} chunks, {len(symbols)} symbols "
            f"in {_stage(stats, 'chunk', start):.1f}s",
        )

        if not chunks:
            logger.warning("[chunk] no Python or TypeScript files to index")

        embeddings: list[list[float]] | None = None
        if embed:
            start = time.monotonic()
            embedder = LocalEmbedder(
                model_name=settings.embedding_model,
                batch_size=settings.embed_batch_size,
            )
            embeddings = embedder.embed_documents(
                [embedding_text(c) for c in chunks],
                on_progress=lambda done, total: announce(
                    "embed",
                    f"{done} of {total} chunks embedded",
                    percent=int(done * 100 / total) if total else 100,
                ),
            )
            announce(
                "embed",
                f"{len(embeddings)} vectors in {_stage(stats, 'embed', start):.1f}s",
            )

        start = time.monotonic()
        with connect() as conn:
            write_index(
                conn,
                repo.owner,
                repo.name,
                repo.default_branch,
                repo.sha,
                chunks,
                embeddings,
                files=files,
                symbols=symbols,
                update_latest=update_latest,
            )
        announce("write", f"{len(chunks)} rows in {_stage(stats, 'write', start):.1f}s")

    logger.info(
        "[done] %s/%s@%s: %d files, %d chunks in %.1fs",
        stats.owner,
        stats.name,
        stats.sha[:8],
        stats.files,
        stats.chunks,
        sum(stats.stage_ms.values()) / 1000,
    )
    return stats


def _stage(stats: IndexStats, name: str, start: float) -> float:
    """Record a stage boundary and return its elapsed time in seconds."""
    elapsed = time.monotonic() - start
    stats.stage_ms[name] = elapsed * 1000
    return elapsed


def embed_pending(
    owner: str,
    name: str,
    sha: str,
    settings: Settings,
    on_stage: Callable[[str, str, int | None], None] | None = None,
) -> int:
    """Fill in vectors for chunks stored without them.

    Runs after the structure pass, so a repo is searchable lexically and
    fully navigable while this works through the backlog. Chunks are
    updated in batches: an interrupted run leaves the finished ones
    embedded rather than starting over.
    """
    with connect() as conn:
        conn.autocommit = True
        register_vector(conn)
        rows = conn.execute(
            """
            SELECT c.id, c.path, c.start_line, c.end_line, c.content
            FROM chunks c JOIN repos r ON r.id = c.repo_id
            WHERE r.owner = %s AND r.name = %s AND c.sha = %s
              AND c.embedding IS NULL
            ORDER BY c.id
            """,
            (owner, name, sha),
        ).fetchall()
        if not rows:
            return 0

        embedder = LocalEmbedder(
            model_name=settings.embedding_model,
            batch_size=settings.embed_batch_size,
        )
        total = len(rows)
        done = 0
        for start in range(0, total, settings.embed_batch_size):
            batch = rows[start : start + settings.embed_batch_size]
            texts = [
                embedding_text(
                    Chunk(
                        path=path,
                        language="",
                        symbol_kind="",
                        start_line=start_line,
                        end_line=end_line,
                        content=content,
                    )
                )
                for _, path, start_line, end_line, content in batch
            ]
            vectors = embedder.embed_documents(texts)
            with conn.cursor() as cursor:
                cursor.executemany(
                    "UPDATE chunks SET embedding = %s WHERE id = %s",
                    [
                        (Vector(vector), row[0])
                        for row, vector in zip(batch, vectors, strict=True)
                    ],
                )
            done += len(batch)
            if on_stage is not None:
                on_stage(
                    "embed",
                    f"{done} of {total} chunks embedded",
                    int(done * 100 / total),
                )
        logger.info("[embed] filled %d vectors for %s/%s", done, owner, name)
        return done
