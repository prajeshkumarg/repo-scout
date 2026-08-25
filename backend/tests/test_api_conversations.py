"""Conversation endpoint tests with a scripted fake model. No network."""

import json

import pytest
from fastapi.testclient import TestClient

from agent.llm import ToolCall, Turn
from api import conversations
from api.main import app


class ScriptedClient:
    """Returns a fixed tool sequence, then a final answer."""

    def __init__(self, turns: list[Turn]) -> None:
        self.turns = turns

    def generate(self, messages, tools, system) -> Turn:
        return self.turns.pop(0) if self.turns else Turn(text="(exhausted)")


def frames(response) -> list[dict]:
    """Parse an SSE body into event dicts."""
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
def client(tool_ctx, monkeypatch):
    # The endpoint builds its own context; point it at the fixture repo
    # and the scripted model instead of Gemini.
    scripted = ScriptedClient(
        [
            Turn(
                tool_calls=[
                    ToolCall(
                        call_id="c1",
                        name="read_file",
                        arguments={"path": "src/app.py", "start": 1, "end": 2},
                    )
                ]
            ),
            Turn(text="The store is in src/app.py:1-2.", tokens=99),
        ]
    )
    monkeypatch.setattr(conversations, "GeminiClient", lambda *a, **k: scripted)
    monkeypatch.setattr(conversations, "LocalEmbedder", lambda **k: tool_ctx.embedder)
    settings = conversations.get_settings()
    monkeypatch.setattr(settings, "google_api_key", "test-key")
    yield TestClient(app)


def test_create_conversation_requires_an_indexed_repo(client):
    ok = client.post("/conversations", json={"repo": "owner/repo"})
    assert ok.status_code == 201
    assert ok.json()["sha"] == "sha1"

    missing = client.post("/conversations", json={"repo": "nobody/nothing"})
    assert missing.status_code == 404


def test_ask_streams_the_spec_event_sequence(client):
    conversation_id = client.post("/conversations", json={"repo": "owner/repo"}).json()[
        "conversation_id"
    ]

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": "where is the store"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = frames(response)
    types = [e["type"] for e in events]

    # The spec's contract: steps, then answer text, citations, then done.
    assert types[0] == "step_start"
    assert types[1] == "step_result"
    assert "token" in types
    assert "citation" in types
    assert types[-1] == "done"

    start = events[0]
    assert start["tool"] == "read_file"
    assert start["step"] == 1

    citation = next(e for e in events if e["type"] == "citation")
    assert citation == {
        "type": "citation",
        "path": "src/app.py",
        "start": 1,
        "end": 2,
    }

    done = events[-1]
    assert done["steps"] == 1
    assert done["tokens"] == 99


def test_ask_persists_messages_and_the_agent_run(client, tool_ctx):
    conversation_id = client.post("/conversations", json={"repo": "owner/repo"}).json()[
        "conversation_id"
    ]

    client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": "where is the store"},
    )

    rows = tool_ctx.conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    ).fetchall()
    assert [r[0] for r in rows] == ["user", "assistant"]
    assert rows[0][1] == "where is the store"

    run = tool_ctx.conn.execute(
        """
        SELECT mode, tokens, finished, message_id FROM agent_runs
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert run[0] == "deep"
    assert run[1] == 99
    assert run[2] is True
    assert run[3] is not None  # linked to the assistant message


def test_ask_404s_for_an_unknown_conversation(client):
    response = client.post("/conversations/999999/messages", json={"question": "hi"})
    assert response.status_code == 404
