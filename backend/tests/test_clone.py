"""URL parsing and git-log tests. Cloning itself is exercised by evals."""

import subprocess

import pytest

from ingest.clone import git_log_for, parse_github_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/owner/name", ("owner", "name")),
        ("https://github.com/owner/name.git", ("owner", "name")),
        ("https://github.com/owner/name/", ("owner", "name")),
        ("  https://github.com/a-b/c_d  ", ("a-b", "c_d")),
    ],
)
def test_parse_github_url(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "github.com/owner/name",  # no scheme
        "https://gitlab.com/owner/name",  # not GitHub
        "https://github.com/owner/name/tree/main",  # extra path
        "https://github.com/owner",  # no repo name
        "not a url",
    ],
)
def test_parse_github_url_rejects(url):
    with pytest.raises(ValueError, match="expected a GitHub repo URL"):
        parse_github_url(url)


def test_git_log_for_returns_one_line_per_commit(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    commit = ["-c", "user.name=test", "-c", "user.email=t@t"]
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), *commit, "commit", "-qm", "first"], check=True
    )
    (tmp_path / "a.py").write_text("x = 2\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), *commit, "commit", "-qam", "second"],
        check=True,
    )

    log = git_log_for(tmp_path, "a.py")

    lines = log.splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("|second")
    assert lines[1].endswith("|first")


def test_git_log_for_untracked_file_is_empty(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)

    assert git_log_for(tmp_path, "missing.py") == ""
