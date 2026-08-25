"""Citation validation tests against the fixture repo. No network."""

from agent.citations import repair_once, validate_answer
from agent.llm import Turn


def test_valid_citations_are_kept(tool_ctx):
    result = validate_answer(
        "The store lives in src/app.py:1-2 and src/nested/util.py:1-2.",
        tool_ctx.conn,
        tool_ctx.repo_id,
        tool_ctx.sha,
    )

    assert result.invalid == []
    assert len(result.valid) == 2
    assert "src/app.py:1-2" in result.answer


def test_invalid_citations_are_stripped(tool_ctx):
    result = validate_answer(
        "It is in src/ghost.py:1-2 and also src/app.py:99-100.",
        tool_ctx.conn,
        tool_ctx.repo_id,
        tool_ctx.sha,
    )

    assert len(result.invalid) == 2  # missing file + out-of-range lines
    assert "src/ghost.py:1-2" not in result.answer
    assert "src/app.py:99-100" not in result.answer


def test_answer_without_citations_passes_through(tool_ctx):
    result = validate_answer(
        "No citations here.", tool_ctx.conn, tool_ctx.repo_id, tool_ctx.sha
    )

    assert result.valid == []
    assert result.answer == "No citations here."


class ScriptedRepairClient:
    def __init__(self, repaired: str) -> None:
        self.repaired = repaired
        self.calls = 0

    def generate(self, messages, tools, system):
        self.calls += 1
        return Turn(text=self.repaired)


def test_repair_once_asks_for_a_fix(tool_ctx):
    client = ScriptedRepairClient("fixed: src/app.py:1-2")

    fixed = repair_once(
        "draft with src/ghost.py:1-2", ["src/ghost.py:1-2"], client, system="sys"
    )

    assert fixed == "fixed: src/app.py:1-2"
    assert client.calls == 1


def test_repair_once_is_a_noop_without_invalid(tool_ctx):
    client = ScriptedRepairClient("should not be called")

    fixed = repair_once("clean answer", [], client, system="sys")

    assert fixed == "clean answer"
    assert client.calls == 0


def test_single_line_citations_are_validated(tool_ctx):
    """A single-line citation must be checked, not waved through.

    The pattern used to match only path:start-end, so the model writing
    "README.md:16" produced a line reference nobody verified — the exact
    failure this module exists to prevent.
    """
    result = validate_answer(
        "It is set in src/app.py:2 and also src/app.py:99.",
        tool_ctx.conn,
        tool_ctx.repo_id,
        tool_ctx.sha,
    )

    assert result.valid == ["src/app.py:2"]
    assert result.invalid == ["src/app.py:99"]  # file has 4 lines
    assert "src/app.py:99" not in result.answer


def test_single_line_and_range_citations_together(tool_ctx):
    result = validate_answer(
        "See src/app.py:1-2 and src/nested/util.py:1.",
        tool_ctx.conn,
        tool_ctx.repo_id,
        tool_ctx.sha,
    )

    assert set(result.valid) == {"src/app.py:1-2", "src/nested/util.py:1"}
    assert result.invalid == []
