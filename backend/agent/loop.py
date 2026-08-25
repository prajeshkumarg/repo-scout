"""The agent loop: budgeted tool use (rules/agent.md).

Budgets are enforced here, in code, never suggested in a prompt:
steps, tokens, wall clock, per-tool timeout. When a budget trips the
agent gets one final turn to answer with what it has. Cancellation is a
threading.Event checked between steps.

All tool results from one model turn go back in a single message, so
the model learns to expect parallel results together.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path

from agent.llm import LLMClient, Turn
from tools.base import ToolContext, ToolResult, error_result
from tools.registry import TOOLS_BY_NAME

logger = logging.getLogger(__name__)

MAX_STEPS = 20
MAX_TOKENS = 120_000
TOOL_TIMEOUT_SECONDS = 20.0
RUN_TIMEOUT_SECONDS = 180.0

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()

_FINAL_TURN_NUDGE = (
    "A budget was reached. Answer now, with citations for every claim, "
    "using only what the tools have shown you."
)


@dataclass
class StepRecord:
    """One executed tool call, for the trace and agent_runs."""

    tool: str
    args: dict
    summary: str
    ms: int


@dataclass
class AgentRun:
    """Everything one deep-mode run produces."""

    answer: str
    steps: list[StepRecord] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    finished: bool = False  # False when a budget tripped or cancelled


def run_agent(
    question: str,
    ctx: ToolContext,
    client: LLMClient,
    *,
    max_steps: int = MAX_STEPS,
    max_tokens: int = MAX_TOKENS,
    tool_timeout: float = TOOL_TIMEOUT_SECONDS,
    run_timeout: float = RUN_TIMEOUT_SECONDS,
    cancel: threading.Event | None = None,
    on_step: Callable[[StepRecord], None] | None = None,
) -> AgentRun:
    """Run the loop and return the agent's answer with its trace.

    `on_step` fires as each tool completes, so a CLI or stream can show
    the trace live instead of after the run.
    """
    started = time.monotonic()
    messages: list[dict] = [
        {"role": "user", "text": question},
    ]
    tool_decls = [spec.declaration for spec in TOOLS_BY_NAME.values()]
    tokens = 0
    steps: list[StepRecord] = []
    files_read: list[str] = []
    finished = False

    def final_turn(reason: str) -> Turn:
        messages.append({"role": "user", "text": _FINAL_TURN_NUDGE})
        turn = client.generate(messages, tool_decls, system=SYSTEM_PROMPT)
        logger.info("final turn (%s): %d tokens", reason, turn.tokens)
        return turn

    answer = ""
    for _ in range(max_steps):
        if cancel is not None and cancel.is_set():
            logger.info("run cancelled after %d steps", len(steps))
            return AgentRun(
                answer="",
                steps=steps,
                files_read=files_read,
                tokens=tokens,
                latency_ms=_elapsed(started),
                finished=False,
            )
        if time.monotonic() - started > run_timeout:
            turn = final_turn("wall clock")
            tokens += turn.tokens
            answer = turn.text
            break
        if tokens >= max_tokens:
            turn = final_turn("token budget")
            tokens += turn.tokens
            answer = turn.text
            break

        turn = client.generate(messages, tool_decls, system=SYSTEM_PROMPT)
        tokens += turn.tokens
        if not turn.tool_calls:
            answer = turn.text
            finished = True
            break

        messages.append(
            {
                "role": "model",
                "tool_calls": [
                    {
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in turn.tool_calls
                ],
                # Opaque provider payload, handed back unchanged: some
                # models require their own parts echoed verbatim.
                "raw": turn.raw_parts,
            }
        )
        results = []
        for call in turn.tool_calls:
            t0 = time.monotonic()
            spec = TOOLS_BY_NAME.get(call.name)
            if spec is None:
                result = error_result(f"unknown tool {call.name!r}")
            else:
                result = _run_with_timeout(
                    spec.function, ctx, call.arguments, tool_timeout
                )
            step = StepRecord(
                tool=call.name,
                args=call.arguments,
                summary=result.summary,
                ms=_elapsed(t0),
            )
            steps.append(step)
            if on_step is not None:
                on_step(step)
            files_read.extend(
                path for path in result.files_read if path not in files_read
            )
            results.append(
                {
                    "call_id": call.call_id,
                    "name": call.name,
                    "content": result.content,
                }
            )
        messages.append({"role": "user", "tool_results": results})
    else:
        turn = final_turn("step budget")
        tokens += turn.tokens
        answer = turn.text

    return AgentRun(
        answer=answer,
        steps=steps,
        files_read=files_read,
        tokens=tokens,
        latency_ms=_elapsed(started),
        finished=finished,
    )


def _run_with_timeout(
    function: Callable[..., ToolResult],
    ctx: ToolContext,
    arguments: dict,
    timeout: float,
) -> ToolResult:
    """Run a tool with a hard timeout.

    Note: an abandoned thread may still finish later; the connection is
    handed to one tool at a time and in-DB tools are milliseconds, so the
    timeout exists for the spec's contract rather than for real risk.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(function, ctx, **arguments)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            return error_result(f"tool timed out after {timeout:.0f}s")
        except TypeError as exc:
            # Bad arguments from the model are an error result, not a crash.
            return error_result(f"bad arguments: {exc}")


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
