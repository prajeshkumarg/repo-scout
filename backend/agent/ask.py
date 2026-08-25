"""Deep mode end to end: run the loop, validate citations, repair once."""

from __future__ import annotations

import threading
from collections.abc import Callable

from agent.citations import Validation, repair_once, validate_answer
from agent.llm import LLMClient
from agent.loop import SYSTEM_PROMPT, AgentRun, StepRecord, run_agent
from tools.base import ToolContext


def ask_deep(
    question: str,
    ctx: ToolContext,
    client: LLMClient,
    *,
    on_step: Callable[[StepRecord], None] | None = None,
    cancel: threading.Event | None = None,
) -> tuple[AgentRun, Validation]:
    """One deep-mode question: agent run plus post-validated answer."""
    run = run_agent(question, ctx, client, on_step=on_step, cancel=cancel)
    validation = validate_answer(run.answer, ctx.conn, ctx.repo_id, ctx.sha)
    if validation.invalid:
        fixed = repair_once(
            validation.answer, validation.invalid, client, system=SYSTEM_PROMPT
        )
        validation = validate_answer(fixed, ctx.conn, ctx.repo_id, ctx.sha)
        validation.repaired = True
    return run, validation
