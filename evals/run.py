"""Eval runner: retrieval recall@10 over the fixture repos.

`make eval` prints a table and writes JSON to evals/results/. The recall
number is the baseline every later retrieval change is compared against;
a regression against evals/results/baseline.json fails CI.

Runs against the same database as the dev tooling. Fixture indexes are
keyed by pinned SHA and never move the `last_indexed_sha` pointer, so
evaluating an old fixture cannot make the search CLI serve stale code.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# The runner lives outside backend/; make it importable alongside the app.
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import yaml  # noqa: E402

from config import get_settings  # noqa: E402
from db.conn import connect  # noqa: E402
from db.schema import ensure_schema  # noqa: E402
from embedding import LocalEmbedder  # noqa: E402
from ingest.clone import parse_github_url  # noqa: E402
from ingest.pipeline import run as index_repo  # noqa: E402
from tools.search import hybrid_search  # noqa: E402

EVALS_DIR = Path(__file__).parent
FIXTURES_PATH = EVALS_DIR / "fixtures.yml"
QUESTIONS_DIR = EVALS_DIR / "questions"
RESULTS_DIR = EVALS_DIR / "results"
LATEST_PATH = RESULTS_DIR / "latest.json"
BASELINE_PATH = RESULTS_DIR / "baseline.json"

K = 10
# A regression is a drop of more than this against the recorded baseline.
REGRESSION_TOLERANCE = 0.02


@dataclass
class RepoFixture:
    url: str
    sha: str

    @property
    def owner(self) -> str:
        owner, _ = parse_github_url(self.url)
        return owner

    @property
    def name(self) -> str:
        _, name = parse_github_url(self.url)
        return name


@dataclass
class Question:
    text: str
    files: set[str]


def recall_at_k(ground_truth: set[str], hit_files: set[str]) -> float:
    """The fraction of ground-truth files present among the hit files."""
    if not ground_truth:
        return 1.0
    return len(ground_truth & hit_files) / len(ground_truth)


def load_fixtures() -> list[RepoFixture]:
    raw = yaml.safe_load(FIXTURES_PATH.read_text())
    return [RepoFixture(url=r["url"], sha=r["sha"]) for r in raw["repos"]]


def load_questions(repo: RepoFixture) -> list[Question]:
    path = QUESTIONS_DIR / f"{repo.name}.yml"
    raw = yaml.safe_load(path.read_text())
    return [
        Question(text=q["question"], files=set(q["files"]))
        for q in raw["questions"]
    ]


def repo_is_indexed(conn, owner: str, name: str, sha: str) -> bool:
    """True when the index is complete: chunks, files, and symbols.

    Deep mode reads files and symbols, so a chunks-only index (written
    before those tables existed) must be rebuilt, not reused.
    """
    row = conn.execute(
        """
        SELECT
            (SELECT count(*) FROM chunks c WHERE c.repo_id = r.id AND c.sha = %s),
            (SELECT count(*) FROM files f WHERE f.repo_id = r.id AND f.sha = %s),
            (SELECT count(*) FROM symbols s WHERE s.repo_id = r.id AND s.sha = %s)
        FROM repos r WHERE r.owner = %s AND r.name = %s
        """,
        (sha, sha, sha, owner, name),
    ).fetchone()
    return row is not None and all(count > 0 for count in row)


def evaluate_repo(
    conn, embedder, repo: RepoFixture, questions: list[Question]
) -> dict:
    """Run every question and return recall details for the repo."""
    details = []
    for question in questions:
        query_vector = embedder.embed_query(question.text)
        hits = hybrid_search(conn, question.text, query_vector, k=K)
        hit_files = {hit.path for hit in hits}
        details.append(
            {
                "question": question.text,
                "recall": recall_at_k(question.files, hit_files),
                "hit_files": sorted(hit_files),
                "missing": sorted(question.files - hit_files),
            }
        )
    return {
        "owner": repo.owner,
        "name": repo.name,
        "sha": repo.sha,
        "recall": sum(d["recall"] for d in details) / len(details),
        "questions": details,
    }


def evaluate_repo_deep(
    conn, repo: RepoFixture, questions: list[Question], settings
) -> dict:
    """Deep mode: recall over the union of everything the agent read.

    Also reports how many files that union contains. Deep mode is
    structurally allowed to see more than fast mode's top-k (one
    search_code call alone returns up to 10), so the breadth number is
    what keeps the recall comparison honest rather than flattering.
    """
    repo_row = conn.execute(
        "SELECT id FROM repos WHERE owner = %s AND name = %s",
        (repo.owner, repo.name),
    ).fetchone()
    if repo_row is None:
        return 0.0

    from agent.ask import ask_deep
    from agent.llm import GeminiClient
    from embedding import LocalEmbedder
    from tools.base import ToolContext

    embedder = LocalEmbedder(
        model_name=settings.embedding_model,
        batch_size=settings.embed_batch_size,
    )
    ctx = ToolContext(
        conn=conn, repo_id=repo_row[0], sha=repo.sha, embedder=embedder
    )
    client = GeminiClient(settings.google_api_key, settings.google_agent_model)

    recalls = []
    breadth = []
    for question in questions:
        run, _ = ask_deep(question.text, ctx, client)
        recalls.append(recall_at_k(question.files, set(run.files_read)))
        breadth.append(len(set(run.files_read)))
        print(
            f"  deep: {question.text[:50]!r} -> "
            f"{recalls[-1]:.1f} ({len(run.steps)} steps, {breadth[-1]} files)"
        )
    return {
        "recall": sum(recalls) / len(recalls),
        "files_per_question": sum(breadth) / len(breadth),
    }


def print_table(results: dict) -> None:
    """A human-readable recall table, per repo and overall.

    When deep-mode numbers are present they get their own column.
    """
    has_deep = any("deep_recall" in repo for repo in results["repos"])
    line = "-" * (58 + (13 if has_deep else 0))
    print(line)
    header = f"{'repo':<24} {'questions':>9} {'recall@10':>11}"
    if has_deep:
        header += f" {'deep@10':>12}"
    print(header)
    print(line)
    total_questions = 0
    for repo in results["repos"]:
        count = len(repo["questions"])
        total_questions += count
        label = f"{repo['owner']}/{repo['name']}"
        row = f"{label:<24} {count:>9} {repo['recall']:>10.2f}"
        if has_deep:
            deep = repo.get("deep_recall")
            row += f" {deep:>11.2f}" if deep is not None else "       (n/a)"
        print(row)
    print(line)
    overall = f"{results['overall_recall']:>10.2f}"
    if has_deep and "overall_deep_recall" in results:
        overall += f" {results['overall_deep_recall']:>11.2f}"
    print(f"{'overall':<24} {total_questions:>9} {overall}")
    print(line)


def main() -> None:
    parser = argparse.ArgumentParser(prog="make eval")
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="write the current result as the regression baseline",
    )
    parser.add_argument(
        "--check-regression",
        action="store_true",
        help="fail when recall regresses against the recorded baseline",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="also run deep mode (the agent loop) per question; slow, "
        "uses real LLM quota",
    )
    parser.add_argument(
        "--repo",
        help="only evaluate this fixture repo (name)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="only evaluate the first N questions per repo (quota control)",
    )
    args = parser.parse_args()

    # Without this the pipeline's progress goes nowhere and a CI run
    # sits silent for the whole indexing pass, which reads as a hang.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    settings = get_settings()
    embedder = LocalEmbedder(
        model_name=settings.embedding_model,
        batch_size=settings.embed_batch_size,
    )
    if args.deep and not settings.google_api_key:
        print("error: --deep needs GOOGLE_API_KEY in .env")
        sys.exit(2)

    repo_results = []
    with connect() as conn:
        # CI runs against a database created seconds ago, so the first
        # query here is the first thing to touch it. Nothing else in this
        # path creates the schema: indexing does, and that comes later.
        conn.autocommit = True
        ensure_schema(conn)
        for repo in load_fixtures():
            if args.repo and repo.name != args.repo:
                continue
            if not repo_is_indexed(conn, repo.owner, repo.name, repo.sha):
                print(f"indexing {repo.owner}/{repo.name} @ {repo.sha[:8]} ...")
                # Fixture indexes must not move the dev "latest" pointer.
                index_repo(repo.url, settings, sha=repo.sha, update_latest=False)
            questions = load_questions(repo)[: args.limit] if args.limit else load_questions(repo)
            if not questions:
                continue
            result = evaluate_repo(conn, embedder, repo, questions)
            if args.deep:
                deep = evaluate_repo_deep(conn, repo, questions, settings)
                result["deep_recall"] = deep["recall"]
                result["deep_files_per_question"] = deep["files_per_question"]
                print(
                    f"{repo.owner}/{repo.name}: deep recall "
                    f"{deep['recall']:.2f} over "
                    f"{deep['files_per_question']:.1f} files/question"
                )
            repo_results.append(result)

    overall = sum(r["recall"] for r in repo_results) / len(repo_results)
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.embedding_model,
        "k": K,
        "overall_recall": overall,
        "repos": repo_results,
    }
    if args.deep:
        results["overall_deep_recall"] = sum(
            r["deep_recall"] for r in repo_results
        ) / len(repo_results)
    print_table(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(results, indent=2))

    if args.record_baseline:
        baseline = {"recorded_at": results["generated_at"], **results}
        BASELINE_PATH.write_text(json.dumps(baseline, indent=2))
        print(f"baseline recorded to {BASELINE_PATH}")

    if args.check_regression:
        if not BASELINE_PATH.exists():
            print(f"error: no baseline at {BASELINE_PATH}; record one first")
            sys.exit(2)
        baseline = json.loads(BASELINE_PATH.read_text())
        allowed = baseline["overall_recall"] - REGRESSION_TOLERANCE
        if overall < allowed:
            print(
                f"recall regression: {overall:.2f} < baseline "
                f"{baseline['overall_recall']:.2f} - {REGRESSION_TOLERANCE:.2f}"
            )
            sys.exit(1)
        print(f"recall {overall:.2f} >= baseline {baseline['overall_recall']:.2f}")


if __name__ == "__main__":
    main()
