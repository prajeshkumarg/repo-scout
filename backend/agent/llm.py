"""LLM client for the agent loop.

The loop speaks a small provider-neutral message protocol; this module
translates it to the Gemini API. Unit tests use scripted fakes instead
of a real model (testing rules: never call a real model in tests).

Message protocol (list of dicts):
- {"role": "user" | "model", "text": str}
- {"role": "model", "tool_calls": [{"call_id", "name", "arguments"}]}
- {"role": "user", "tool_results": [{"call_id", "name", "content"}]}
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger(__name__)

_RETRY_HINT = re.compile(r"retry in ([\d.]+)s")
# A per-day quota cannot recover by waiting a few seconds; retrying it
# just spends more of the quota that is already gone.
_DAILY_QUOTA = re.compile(r"PerDay", re.IGNORECASE)


class _Models(Protocol):
    """The slice of the genai client the wrapper uses."""

    def generate_content(self, **kwargs: object) -> object: ...


class _GenaiClient(Protocol):
    models: _Models


@dataclass
class ToolCall:
    """A tool the model asked to run."""

    call_id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    """One model response: text and/or tool calls, plus token usage.

    `raw_parts` is the provider's own representation of this turn. The
    loop treats it as opaque and hands it back unchanged; Gemini needs
    it because thinking models require their thought_signature echoed
    verbatim on the next request, and rebuilding parts from our neutral
    protocol drops it.
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int = 0
    raw_parts: object | None = None


class LLMClient(Protocol):
    """What the agent loop needs from a model."""

    def generate(
        self, messages: list[dict], tools: list[dict], system: str
    ) -> Turn: ...


class GeminiClient:
    """Gemini with function calling, via google-genai."""

    def __init__(
        self,
        api_key: str,
        model: str,
        max_retries: int = 5,
        client: _GenaiClient | None = None,
    ) -> None:
        self._client = client if client is not None else genai.Client(api_key=api_key)
        self._model = model
        self._max_retries = max_retries

    def generate(self, messages: list[dict], tools: list[dict], system: str) -> Turn:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=tools)] if tools else None,
        )
        for attempt in range(self._max_retries):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=[_to_content(message) for message in messages],
                    config=config,
                )
                break
            except APIError as exc:
                if attempt == self._max_retries - 1 or _DAILY_QUOTA.search(str(exc)):
                    raise
                match = _RETRY_HINT.search(str(exc))
                hint = float(match.group(1)) if match else 0.0
                delay = max(2**attempt, hint)
                logger.warning(
                    "agent LLM request failed (%s); retrying in %.1fs", exc, delay
                )
                time.sleep(delay)
        turn = Turn()
        if response.usage_metadata is not None:
            turn.tokens = response.usage_metadata.total_token_count
        candidates = response.candidates
        if not candidates:
            return turn
        turn.raw_parts = candidates[0].content.parts
        for part in candidates[0].content.parts:
            if part.text:
                turn.text += part.text
            elif part.function_call is not None:
                call = part.function_call
                turn.tool_calls.append(
                    ToolCall(
                        call_id=call.id,
                        name=call.name,
                        arguments=dict(call.args) if call.args else {},
                    )
                )
        return turn


def _to_content(message: dict) -> types.Content:
    role = "model" if message["role"] == "model" else "user"
    if "text" in message:
        return types.Content(
            role=role, parts=[types.Part.from_text(text=message["text"])]
        )
    if "tool_calls" in message:
        # Echo the model's own parts when we have them: thinking models
        # reject a tool-call turn whose thought_signature went missing.
        raw = message.get("raw")
        if raw is not None:
            return types.Content(role="model", parts=raw)
        parts = [
            types.Part.from_function_call(name=call["name"], args=call["arguments"])
            for call in message["tool_calls"]
        ]
        return types.Content(role="model", parts=parts)
    # tool_results: all results land in ONE message so the model learns
    # to expect parallel results together.
    parts = [
        types.Part.from_function_response(
            name=result["name"], response={"result": result["content"]}
        )
        for result in message["tool_results"]
    ]
    return types.Content(role="user", parts=parts)
