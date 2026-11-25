"""Provider-agnostic LLM interface (CONTRACTS §4).

Everything above the gateway (router, skills, doctor) depends only on `LLMClient`, which
is why `FakeLLM` can stand in for a real provider in every offline test.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, Protocol, TypedDict, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

__all__ = [
    "ChatMessage",
    "LLMClient",
    "LLMResponse",
    "LLMUsage",
    "StructuredResult",
    "T",
    "ToolCall",
    "ToolSpec",
]


class ChatMessage(TypedDict, total=False):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str
    tool_calls: list[dict[str, Any]]


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]  # parsed; {} if unparsable
    raw_arguments: str


class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMResponse(BaseModel):
    text: str  # <think> blocks already stripped
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: float
    model: str
    attempts: int  # 1 + retries
    finish_reason: str | None = None  # "stop" | "length" | "tool_calls" | provider-specific


T = TypeVar("T", bound=BaseModel)


class StructuredResult(BaseModel, Generic[T]):  # noqa: UP046 - mirrors CONTRACTS §4 verbatim
    value: T
    response: LLMResponse
    repairs: int


@runtime_checkable
class LLMClient(Protocol):
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
    ) -> LLMResponse: ...

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
    ) -> StructuredResult[T]: ...
