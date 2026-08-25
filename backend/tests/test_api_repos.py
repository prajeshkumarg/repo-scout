"""Browse endpoint tests against the fixture repo. No network, no LLM."""

from fastapi.testclient import TestClient

from api.main import app


def client_for(tool_ctx) -> TestClient:
    return TestClient(app)


def test_list_repos(tool_ctx):
    body = client_for(tool_ctx).get("/repos").json()

    entry = next(r for r in body if r["name"] == "repo")
    assert entry["owner"] == "owner"
    assert entry["sha"] == "sha1"
    assert entry["files"] == 2
    assert entry["chunks"] == 2


def test_tree_lists_indexed_paths(tool_ctx):
    body = client_for(tool_ctx).get("/repos/owner/repo/tree").json()

    assert body == ["src/app.py", "src/nested/util.py"]


def test_file_returns_content_and_line_count(tool_ctx):
    body = (
        client_for(tool_ctx)
        .get("/repos/owner/repo/file", params={"path": "src/nested/util.py"})
        .json()
    )

    assert body["path"] == "src/nested/util.py"
    assert body["content"].startswith("def helper():")
    assert body["lines"] == 2


def test_file_404s_for_a_path_not_at_this_revision(tool_ctx):
    response = client_for(tool_ctx).get(
        "/repos/owner/repo/file", params={"path": "src/ghost.py"}
    )

    assert response.status_code == 404


def test_symbols_scoped_to_a_file_is_the_outline(tool_ctx):
    body = (
        client_for(tool_ctx)
        .get("/repos/owner/repo/symbols", params={"path": "src/app.py"})
        .json()
    )

    assert body == [{"name": "find_me", "kind": "function", "line": 4, "parent": None}]


def test_orientation_needs_no_model_call(tool_ctx):
    body = client_for(tool_ctx).get("/repos/owner/repo/orientation").json()

    assert body["sha"] == "sha1"
    assert body["languages"] == {"python": 2}
    # Key files are ranked by how many definitions they hold.
    assert body["key_files"][0] in {"src/app.py", "src/nested/util.py"}
    # Starter questions are built from real structure, never generic-only.
    assert len(body["starter_questions"]) >= 1
    assert any("run this project" in q for q in body["starter_questions"])


def test_unknown_repo_404s(tool_ctx):
    assert client_for(tool_ctx).get("/repos/nobody/nothing/tree").status_code == 404
