"""Worker queue wiring. No network: RQ builds a Queue lazily."""

from worker import jobs
from worker.queue import (
    EMBEDDING_QUEUE,
    INDEXING_QUEUE,
    get_embedding_queue,
    get_indexing_queue,
)


def test_indexing_queue_has_the_expected_name():
    assert get_indexing_queue().name == INDEXING_QUEUE


def test_embedding_queue_is_separate_from_indexing():
    # The split is what lets the worker drain interactive structure
    # passes ahead of the vector backlog; one queue would serialise them.
    assert get_embedding_queue().name == EMBEDDING_QUEUE
    assert EMBEDDING_QUEUE != INDEXING_QUEUE


class _RecordingQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple] = []

    def enqueue(self, func, *args, **kwargs) -> None:
        self.enqueued.append((func, args))


def test_embed_job_reenqueues_itself_while_work_remains(monkeypatch):
    """A batch that embedded something must come back for the next one."""
    queue = _RecordingQueue()
    monkeypatch.setattr(jobs, "get_embedding_queue", lambda: queue)
    monkeypatch.setattr(jobs, "publish_progress", lambda *a, **k: None)
    monkeypatch.setattr(
        jobs, "embed_pending", lambda *a, **k: 100
    )  # a full batch: more to do

    jobs.embed_repo_job(1, "pallets", "click", "abc123")

    assert len(queue.enqueued) == 1
    func, args = queue.enqueued[0]
    assert func is jobs.embed_repo_job
    assert args == (1, "pallets", "click", "abc123")


def test_embed_job_stops_when_backlog_is_clear(monkeypatch):
    """Zero chunks embedded means nothing lacks a vector: stop, or loop forever."""
    queue = _RecordingQueue()
    published: list[tuple] = []
    monkeypatch.setattr(jobs, "get_embedding_queue", lambda: queue)
    monkeypatch.setattr(jobs, "publish_progress", lambda *a, **k: published.append(a))
    monkeypatch.setattr(jobs, "embed_pending", lambda *a, **k: 0)

    jobs.embed_repo_job(1, "pallets", "click", "abc123")

    assert queue.enqueued == []
    assert any(stage == "done" for _, stage, *_ in published)


def test_embed_job_passes_the_batch_cap(monkeypatch):
    """Without the cap the job embeds the whole repo and never yields."""
    seen: dict = {}
    monkeypatch.setattr(jobs, "get_embedding_queue", lambda: _RecordingQueue())
    monkeypatch.setattr(jobs, "publish_progress", lambda *a, **k: None)

    def fake_embed_pending(*args, **kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(jobs, "embed_pending", fake_embed_pending)
    jobs.embed_repo_job(1, "pallets", "click", "abc123")

    assert seen["max_batches"] == jobs.EMBED_BATCHES_PER_JOB
