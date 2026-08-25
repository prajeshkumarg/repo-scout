"""Skip lists for ingest. All path filtering lives here (rules/ingest.md).

M1 indexes Python and TypeScript source only. Docs, config, and CI files
are filtered out for now; M2 evals decide whether their absence hurts
recall before anything is added back.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from chunking.languages import EXTENSION_LANGUAGES

MAX_FILE_BYTES = 1_048_576  # 1 MB per file, per the spec

# Files kept for context (README, manifests, CI) but never chunked or
# embedded: they belong to orientation, not retrieval. Keeping them out
# of `chunks` means the recall baseline stays comparable.
DOC_FILENAMES = {
    "readme.md",
    "readme.rst",
    "readme.txt",
    "pyproject.toml",
    "package.json",
    "setup.py",
    "setup.cfg",
    "cargo.toml",
    "go.mod",
    "dockerfile",
    "makefile",
}

# Directories that never contain source worth indexing.
DROP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".venv",
    "out",
}

LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "Cargo.lock",
}

# Minified bundles, sourcemaps, and generated declarations.
DROP_SUFFIXES = {".min.js", ".min.css", ".min.mjs", ".map", ".d.ts"}

GENERATED_MARKERS = (".generated.", ".pb.")


def is_binary(path: Path) -> bool:
    """A file with a NUL byte in its first kibibyte is binary."""
    with path.open("rb") as handle:
        return b"\x00" in handle.read(1024)


def _is_droppable(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if any(part in DROP_DIRS for part in parts):
        return True
    name = Path(rel_path).name
    if name in LOCKFILES:
        return True
    if any(name.endswith(suffix) for suffix in DROP_SUFFIXES):
        return True
    if any(marker in name for marker in GENERATED_MARKERS):
        return True
    return False


def git_ignored(root: Path, paths: list[str]) -> set[str]:
    """The subset of `paths` matched by the repo's .gitignore rules.

    Uses `git check-ignore` so the real gitignore semantics apply, no
    hand-rolled matcher to drift from git's. Returns an empty set when the
    root is not a git repo (nothing to ask).
    """
    if not paths:
        return set()
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin", "-z"],
        input="\0".join(paths),
        capture_output=True,
        text=True,
    )
    # Exit code 0 means "some paths ignored", 1 means "none"; output only
    # appears in the first case.
    return set(result.stdout.split("\0")) - {""}


def iter_doc_files(root: Path) -> list[str]:
    """README, manifests, and other orientation context at the repo root.

    Stored as files so the landing page can read them; never chunked.
    """
    kept: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file() or entry.name.lower() not in DOC_FILENAMES:
            continue
        # setup.py is both a manifest and a source file. iter_source_files
        # already returns it, and adding it here too violates the unique
        # constraint on (repo_id, sha, path).
        if entry.suffix.lower() in EXTENSION_LANGUAGES:
            continue
        if entry.stat().st_size > MAX_FILE_BYTES or is_binary(entry):
            continue
        kept.append(entry.name)
    return kept


def iter_source_files(root: Path) -> list[str]:
    """Relative paths of the files to index, sorted for stable runs."""
    kept: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DROP_DIRS]
        for filename in filenames:
            rel_path = os.path.relpath(os.path.join(dirpath, filename), root)
            if _is_droppable(rel_path):
                continue
            if Path(filename).suffix.lower() not in EXTENSION_LANGUAGES:
                continue
            path = root / rel_path
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            if is_binary(path):
                continue
            kept.append(rel_path)
    ignored = git_ignored(root, kept)
    return sorted(path for path in kept if path not in ignored)


# What one repo may occupy. A budget rather than a refusal: a repo over
# the line gets its most useful files indexed instead of being turned
# away, which is the same bargain DeepWiki strikes when it caps
# generation and lets you steer scope rather than rejecting monorepos.
MAX_INDEX_FILES = 4000
MAX_INDEX_BYTES = 40 * 1024 * 1024

# Directories that are real but rarely what someone is asking about.
# Ranked below source, never dropped outright.
LOW_PRIORITY_DIRS = frozenset(
    {
        "test",
        "tests",
        "spec",
        "specs",
        "example",
        "examples",
        "docs",
        "doc",
        "benchmark",
        "benchmarks",
        "fixtures",
        "testdata",
        "third_party",
    }
)


def _priority(rel_path: str) -> tuple[int, int, int]:
    """Sort key: source first, then shallower, then smaller."""
    parts = rel_path.split("/")
    deprioritised = any(part.lower() in LOW_PRIORITY_DIRS for part in parts)
    return (1 if deprioritised else 0, len(parts), len(rel_path))


def within_budget(
    root: Path,
    paths: list[str],
    max_files: int = MAX_INDEX_FILES,
    max_bytes: int = MAX_INDEX_BYTES,
) -> tuple[list[str], int]:
    """Trim a file list to the storage budget, best files first.

    Returns the kept paths in their original order plus the number
    skipped, so the caller can say what was left out rather than
    quietly indexing part of a repo and calling it whole.
    """
    if len(paths) <= max_files:
        total = sum((root / p).stat().st_size for p in paths)
        if total <= max_bytes:
            return paths, 0

    kept: list[str] = []
    used = 0
    for rel_path in sorted(paths, key=_priority):
        size = (root / rel_path).stat().st_size
        if len(kept) >= max_files or used + size > max_bytes:
            continue
        kept.append(rel_path)
        used += size
    return sorted(kept), len(paths) - len(kept)
