"""Index endpoint tests. No worker, no network: the queue is faked."""

import json

import pytest
from fastapi.testclient import TestClient

from api import indexing
from api.events import Done, ErrorEvent, Progress, sse
from api.main import app
from db.conn import connect
from db.schema import ensure_schema


def _postgres_available() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
    except Exception:  # probing; any failure means "not available"
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="local Postgres not reachable"
)


class FakeQueue:
    """Records enqueued jobs instead of running them."""

    def __init__(self) -> None:
        self.jobs = []

    def enqueue(self, func, *args, **kwargs):
        self.jobs.append((func.__name__, args))


@pytest.fixture
def client(monkeypatch):
    queue = FakeQueue()
    monkeypatch.setattr(indexing, "get_indexing_queue", lambda: queue)
    with connect() as conn:
        conn.autocommit = True
        ensure_schema(conn)
    test_client = TestClient(app)
    test_client.queue = queue
    yield test_client
    with connect() as conn:
        conn.autocommit = True
        conn.execute("DELETE FROM index_runs")


def test_index_enqueues_a_job_and_returns_the_run(client):
    response = client.post("/index", json={"url": "https://github.com/owner/name"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["events_url"] == f"/index/{body['run_id']}/events"
    # The handler enqueues; it never indexes inline.
    assert client.queue.jobs[0][0] == "index_repo_job"


def test_index_rejects_a_non_github_url(client):
    response = client.post("/index", json={"url": "https://gitlab.com/a/b"})

    assert response.status_code == 400
    assert "GitHub repo URL" in response.json()["detail"]


def test_events_404_for_an_unknown_run(client):
    response = client.get("/index/999999/events")

    assert response.status_code == 404


def test_sse_frames_match_the_spec_contract():
    # The wire format is `data: {json}\n\n`, one event per frame.
    frame = sse(Progress(stage="clone", message="done"))
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert json.loads(frame[len("data: ") :]) == {
        "type": "progress",
        "stage": "clone",
        "message": "done",
        "percent": None,
    }

    done = json.loads(sse(Done(steps=7, tokens=41200, ms=9400))[len("data: ") :])
    assert done["type"] == "done"
    assert done["cost_usd"] == 0.0

    error = json.loads(
        sse(ErrorEvent(code="boom", message="bad", retryable=False))[len("data: ") :]
    )
    assert error == {
        "type": "error",
        "code": "boom",
        "message": "bad",
        "retryable": False,
    }
