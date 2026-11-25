"""Shared parse → validate → repair loop for structured output (ADR-010).

Both `OpenAICompatGateway` and `FakeLLM` delegate here, so the router's repair behaviour
is unit-testable offline with exactly the logic production uses.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from skillagent.core.errors import StructuredOutputError
from skillagent.core.language import extract_json_object
from skillagent.llm.types import ChatMessage, LLMResponse, StructuredResult, T

__all__ = ["REPAIR_TEMPLATE", "complete_structured_with", "summarize_error"]

logger = logging.getLogger("skillagent.llm")

REPAIR_TEMPLATE = (
    "Your previous output was invalid: {error}. "
    "Return ONLY a corrected JSON object that fixes this."
)

CompleteFn = Callable[..., Awaitable[LLMResponse]]

_MAX_ERRORS_SHOWN = 5


def summarize_error(exc: Exception) -> str:
    """One-line, model-readable error: field paths plus messages, capped in length.

    Short and specific beats a full pydantic dump: small models fix one clear sentence far
    more reliably than a wall of JSON.
    """
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors()[:_MAX_ERRORS_SHOWN]:
            loc = ".".join(str(p) for p in err["loc"])
            msg = err["msg"].removeprefix("Value error, ")
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "; ".join(parts)
    if isinstance(exc, json.JSONDecodeError):
        return f"not valid JSON ({exc.msg} at line {exc.lineno} column {exc.colno})"
    return str(exc)


async def complete_structured_with(
    complete: CompleteFn,
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
    """Call `complete(json_mode=True)`, validate into `schema`, repair up to `max_repairs` times.

    Each repair appends the invalid reply and a corrective user message, so the model sees
    its own mistake. Bounded by `max_repairs` to prevent loops on stubborn models.
    """
    conversation = list(messages)
    repair_purpose = f"{purpose}:repair" if purpose else "repair"
    last_text, last_error = "", ""
    for attempt in range(max_repairs + 1):
        response = await complete(
            conversation,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            timeout_s=timeout_s,
            purpose=purpose if attempt == 0 else repair_purpose,
        )
        last_text = response.text
        try:
            data = json.loads(extract_json_object(response.text))
            value = schema.model_validate(data, context=validation_context)
        except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
            last_error = summarize_error(exc)
            if response.finish_reason == "length":
                # A cut-off reply is not a schema mistake; say so, or the model repeats it.
                last_error = (
                    "your reply was cut off at the token limit; return a shorter JSON object "
                    f"({last_error})"
                )
            logger.warning(
                "structured output invalid purpose=%s attempt=%d error=%s",
                purpose,
                attempt + 1,
                last_error,
            )
            conversation += [
                {"role": "assistant", "content": response.text},
                {"role": "user", "content": REPAIR_TEMPLATE.format(error=last_error)},
            ]
            continue
        return StructuredResult[schema](value=value, response=response, repairs=attempt)
    raise StructuredOutputError(raw_text=last_text, errors=last_error)
