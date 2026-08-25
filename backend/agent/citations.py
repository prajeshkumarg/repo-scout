"""Citation validation: never trust the model's line numbers.

Every `path:start-end` in the final answer is checked against the index
for that SHA: the file must exist and the range must be within it.
Invalid citations are stripped and the model gets ONE retry to fix or
remove them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import psycopg

from agent.llm import LLMClient

# Ranges and single lines both. The model writes README.md:16 as
# readily as README.md:1-8, and a pattern that only knows ranges lets
# the single-line form past validation entirely — an unchecked line
# number reaching the reader is exactly what this module exists to stop.
CITATION_PATTERN = re.compile(r"\b([\w./\-]+):(\d+)(?:-(\d+))?\b")

_REPAIR_PROMPT = """Here is a draft answer about a repository:

{draft}

These citations in it do not match the code at the pinned commit
(file missing or line range out of bounds):

{invalid}

Rewrite the answer: fix the citations to real files and line ranges you
were shown, or drop any claim you cannot cite. Keep everything else."""


@dataclass
class Validation:
    """The cleaned answer and what was found in it."""

    answer: str
    valid: list[str]
    invalid: list[str]
    repaired: bool = False


def validate_answer(
    text: str, conn: psycopg.Connection[Any], repo_id: int, sha: str
) -> Validation:
    """Strip citations that do not resolve against the index."""
    matches = list(CITATION_PATTERN.finditer(text))
    if not matches:
        return Validation(answer=text, valid=[], invalid=[])

    paths = {match.group(1) for match in matches}
    if paths:
        rows = conn.execute(
            """
            SELECT path, array_length(string_to_array(content, E'\\n'), 1)
            FROM files
            WHERE repo_id = %s AND sha = %s AND path = ANY(%s)
            """,
            (repo_id, sha, list(paths)),
        ).fetchall()
        line_counts = {path: count for path, count in rows}

    valid: list[str] = []
    invalid: list[str] = []
    for match in matches:
        path, start = match.group(1), int(match.group(2))
        end = int(match.group(3)) if match.group(3) else start
        citation = match.group(0)
        count = line_counts.get(path)
        if count is not None and 1 <= start <= end <= count:
            valid.append(citation)
        else:
            invalid.append(citation)
            text = text.replace(citation, "")
    return Validation(answer=text, valid=valid, invalid=invalid)


def repair_once(draft: str, invalid: list[str], client: LLMClient, system: str) -> str:
    """The one allowed retry: ask the model to fix its citations."""
    if not invalid:
        return draft
    prompt = _REPAIR_PROMPT.format(
        draft=draft, invalid="\n".join(f"- {c}" for c in invalid)
    )
    turn = client.generate([{"role": "user", "text": prompt}], tools=[], system=system)
    return turn.text or draft
