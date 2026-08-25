"""Tool tests against a fixture repo in the test database. No network.

The indexed fixture repo lives in conftest's `tool_ctx` fixture.
"""

from tools.files import git_log, grep, list_dir, literal_prefilter, read_file
from tools.search import search_code
from tools.symbols import find_references, find_symbol


def test_read_file_range(tool_ctx):
    result = read_file(tool_ctx, "src/app.py", start=1, end=2)

    assert result.summary == "read src/app.py:1-2"
    assert result.content.startswith("src/app.py:1-2\n1: SESSION_STORE = {}")
    assert result.files_read == ["src/app.py"]


def test_read_file_caps_at_400_lines_with_marker(tool_ctx):
    content = "\n".join(f"x = {i}" for i in range(500))
    tool_ctx.conn.execute(
        "UPDATE files SET content = %s WHERE path = 'src/app.py'", (content,)
    )
    result = read_file(tool_ctx, "src/app.py", start=1, end=500)

    assert "truncated at 400 lines" in result.content
    assert result.files_read == ["src/app.py"]


def test_read_file_missing_file_is_an_error(tool_ctx):
    result = read_file(tool_ctx, "src/ghost.py")

    assert result.summary.startswith("error:")
    assert result.files_read == []


def test_list_dir_is_one_level(tool_ctx):
    root = list_dir(tool_ctx)
    nested = list_dir(tool_ctx, "src")

    assert "src/" in root.content
    assert "app.py" in nested.content
    assert "nested/" in nested.content


def test_grep_finds_matches_with_line_numbers(tool_ctx):
    result = grep(tool_ctx, r"SESSION")

    assert result.summary.startswith("grep")
    assert "src/app.py:1:" in result.content
    assert result.files_read == ["src/app.py"]


def test_grep_invalid_regex_is_an_error(tool_ctx):
    result = grep(tool_ctx, "([unclosed")

    assert result.summary.startswith("error:")


def test_git_log_returns_stored_history(tool_ctx):
    result = git_log(tool_ctx, "src/app.py", n=5)

    assert "abc|dev|2026-01-01|init" in result.content
    assert result.files_read == ["src/app.py"]


def test_find_symbol_exact_match(tool_ctx):
    result = find_symbol(tool_ctx, "find_me")

    assert "src/app.py:4" in result.content
    assert "function find_me" in result.content
    assert result.files_read == ["src/app.py"]


def test_find_symbol_missing_is_not_found(tool_ctx):
    result = find_symbol(tool_ctx, "ghost")

    assert result.content == "not found"


def test_find_references_uses_fts(tool_ctx):
    result = find_references(tool_ctx, "helper")

    assert "src/nested/util.py" in result.content
    assert result.files_read == ["src/nested/util.py"]


def test_search_code_returns_chunks_with_snippets(tool_ctx):
    result = search_code(tool_ctx, "find me")

    # Both fixture chunks carry identical fake embeddings, so both can
    # rank; the point is the target chunk's snippet comes back.
    assert "src/app.py" in result.files_read
    assert "def find_me()" in result.content


def test_literal_prefilter_picks_the_longest_plain_run():
    # Used to narrow by trigram index before matching the full regex.
    assert literal_prefilter("def echo") == "echo"
    assert literal_prefilter(r"class\s+Command") == "Command"
    assert literal_prefilter("createStore") == "createStore"
    # Nothing long enough to narrow with: read everything rather than
    # narrowing wrongly and losing matches.
    assert literal_prefilter(r"\w+") is None
    assert literal_prefilter("a|b") is None


def test_grep_with_metacharacter_pattern_still_matches(tool_ctx):
    # The narrowing must never change the answer, only the work done.
    narrowed = grep(tool_ctx, r"SESSION\w+")
    assert "src/app.py:1:" in narrowed.content


def test_grep_narrowing_agrees_with_a_full_scan(tool_ctx):
    # A pattern whose literal narrows, and one that cannot narrow at all,
    # must find the same lines.
    with_literal = grep(tool_ctx, "line_1")
    without = grep(tool_ctx, r"line_\d")
    assert "line_1" in with_literal.content
    assert "line_1" in without.content
