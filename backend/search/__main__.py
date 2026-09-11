"""CLI: python -m search [--deep] [--repo owner/name] "<query>".

Fast mode prints hybrid retrieval hits; deep mode runs the agent loop
with a live step trace and post-validated citations. Results go to
stdout; diagnostics go to stderr via logging.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from agent.ask import ask_deep
from agent.llm import GeminiClient
from agent.loop import StepRecord
from agent.runs import record_run
from config import Settings, get_settings
from db.conn import connect
from db.schema import ensure_schema
from embedding import LocalEmbedder
from tools.base import ToolContext
from tools.search import hybrid_search


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m search",
        description="Code search over the indexed repos.",
    )
    parser.add_argument("query", help="a question or identifier to search for")
    parser.add_argument(
        "-k", type=int, default=10, help="results to print (default 10)"
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="agentic deep mode: tools, trace, validated citations",
    )
    parser.add_argument(
        "--repo",
        help="owner/name to search (required when several repos are indexed)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()

    if args.deep:
        _deep_mode(args, settings)
    else:
        _fast_mode(args, settings)


def _fast_mode(args: argparse.Namespace, settings: Settings) -> None:
    embedder = LocalEmbedder(
        model_name=settings.embedding_model,
        batch_size=settings.embed_batch_size,
    )
    query_vector = embedder.embed_query(args.query)
    with connect() as conn:
        conn.autocommit = True
        ensure_schema(conn)
        hits = hybrid_search(conn, args.query, query_vector, k=args.k)

    if not hits:
        print("no results. Index a repo first: python -m ingest <github-url>")
        return
    for position, hit in enumerate(hits, start=1):
        header = f"{hit.path}:{hit.start_line}-{hit.end_line}"
        if hit.symbol_name:
            header += f" ({hit.symbol_name})"
        print(
            f"{position}. {header}  {hit.owner}/{hit.name}@{hit.sha[:8]}  "
            f"score={hit.score:.4f}"
        )
        snippet = "\n".join(hit.content.splitlines()[:6])
        print(f"   {snippet}")
        print()


def _deep_mode(args: argparse.Namespace, settings: Settings) -> None:
    if not settings.google_api_key:
        logging.error("error: GOOGLE_API_KEY is not set; add it to .env")
        sys.exit(1)

    with connect() as conn:
        # The dev database may predate new tables; ensure_schema is
        # idempotent and cheap.
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT id, owner, name, last_indexed_sha FROM repos
            WHERE last_indexed_sha IS NOT NULL ORDER BY id
            """
        ).fetchall()
        if not rows:
            logging.error(
                "error: no indexed repos. Index one first: python -m ingest <url>"
            )
            sys.exit(1)
        if args.repo is None and len(rows) > 1:
            listed = ", ".join(f"{owner}/{name}" for _, owner, name, _ in rows)
            logging.error("error: several repos indexed (%s); pass --repo", listed)
            sys.exit(1)
        repo = (
            rows[0]
            if args.repo is None
            else next((row for row in rows if f"{row[1]}/{row[2]}" == args.repo), None)
        )
        if repo is None:
            logging.error("error: repo %r is not indexed", args.repo)
            sys.exit(1)

        repo_id, owner, name, sha = repo
        embedder = LocalEmbedder(
            model_name=settings.embedding_model,
            batch_size=settings.embed_batch_size,
        )
        ctx = ToolContext(conn=conn, repo_id=repo_id, sha=sha, embedder=embedder)
        client = GeminiClient(settings.google_api_key, settings.google_agent_model)

        cancel = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: cancel.set())

        _steps = []

        def on_step(step: StepRecord) -> None:
            _steps.append(step)
            print(f"  step {len(_steps)}: {step.tool}({step.args})")
            print(f"      -> {step.summary} ({step.ms}ms)")

        print(f"deep mode: {owner}/{name}@{sha[:8]} | {args.query}")
        try:
            run, validation = ask_deep(args.query, ctx, client, on_step=on_step)
        except Exception as exc:  # record the failure, then surface it
            record_run(
                conn,
                repo_id=repo_id,
                sha=sha,
                mode="deep",
                question=args.query,
                steps=_steps,
                tokens=0,
                latency_ms=0,
                finished=False,
            )
            raise exc

        record_run(
            conn,
            repo_id=repo_id,
            sha=sha,
            mode="deep",
            question=args.query,
            steps=run.steps,
            tokens=run.tokens,
            latency_ms=run.latency_ms,
            finished=run.finished,
        )

    print()
    print(validation.answer)
    print()
    print(
        f"({len(run.steps)} steps, {run.tokens} tokens, "
        f"{run.latency_ms / 1000:.1f}s, finished={run.finished})"
    )
    if validation.invalid:
        print(f"warning: {len(validation.invalid)} invalid citations stripped")


if __name__ == "__main__":
    main()
