"""The only code that talks to an LLM provider (ARCHITECTURE §6, ADR-015).

One thin wrapper over `openai.AsyncOpenAI` gives us explicit control of retries, rate
limiting, JSON mode, tools and `extra_body` across Google AI Studio, Groq and OpenRouter.
Create one gateway per process and share it: the semaphore and RPM window are per instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import openai

from skillagent.config import Settings, mask_secret
from skillagent.core.errors import LLMError, LLMProviderError, LLMRateLimitError, LLMTimeoutError
from skillagent.core.language import strip_think
from skillagent.llm.providers import ProviderProfile, resolve_profile
from skillagent.llm.ratelimit import SlidingWindowRateLimiter
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

__all__ = ["OpenAICompatGateway"]

logger = logging.getLogger("skillagent.llm")

MAX_RETRY_AFTER_S = 60.0
"""A longer `retry-after` usually means a daily quota is gone; fail fast instead of hanging."""

_JSON_MODE_REJECTED = re.compile(r"response_format|json_object|json mode", re.IGNORECASE)
_KEY_LIKE = re.compile(r"\b(?:gsk_|sk-or-v1-|sk-|AIza)[A-Za-z0-9_\-]{8,}")


class OpenAICompatGateway:
    """`LLMClient` for any OpenAI-compatible chat-completions endpoint.

    `client`, `clock`, `sleep` and `rng` are injection points for tests; production code
    passes only `settings` (and optionally a measured `profile`).
    """

    def __init__(
        self,
        settings: Settings,
        profile: ProviderProfile | None = None,
        *,
        client: Any = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.settings = settings
        self.profile = profile or resolve_profile(settings)
        self.model = self.profile.default_model
        self._secret: str | None = None
        if client is None:
            self._secret = settings.api_key().get_secret_value()
            client = openai.AsyncOpenAI(
                base_url=self.profile.base_url, api_key=self._secret, max_retries=0
            )
        self._client = client
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
        self._limiter = SlidingWindowRateLimiter(settings.llm_rpm, 60.0, clock=clock, sleep=sleep)
        self._json_mode_supported = self.profile.supports_json_mode

    async def aclose(self) -> None:
        await self._client.close()

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
        start = self._clock()
        request = self._build_request(
            messages, temperature, max_tokens, json_mode, tools, tool_choice
        )
        timeout = timeout_s or self.settings.llm_timeout_s
        try:
            completion, attempts = await self._send(request, timeout, purpose)
        except LLMProviderError as exc:
            if not self._is_json_mode_rejection(request, exc):
                raise
            self._json_mode_supported = False
            logger.warning(
                "provider %s rejected response_format; JSON mode disabled for this gateway",
                self.profile.name,
            )
            del request["response_format"]
            completion, retried = await self._send(request, timeout, purpose)
            attempts = 1 + retried
        response = self._parse(
            completion, latency_ms=(self._clock() - start) * 1000, attempts=attempts
        )
        logger.info(
            "llm call purpose=%s model=%s attempts=%d latency_ms=%.0f prompt_tokens=%s "
            "completion_tokens=%s",
            purpose,
            response.model,
            response.attempts,
            response.latency_ms,
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
        )
        return response

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

    # --- request building ---------------------------------------------------------------

    def _build_request(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[ToolSpec] | None,
        tool_choice: str | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode and self._json_mode_supported:
            request["response_format"] = {"type": "json_object"}
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        if tool_choice is not None:
            request["tool_choice"] = _map_tool_choice(tool_choice, tools)
        if self.profile.extra_body:
            request["extra_body"] = dict(self.profile.extra_body)
        return request

    def _prepare_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Copy messages; merge system prompts into the first user turn if unsupported."""
        prepared = [dict(m) for m in messages]
        if self.profile.supports_system_role:
            return prepared
        system = "\n\n".join(m.get("content", "") for m in prepared if m.get("role") == "system")
        rest = [m for m in prepared if m.get("role") != "system"]
        if not system:
            return rest
        for message in rest:
            if message.get("role") == "user":
                message["content"] = (
                    f"[Instructions]\n{system}\n\n[User]\n{message.get('content', '')}"
                )
                return rest
        return [{"role": "user", "content": f"[Instructions]\n{system}"}, *rest]

    def _is_json_mode_rejection(self, request: dict[str, Any], exc: LLMProviderError) -> bool:
        return (
            "response_format" in request
            and exc.status_code == 400
            and _JSON_MODE_REJECTED.search(str(exc)) is not None
        )

    # --- sending with retries -----------------------------------------------------------

    async def _send(
        self, request: dict[str, Any], attempt_timeout_s: float, purpose: str
    ) -> tuple[Any, int]:
        """Returns (completion, attempts). Retries 429/5xx/timeouts/connection errors."""
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._semaphore:
                    await self._limiter.acquire()
                    completion = await asyncio.wait_for(
                        self._client.chat.completions.create(**request), attempt_timeout_s
                    )
                return completion, attempt
            except (TimeoutError, openai.APIError) as exc:
                error, retryable, retry_after = self._classify(exc, attempt_timeout_s)
                if not retryable or attempt > self.settings.llm_max_retries:
                    raise error from exc
                if retry_after is not None and retry_after > MAX_RETRY_AFTER_S:
                    raise error from exc
                delay = retry_after if retry_after is not None else self._backoff(attempt)
                logger.warning(
                    "llm retry purpose=%s attempt=%d error=%s delay_s=%.2f",
                    purpose,
                    attempt,
                    type(error).__name__,
                    delay,
                )
                await self._sleep(delay)

    def _backoff(self, attempt: int) -> float:
        """1 s, 2 s, 4 s… with ±25% jitter so parallel callers don't retry in lockstep."""
        return float(2 ** (attempt - 1)) * (1 + (self._rng() * 2 - 1) * 0.25)

    def _classify(self, exc: BaseException, timeout: float) -> tuple[LLMError, bool, float | None]:
        """Map an exception to (our error, retryable?, retry-after seconds)."""
        if isinstance(exc, TimeoutError | openai.APITimeoutError):
            return LLMTimeoutError(f"LLM call timed out after {timeout:g}s"), True, None
        if isinstance(exc, openai.APIConnectionError):
            return LLMProviderError(f"connection error: {self._redact(str(exc))}"), True, None
        if isinstance(exc, openai.APIStatusError):
            status = exc.status_code
            message = self._redact(exc.message)
            retry_after = _retry_after_seconds(exc.response.headers)
            if status == 429:
                hint = f" (provider asks to wait {retry_after:g}s)" if retry_after else ""
                return (
                    LLMRateLimitError(f"rate limited by provider{hint}: {message}"),
                    True,
                    retry_after,
                )
            error = LLMProviderError(f"provider error {status}: {message}", status_code=status)
            return error, status >= 500, retry_after
        return LLMProviderError(f"provider error: {self._redact(str(exc))}"), False, None

    def _redact(self, text: str) -> str:
        if self._secret:
            text = text.replace(self._secret, mask_secret(self._secret))
        return _KEY_LIKE.sub(lambda m: mask_secret(m.group(0)), text)

    # --- response parsing ---------------------------------------------------------------

    def _parse(self, completion: Any, *, latency_ms: float, attempts: int) -> LLMResponse:
        if not completion.choices:
            raise LLMProviderError("provider returned no choices")
        message = completion.choices[0].message
        tool_calls = [
            _parse_tool_call(tc)
            for tc in (message.tool_calls or [])
            if getattr(tc, "function", None)
        ]
        usage = completion.usage
        return LLMResponse(
            text=strip_think(message.content or ""),
            tool_calls=tool_calls,
            usage=LLMUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
            ),
            latency_ms=latency_ms,
            model=completion.model or self.model,
            attempts=attempts,
        )


def _map_tool_choice(tool_choice: str, tools: list[ToolSpec] | None) -> str | dict[str, Any]:
    """`"required"`/`"auto"`/`"none"` pass through; any other string forces that tool."""
    if tool_choice in ("required", "auto", "none"):
        return tool_choice
    if not tools or tool_choice not in {t.name for t in tools}:
        raise ValueError(f"tool_choice={tool_choice!r} does not name one of the provided tools")
    return {"type": "function", "function": {"name": tool_choice}}


def _parse_tool_call(tool_call: Any) -> ToolCall:
    raw = tool_call.function.arguments or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    return ToolCall(
        id=tool_call.id or "",
        name=tool_call.function.name,
        arguments=parsed if isinstance(parsed, dict) else {},
        raw_arguments=raw,
    )


def _retry_after_seconds(headers: Any) -> float | None:
    """Seconds from `retry-after-ms` or numeric `retry-after`; HTTP-date form is ignored."""
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            return max(0.0, float(value) * scale)
        except ValueError:
            continue
    return None
