"""Chunker tests against fixture files, asserting exact line ranges.

This is the highest-value test in the codebase: chunk boundaries are what
every citation and every retrieval result resolves against.
"""

from pathlib import Path

import pytest

from chunking.chunker import Chunk, chunk_file, symbols_for

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def chunks_for(name: str, max_chars: int = 10_000) -> list[Chunk]:
    return chunk_file(f"tests/fixtures/{name}", read_fixture(name), max_chars)


def by_name(chunks: list[Chunk], name: str | None) -> Chunk:
    matches = [c for c in chunks if c.symbol_name == name]
    assert len(matches) == 1, f"expected exactly one chunk named {name!r}"
    return matches[0]


def test_basic_python_file():
    chunks = chunks_for("basic.py")

    # Module-level leftovers (docstring + imports + constants), one chunk.
    module = by_name(chunks, None)
    assert (module.start_line, module.end_line) == (1, 7)
    assert module.symbol_kind == "module"
    assert module.content.startswith('"""Module docstring."""')

    helper = by_name(chunks, "helper")
    assert (helper.start_line, helper.end_line) == (10, 11)
    assert helper.symbol_kind == "function"
    assert helper.parent_symbol is None

    worker = by_name(chunks, "Worker")
    assert (worker.start_line, worker.end_line) == (14, 21)
    assert worker.symbol_kind == "class"

    main = by_name(chunks, "main")
    assert (main.start_line, main.end_line) == (24, 25)

    # Imports attach to every chunk.
    for chunk in chunks:
        assert chunk.imports == ["os", "pathlib"]


def test_big_function_splits_at_statement_boundaries_with_signature():
    chunks = chunks_for("big_function.py", max_chars=200)

    assert [c.symbol_name for c in chunks] == ["process", "process"]
    first, second = chunks
    assert (first.start_line, first.end_line) == (1, 8)
    assert (second.start_line, second.end_line) == (9, 13)
    # Every piece carries the signature.
    assert first.content.startswith("def process(items):\n")
    assert second.content.startswith("def process(items):\n")
    # The pieces tile the body exactly, no overlap and no gap.
    assert first.end_line + 1 == second.start_line
    assert second.content.endswith("    return result, total\n")


def test_big_class_splits_header_and_methods():
    chunks = chunks_for("big_class.py", max_chars=120)

    header = by_name(chunks, "BigClass")
    assert header.symbol_kind == "class"
    assert (header.start_line, header.end_line) == (1, 4)

    first = by_name(chunks, "first")
    assert first.symbol_kind == "method"
    assert first.parent_symbol == "BigClass"
    assert (first.start_line, first.end_line) == (6, 7)

    second = by_name(chunks, "second")
    assert second.symbol_kind == "method"
    assert second.parent_symbol == "BigClass"
    assert (second.start_line, second.end_line) == (9, 10)


def test_parse_error_falls_back_to_whole_file_chunk():
    chunks = chunks_for("syntax_error.py")

    assert len(chunks) == 1
    assert chunks[0].symbol_kind == "module"
    assert chunks[0].symbol_name is None
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 2)


def test_localized_error_does_not_lose_symbol_names():
    # One broken statement among several healthy ones must not cost the
    # whole file its symbol chunks (real case: zustand's vanilla.ts).
    chunks = chunks_for("minor_error.py")

    good = by_name(chunks, "good")
    assert good.symbol_kind == "function"
    assert (good.start_line, good.end_line) == (1, 2)

    fine = by_name(chunks, "fine")
    assert (fine.start_line, fine.end_line) == (9, 10)

    bad = by_name(chunks, "bad")
    assert (bad.start_line, bad.end_line) == (5, 6)

    # No whole-file module fallback chunk.
    assert all(c.symbol_kind != "module" for c in chunks)


def test_typescript_file():
    chunks = chunks_for("basic.ts")

    # Non-symbol declarations (imports, interface, constant, type alias)
    # merge into one module run. Pure-import runs would be dropped; these
    # imports ride along in the run's content.
    module = by_name(chunks, None)
    assert (module.start_line, module.end_line) == (1, 10)
    assert "interface Config" in module.content
    assert "const DEFAULT_PORT = 3000;" in module.content

    # An arrow function behind parens and a type cast is still a symbol.
    wrapped = by_name(chunks, "wrapped")
    assert wrapped.symbol_kind == "function"
    assert (wrapped.start_line, wrapped.end_line) == (11, 11)

    parse = by_name(chunks, "parse")
    assert parse.symbol_kind == "function"
    assert (parse.start_line, parse.end_line) == (13, 15)

    read_config = by_name(chunks, "readConfig")
    assert (read_config.start_line, read_config.end_line) == (17, 19)

    server = by_name(chunks, "Server")
    assert server.symbol_kind == "class"
    assert (server.start_line, server.end_line) == (21, 31)

    for chunk in chunks:
        assert chunk.imports == ["node:fs", "./types"]
        assert chunk.language == "typescript"


def test_symbols_include_module_symbols_and_class_members():
    symbols = symbols_for("tests/fixtures/basic.py", read_fixture("basic.py"))
    found = {(s.name, s.kind, s.line, s.parent) for s in symbols}

    assert ("helper", "function", 10, None) in found
    assert ("Worker", "class", 14, None) in found
    assert ("__init__", "method", 17, "Worker") in found
    assert ("run", "method", 20, "Worker") in found
    assert ("main", "function", 24, None) in found


def test_symbols_for_typescript_includes_wrapped_arrows_and_methods():
    symbols = symbols_for("tests/fixtures/basic.ts", read_fixture("basic.ts"))
    found = {(s.name, s.kind, s.line, s.parent) for s in symbols}

    assert ("wrapped", "function", 11, None) in found
    assert ("parse", "function", 13, None) in found
    assert ("readConfig", "function", 17, None) in found
    assert ("Server", "class", 21, None) in found
    assert ("constructor", "method", 24, "Server") in found
    assert ("start", "method", 28, "Server") in found


def test_symbols_survive_localized_parse_errors():
    symbols = symbols_for(
        "tests/fixtures/minor_error.py", read_fixture("minor_error.py")
    )
    names = {(s.name, s.line) for s in symbols}
    assert ("good", 1) in names
    assert ("fine", 9) in names


def test_oversized_signature_is_capped_and_ranges_stay_unique():
    # FastAPI's __init__ has a signature bigger than the budget itself;
    # every piece must still start at a distinct real line.
    chunks = chunks_for("huge_signature.py", max_chars=250)

    starts = [c.start_line for c in chunks]
    assert len(starts) == len(set(starts))
    for chunk in chunks:
        assert chunk.symbol_name == "configure"
        # The signature (capped or not) leads every piece.
        assert chunk.content.startswith("def configure(")


def test_unsupported_extension_raises():
    with pytest.raises(ValueError, match="unsupported file type"):
        chunk_file("main.go", "package main\n", 10_000)
