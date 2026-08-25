"""Cloning public GitHub repos for indexing.

Everything downstream is keyed on the SHA recorded here, so indexing is
idempotent per commit.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_GITHUB_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")


@dataclass
class Repo:
    """A shallow clone on disk plus the facts indexing needs."""

    owner: str
    name: str
    default_branch: str
    sha: str
    root: Path


def parse_github_url(url: str) -> tuple[str, str]:
    """Split a GitHub repo URL into (owner, name). Raises ValueError."""
    match = _GITHUB_URL.match(url.strip())
    if match is None:
        raise ValueError(
            f"expected a GitHub repo URL like https://github.com/owner/name, "
            f"got: {url!r}"
        )
    return match.group(1), match.group(2)


def clone_repo(url: str, into: Path, sha: str | None = None, depth: int = 20) -> Repo:
    """Clone into `into` and record the checked-out SHA.

    Shallow (depth 20): enough history for per-file git logs. With `sha`
    set, fetches exactly that commit: GitHub refuses
    `git clone --branch <sha>`, but honors shallow fetches of reachable
    SHAs (`allowReachableSHA1InWant`). Fixture repos pin a SHA so evals
    cannot drift; a fetch failure means the pin is no longer reachable
    and the fixture must be updated.
    """
    owner, name = parse_github_url(url)
    if sha is not None:
        _fetch_sha(url, sha, into, depth)
        checked_out = _git(into, "rev-parse", "HEAD")
        return Repo(
            owner=owner,
            name=name,
            default_branch="",  # a SHA checkout is detached
            sha=checked_out,
            root=into,
        )

    subprocess.run(
        [
            "git",
            "clone",
            f"--depth={depth}",
            "--single-branch",
            "--quiet",
            url,
            str(into),
        ],
        check=True,
        capture_output=True,
    )
    sha = _git(into, "rev-parse", "HEAD")
    branch = _git(into, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return Repo(
        owner=owner,
        name=name,
        default_branch=branch.removeprefix("origin/"),
        sha=sha,
        root=into,
    )


def _fetch_sha(url: str, sha: str, into: Path, depth: int) -> None:
    """Fetch a single commit into a fresh repository and check it out."""
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet", str(into)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(into), "remote", "add", "origin", url],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "-C", str(into), "fetch", f"--depth={depth}", "origin", sha],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"could not fetch {url} at {sha!r}: {result.stderr.strip()}")
    subprocess.run(
        ["git", "-C", str(into), "checkout", "--quiet", "FETCH_HEAD"],
        check=True,
        capture_output=True,
    )


def git_log_for(root: Path, path: str, n: int = 20) -> str:
    """`git log` for one file, one line per commit.

    Stored with the index so the git_log tool works offline, against the
    same SHA the chunks are pinned to.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "log",
            f"-n{n}",
            "--date=short",
            "--format=%h|%an|%ad|%s",
            "--",
            path,
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()
