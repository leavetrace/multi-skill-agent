"""Deterministic `LLMClient` for offline tests (WP1 spec §4.5).

Rules are checked in order; the first matching rule with remaining uses answers. Every
call is recorded so tests can assert on prompts, purposes and call counts.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from skillagent.core.language import estimate_tokens, strip_think
from skillagent.llm.structured import complete_structured_with
from skillagent.llm.types import (
    ChatMessage,
    LLMResponse,
    LLMUsage,
    StructuredResult,
    T,
    ToolCall,
    ToolSpec,
)

__all__ = ["FakeLLM", "FakeRule", "RecordedCall"]

Matcher = Callable[[list[ChatMessage], str], bool] | str
Reply = str | list[ToolCall] | Exception | Callable[[list[ChatMessage]], str]


@dataclass
class FakeRule:
    """`match`: predicate `(messages, purpose) -> bool`, or a regex searched in
    `purpose + "\\n" + last user message`. `times=None` means unlimited uses."""

    match: Matcher
    reply: Reply
    times: int | None = None
    used: int = field(default=0, init=False)

    def matches(self, messages: list[ChatMessage], purpose: str) -> bool:
        if self.times is not None and self.used >= self.times:
            return False
        if isinstance(self.match, str):
            return re.search(self.match, f"{purpose}\n{_last_user_content(messages)}") is not None
        return self.match(messages, purpose)


@dataclass(frozen=True)
class RecordedCall:
    purpose: str
    messages: list[ChatMessage]
    kwargs: dict[str, Any]


def _last_user_content(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


class FakeLLM:
    """Scriptable fake. No match and no `default` → AssertionError naming the purpose."""

    model = "fake-llm"

    def __init__(self, rules: list[FakeRule], default: str | None = None) -> None:
        self.rules = rules
        self.default = default
        self.calls: list[RecordedCall] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
        tools: list[ToolSpec] | None = None,
        tool_choice: str | None = None,
        timeout_s: float | None = None,
        purpose: str = "",
    ) -> LLMResponse:
        self.calls.append(
            RecordedCall(
                purpose=purpose,
                messages=[ChatMessage(**m) for m in messages],  # snapshot, not a live view
                kwargs={
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "json_mode": json_mode,
                    "tools": tools,
                    "tool_choice": tool_choice,
                    "timeout_s": timeout_s,
                },
            )
        )
        reply = self._pick_reply(messages, purpose)
        if isinstance(reply, Exception):
            raise reply
        tool_calls: list[ToolCall] = []
        if isinstance(reply, list):
            tool_calls, text = reply, ""
        elif callable(reply):
            text = reply(messages)
        else:
            text = reply
        prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        return LLMResponse(
            text=strip_think(text),
            tool_calls=tool_calls,
            usage=LLMUsage(prompt_tokens=prompt_tokens, completion_tokens=estimate_tokens(text)),
            latency_ms=0.0,
            model=self.model,
            attempts=1,
        )

    async def complete_structured(
        self,
        messages: list[ChatMessage],
        schema: type[T],
        *,
        validation_context: dict[str, Any] | None = None,
        max_repairs: int = 1,
        temperature: float = 0.0,
        max_tokens: int = 512,
        timeout_s: float | None = None,
        purpose: str = "",
    ) -> StructuredResult[T]:
        return await complete_structured_with(
            self.complete,
            messages,
            schema,
            validation_context=validation_context,
            max_repairs=max_repairs,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            purpose=purpose,
        )

    def _pick_reply(self, messages: list[ChatMessage], purpose: str) -> Reply:
        for rule in self.rules:
            if rule.matches(messages, purpose):
                rule.used += 1
                return rule.reply
        if self.default is not None:
            return self.default
        raise AssertionError(f"FakeLLM: no rule matched purpose={purpose!r} and no default set")
