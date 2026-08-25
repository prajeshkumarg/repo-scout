"""Agent loop tests with a scripted fake model. No network, no real LLM.

The fake returns a fixed sequence of turns: tool calls first, then a
final answer. The loop's budgets get small values so they trip fast.
"""

import threading

from agent.llm import ToolCall, Turn
from agent.loop import run_agent


class ScriptedClient:
    """Pops one scripted turn per generate() call and records messages."""

    def __init__(self, turns: list[Turn]) -> None:
        self.turns = turns
        self.calls: list[tuple[list[dict], list[dict], str]] = []

    def generate(self, messages: list[dict], tools: list[dict], system: str) -> Turn:
        self.calls.append((messages, tools, system))
        if not self.turns:
            return Turn(text="(no scripted turns left)")
        return self.turns.pop(0)


def search_call(call_id: str = "c1") -> ToolCall:
    return ToolCall(call_id=call_id, name="search_code", arguments={"query": "find me"})


def read_call(call_id: str = "c2") -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name="read_file",
        arguments={"path": "src/app.py", "start": 1, "end": 2},
    )


def test_loop_executes_tools_and_returns_answer(tool_ctx):
    client = ScriptedClient(
        [
            Turn(tool_calls=[search_call()]),
            Turn(tool_calls=[read_call()]),
            Turn(text="The session store is in src/app.py:1-2.", tokens=42),
        ]
    )

    run = run_agent("where is the session store", tool_ctx, client)

    assert run.answer.startswith("The session store")
    assert run.finished
    assert [s.tool for s in run.steps] == ["search_code", "read_file"]
    # search_code with fake embeddings can surface both fixture chunks;
    # read_file must add the target file regardless.
    assert "src/app.py" in run.files_read
    assert run.tokens == 42
    # All tool results from one turn land in ONE message.
    last_results_message = [m for m in client.calls[-2][0] if "tool_results" in m][-1]
    assert len(last_results_message["tool_results"]) == 1


def test_loop_batches_parallel_tool_results_in_one_message(tool_ctx):
    client = ScriptedClient(
        [
            Turn(tool_calls=[search_call("a"), read_call("b")]),
            Turn(text="done: src/app.py:1-2"),
        ]
    )

    run = run_agent("q", tool_ctx, client)

    assert len(run.steps) == 2
    results_messages = [m for m in client.calls[1][0] if "tool_results" in m]
    assert len(results_messages) == 1
    assert len(results_messages[0]["tool_results"]) == 2


def test_loop_step_budget_gets_one_final_turn(tool_ctx):
    client = ScriptedClient(
        [Turn(tool_calls=[search_call()])] * 3
        + [Turn(text="final: src/app.py:1-2", tokens=10)]
    )

    run = run_agent("q", tool_ctx, client, max_steps=3)

    assert not run.finished
    assert run.answer == "final: src/app.py:1-2"
    assert len(run.steps) == 3
    # The final turn was nudged with the budget message.
    assert "budget was reached" in client.calls[-1][0][-1]["text"]


def test_loop_token_budget_gets_one_final_turn(tool_ctx):
    client = ScriptedClient(
        [
            Turn(tool_calls=[search_call()], tokens=1000),
            Turn(text="final answer", tokens=5),
        ]
    )

    run = run_agent("q", tool_ctx, client, max_tokens=500)

    assert not run.finished
    assert run.answer == "final answer"


def test_loop_cancellation_stops_between_steps(tool_ctx):
    client = ScriptedClient(
        [Turn(tool_calls=[search_call()]), Turn(tool_calls=[search_call()])]
    )
    cancel = threading.Event()

    def cancel_after_first_generate(*args, **kwargs):
        cancel.set()
        return client.turns.pop(0)

    client.generate = cancel_after_first_generate  # type: ignore[method-assign]

    run = run_agent("q", tool_ctx, client, cancel=cancel)

    assert not run.finished
    assert run.answer == ""
    assert len(run.steps) == 1


def test_loop_unknown_tool_is_an_error_result(tool_ctx):
    client = ScriptedClient(
        [
            Turn(tool_calls=[ToolCall(call_id="x", name="vanish", arguments={})]),
            Turn(text="could not find anything"),
        ]
    )

    run = run_agent("q", tool_ctx, client)

    assert run.steps[0].summary.startswith("error: unknown tool")


def test_gemini_client_retries_on_429():
    from google.genai import types
    from google.genai.errors import ClientError

    from agent.llm import GeminiClient

    class FlakyModels:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise ClientError(
                    429,
                    {
                        "error": {
                            "code": 429,
                            "message": "quota exceeded. Please retry in 0.1s",
                            "status": "RESOURCE_EXHAUSTED",
                        }
                    },
                )
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model",
                            parts=[types.Part.from_text(text="ok")],
                        )
                    )
                ]
            )

    class Wrapper:
        def __init__(self, models: FlakyModels) -> None:
            self.models = models

    flaky = FlakyModels()
    client = GeminiClient("key", "model", client=Wrapper(flaky))

    turn = client.generate([{"role": "user", "text": "hi"}], tools=[], system="sys")

    assert turn.text == "ok"
    assert flaky.calls == 3
