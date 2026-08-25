"""Filter tests against a throwaway git repo built in a tmp dir."""

import subprocess

import pytest

from ingest.filters import (
    MAX_FILE_BYTES,
    iter_doc_files,
    iter_source_files,
    within_budget,
)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored.py\n")

    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "keep.ts").write_text("const x = 1;\n")
    (tmp_path / "drop.min.js").write_text("const x=1;")
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "app.d.ts").write_text("export declare const x: number;")
    (tmp_path / "big.py").write_bytes(b" " * (MAX_FILE_BYTES + 1))
    (tmp_path / "binary.py").write_bytes(b"print(1)\x00")
    (tmp_path / "ignored.py").write_text("x = 1\n")
    (tmp_path / "notes.md").write_text("not source")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "vendored.py").write_text("x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.ts").write_text("export const x = 1;\n")
    (tmp_path / "generated.generated.py").write_text("x = 1\n")
    return tmp_path


def test_keeps_only_python_and_typescript_source(repo):
    assert iter_source_files(repo) == ["keep.py", "keep.ts"]


def test_empty_dir_returns_empty(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    assert iter_source_files(tmp_path) == []


def test_doc_files_keep_manifests_but_not_source(repo):
    (repo / "README.md").write_text("# hi\n")
    (repo / "pyproject.toml").write_text("[project]\n")
    # setup.py is a manifest AND a .py source file. iter_source_files
    # already returns it, so returning it here too would insert the same
    # (repo_id, sha, path) twice and fail the whole index write — which
    # is exactly what happened on psf/requests.
    (repo / "setup.py").write_text("from setuptools import setup\n")

    docs = iter_doc_files(repo)
    sources = iter_source_files(repo)

    assert "README.md" in docs
    assert "pyproject.toml" in docs
    assert "setup.py" not in docs
    assert "setup.py" in sources
    assert not set(docs) & set(sources), "docs and sources must not overlap"


def test_within_budget_keeps_everything_when_it_fits(tmp_path):
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("x = 1\n")

    kept, skipped = within_budget(tmp_path, ["a.py", "b.py"])

    assert kept == ["a.py", "b.py"]
    assert skipped == 0


def test_within_budget_prefers_source_over_tests_and_examples(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "core.py").write_text("x = 1\n")
    (tmp_path / "tests" / "test_core.py").write_text("x = 1\n")
    paths = ["src/core.py", "tests/test_core.py"]

    kept, skipped = within_budget(tmp_path, paths, max_files=1)

    # Over budget, the source file is the one worth keeping.
    assert kept == ["src/core.py"]
    assert skipped == 1


def test_within_budget_respects_a_byte_budget(tmp_path):
    (tmp_path / "small.py").write_text("x = 1\n")
    (tmp_path / "big.py").write_text("y = 2\n" * 500)
    paths = ["big.py", "small.py"]

    kept, skipped = within_budget(tmp_path, paths, max_bytes=50)

    assert kept == ["small.py"]
    assert skipped == 1


def test_within_budget_never_returns_nothing_when_a_file_fits(tmp_path):
    # A single oversized file must not starve the rest: skipping it is
    # right, returning an empty index is not.
    (tmp_path / "huge.py").write_text("y = 2\n" * 5000)
    (tmp_path / "tiny.py").write_text("x = 1\n")

    kept, skipped = within_budget(tmp_path, ["huge.py", "tiny.py"], max_bytes=100)

    assert kept == ["tiny.py"]
    assert skipped == 1
