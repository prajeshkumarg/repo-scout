"""Tests for the eval runner's pure logic (no network, no DB)."""

import sys
from pathlib import Path

# The runner lives outside backend/; import its pure helpers directly.
EVALS_DIR = Path(__file__).parent.parent.parent / "evals"
sys.path.insert(0, str(EVALS_DIR))

from run import load_fixtures, recall_at_k  # noqa: E402


def test_recall_at_k_counts_ground_truth_fraction():
    assert recall_at_k({"a.py", "b.py"}, {"a.py", "c.py"}) == 0.5
    assert recall_at_k({"a.py"}, {"a.py"}) == 1.0
    assert recall_at_k({"a.py"}, {"b.py"}) == 0.0
    assert recall_at_k(set(), {"b.py"}) == 1.0


def test_load_fixtures_reads_pinned_repos():
    fixtures = load_fixtures()
    assert len(fixtures) == 3
    by_name = {f.name: f for f in fixtures}
    assert by_name["click"].sha.startswith("36baa15f")
    assert len(by_name["click"].sha) == 40


def test_question_files_exist_for_every_fixture():
    for fixture in load_fixtures():
        path = EVALS_DIR / "questions" / f"{fixture.name}.yml"
        assert path.exists(), f"missing questions for {fixture.name}"


def test_each_repo_has_twenty_questions():
    import yaml

    for fixture in load_fixtures():
        raw = yaml.safe_load(
            (EVALS_DIR / "questions" / f"{fixture.name}.yml").read_text()
        )
        questions = raw["questions"]
        assert len(questions) == 20, f"{fixture.name}: {len(questions)} questions"
        for q in questions:
            assert q["question"].strip()
            assert q["files"], f"question without ground truth: {q['question']}"
