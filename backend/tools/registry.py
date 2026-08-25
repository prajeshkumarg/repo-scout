"""The tool registry: what the agent can call and how to describe it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tools.base import ToolResult
from tools.files import git_log, grep, list_dir, read_file
from tools.search import search_code
from tools.symbols import find_references, find_symbol


@dataclass
class ToolSpec:
    """A tool: its function, its Gemini declaration, and its description."""

    name: str
    function: Callable[..., ToolResult]
    declaration: dict
    description: str


def _declaration(
    name: str, description: str, properties: dict, required: list[str]
) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "OBJECT",
            "properties": properties,
            "required": required,
        },
    }


def _prop(type_: str, description: str, **extra: object) -> dict:
    return {"type": type_, "description": description, **extra}


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="search_code",
        function=lambda ctx, query, k=10: search_code(ctx, query, k),
        declaration=_declaration(
            "search_code",
            "Semantic + keyword search over code chunks. Good first move for "
            "any question phrased in English. Returns chunk snippets with "
            "path:start-end.",
            {
                "query": _prop("STRING", "what to search for"),
                "k": _prop("INTEGER", "results (max 10)"),
            },
            ["query"],
        ),
        description="hybrid retrieval over chunks",
    ),
    ToolSpec(
        name="grep",
        function=lambda ctx, pattern, path="": grep(ctx, pattern, path),
        declaration=_declaration(
            "grep",
            "Exact regular-expression search over file contents. Use for "
            "identifiers and literals that must match exactly.",
            {
                "pattern": _prop("STRING", "regex to search for"),
                "path": _prop(
                    "STRING", "directory or file to limit the search to (optional)"
                ),
            },
            ["pattern"],
        ),
        description="exact regex search",
    ),
    ToolSpec(
        name="read_file",
        function=lambda ctx, path, start=1, end=None: read_file(ctx, path, start, end),
        declaration=_declaration(
            "read_file",
            "Read a line range of one file. Ranges are 1-based inclusive; "
            "max 400 lines per call, with a truncation marker.",
            {
                "path": _prop("STRING", "file path"),
                "start": _prop("INTEGER", "first line (1-based, default 1)"),
                "end": _prop("INTEGER", "last line (optional; defaults to file end)"),
            },
            ["path"],
        ),
        description="read a file range",
    ),
    ToolSpec(
        name="list_dir",
        function=lambda ctx, path="": list_dir(ctx, path),
        declaration=_declaration(
            "list_dir",
            "List one directory level: immediate files and subdirectories.",
            {"path": _prop("STRING", "directory ('' for the repo root)")},
            [],
        ),
        description="list one directory level",
    ),
    ToolSpec(
        name="find_symbol",
        function=lambda ctx, name: find_symbol(ctx, name),
        declaration=_declaration(
            "find_symbol",
            "Find definition sites of a symbol by exact name, from the "
            "symbol table. Returns path:line plus kind.",
            {"name": _prop("STRING", "exact symbol name")},
            ["name"],
        ),
        description="definition sites by name",
    ),
    ToolSpec(
        name="find_references",
        function=lambda ctx, name: find_references(ctx, name),
        declaration=_declaration(
            "find_references",
            "Find uses of an identifier across the repo (best effort, "
            "full-text). Returns path:start-end per match.",
            {"name": _prop("STRING", "identifier to search for")},
            ["name"],
        ),
        description="identifier uses, best effort",
    ),
    ToolSpec(
        name="git_log",
        function=lambda ctx, path, n=10: git_log(ctx, path, n),
        declaration=_declaration(
            "git_log",
            "Recent commits touching a file: for 'why is this here' questions.",
            {
                "path": _prop("STRING", "file path"),
                "n": _prop("INTEGER", "commits to show (default 10)"),
            },
            ["path"],
        ),
        description="recent commits for a file",
    ),
]

TOOLS_BY_NAME = {spec.name: spec for spec in TOOLS}
