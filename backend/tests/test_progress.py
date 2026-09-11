"""Progress reporting: the embedder's batch counts must reach the UI."""

import json

from api.events import Progress, sse
from embedding import LocalEmbedder


class FakeModel:
    def embed(self, documents):
        import numpy as np

        return [np.full(8, 0.1) for _ in documents]


def test_embedder_reports_progress_per_batch():
    embedder = LocalEmbedder(model_name="unused", batch_size=100, model=FakeModel())
    seen: list[tuple[int, int]] = []

    embedder.embed_documents(["x"] * 250, on_progress=lambda d, t: seen.append((d, t)))

    # One callback per batch, counting up to the total.
    assert seen == [(100, 250), (200, 250), (250, 250)]


def test_embedder_without_callback_still_works():
    embedder = LocalEmbedder(model_name="unused", batch_size=2, model=FakeModel())

    assert len(embedder.embed_documents(["a", "b", "c"])) == 3


def test_progress_event_carries_percent_on_the_wire():
    frame = sse(Progress(stage="embed", message="100 of 250", percent=40))

    assert json.loads(frame[len("data: ") :]) == {
        "type": "progress",
        "stage": "embed",
        "message": "100 of 250",
        "percent": 40,
    }


def test_publish_progress_includes_percent(monkeypatch):
    from worker import jobs

    published: list[str] = []

    class FakeRedis:
        def publish(self, channel, payload):
            published.append(payload)

    monkeypatch.setattr(jobs, "get_redis", lambda: FakeRedis())
    jobs.publish_progress(1, "embed", "100 of 250", 40)

    assert json.loads(published[0])["percent"] == 40


def test_sse_stream_preserves_percent_from_redis(monkeypatch):
    """The handler must pass percent through, not just accept it.

    This is a regression test: the field was declared on the event and
    published by the worker, but the stream built Progress without it,
    so every bar silently rendered as indeterminate.
    """
    import asyncio
    import json as json_module

    from api import indexing

    class FakePubSub:
        def __init__(self):
            self.sent = False

        def subscribe(self, channel):
            pass

        def get_message(self, ignore_subscribe_messages, timeout):
            if self.sent:
                return None
            self.sent = True
            return {
                "data": json_module.dumps(
                    {"stage": "embed", "message": "100 of 578", "percent": 17}
                )
            }

        def close(self):
            pass

    class FakeRedis:
        def pubsub(self):
            return FakePubSub()

    monkeypatch.setattr(indexing, "get_redis", lambda: FakeRedis())
    # Terminal state with no embedding backlog, so the stream closes.
    monkeypatch.setattr(
        indexing, "_run_state", lambda run_id: ("done", None, {"stage_ms": {}}, 0)
    )

    async def collect():
        return [frame async for frame in indexing._events(1)]

    frames = [json.loads(f[len("data: ") :]) for f in asyncio.run(collect())]
    progress = next(f for f in frames if f["type"] == "progress")
    assert progress["percent"] == 17, "percent was dropped between Redis and SSE"


def test_silent_stream_emits_heartbeats(monkeypatch):
    """A quiet stream must keep bytes flowing or proxies cut it.

    Heroku's router gives up after 55s of silence, nginx after 60s by
    default. Embedding a batch reports nothing until it finishes, and an
    agent waiting out a rate limit can be quiet for minutes.
    """
    import asyncio

    from api import events as events_module
    from api import indexing

    # Heartbeat immediately rather than making the test wait 20 seconds.
    monkeypatch.setattr(indexing, "HEARTBEAT_SECONDS", -1)

    class SilentPubSub:
        def subscribe(self, channel):
            pass

        def get_message(self, ignore_subscribe_messages, timeout):
            return None  # nothing ever arrives

        def close(self):
            pass

    class FakeRedis:
        def pubsub(self):
            return SilentPubSub()

    states = iter([("running", None, None, 5), ("done", None, {"stage_ms": {}}, 0)])
    monkeypatch.setattr(indexing, "get_redis", lambda: FakeRedis())
    monkeypatch.setattr(indexing, "_run_state", lambda run_id: next(states))

    async def collect():
        return [frame async for frame in indexing._events(1)]

    frames = asyncio.run(collect())

    assert events_module.heartbeat() in frames, "a silent stream sent nothing"
    # The heartbeat is a comment, so a client parsing data: lines ignores it.
    assert events_module.heartbeat().startswith(":")
    assert any('"type": "done"' in f for f in frames)
