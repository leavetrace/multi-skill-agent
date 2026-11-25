"""Calculator runner: direct path → LLM tool call → exact evaluation → deterministic text.

The model's job is translation (language → expression), never arithmetic: whatever it
writes in labels, the numbers in the answer come from `evaluator.evaluate`. Pure
expressions skip the model entirely, and every LLM step has a bounded fallback so weak
tool calling on a free endpoint degrades to JSON mode instead of failing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from skillagent.config import Settings
from skillagent.core.errors import ConfigError, LLMError, LLMProviderError, StructuredOutputError
from skillagent.core.types import SkillInput, SkillOutput
from skillagent.llm.providers import resolve_profile
from skillagent.llm.types import ChatMessage
from skillagent.skills.base import SkillBudget, SkillContext
from skillagent.skills.calculator.evaluator import CalculatorError, CalcValue, evaluate
from skillagent.skills.calculator.formatting import (
    format_error_line,
    format_result_line,
    render_number,
)
from skillagent.skills.calculator.normalize import (
    MAX_DIRECT_TEXT_CHARS,
    looks_like_expression,
    strip_cues,
    to_expression,
)
from skillagent.skills.calculator.tool import (
    EVALUATE_TOOL,
    Calculation,
    CalculationPlan,
    parse_response,
)

__all__ = ["BUDGET", "PROMPT_NAME", "PURPOSE", "run"]

logger = logging.getLogger("skillagent.skills.calculator")

BUDGET = SkillBudget(max_input_tokens=800, max_output_tokens=300, timeout_s=20, temperature=0.0)
PROMPT_NAME = "calculator"
PURPOSE = "skill:calculator"
_REPAIRABLE = frozenset({"syntax", "unsupported"})

_JSON_INSTRUCTION = (
    "Tool calling is not available for this reply. Return ONLY a JSON object with the "
    'arguments you would pass to evaluate: {"calculations": [{"expression": "...", '
    '"label": "..."}]} (an empty list if there is nothing to compute).'
)
_DELIMITER_TAG = re.compile(r"</?\s*(?:request|task|previous_result)\s*>", re.IGNORECASE)

_NOT_MATH = {
    "en": (
        "This doesn't look like something I can calculate. Please give me an arithmetic "
        "expression or a numeric question, for example: 15% of 2,480."
    ),
    "fa": (
        "این درخواست محاسبه‌ای نیست که بتوانم انجام دهم. لطفاً یک عبارت ریاضی یا پرسش عددی "
        "بنویسید؛ مثلاً: ۱۵ درصدِ ۲۴۸۰."
    ),
}
_UNPARSEABLE = {
    "en": (
        "I couldn't turn this request into a valid calculation. Please write it as an "
        "arithmetic expression, for example: 2480 * 15 / 100."
    ),
    "fa": (
        "نتوانستم این درخواست را به یک محاسبهٔ معتبر تبدیل کنم. لطفاً آن را به‌صورت یک "
        "عبارت ریاضی بنویسید؛ مثلاً: 2480 * 15 / 100."
    ),
}


@dataclass
class _Item:
    """One calculation moving through evaluate → (repair) → format."""

    expression: str
    label: str
    value: CalcValue | None = None
    error: CalculatorError | None = None

    @property
    def needs_repair(self) -> bool:
        return self.error is not None and self.error.code in _REPAIRABLE

    def meta(self) -> dict[str, Any]:
        rendered = render_number(self.value) if self.value is not None else None
        return {
            "expression": self.expression,
            "label": self.label,
            "value": rendered.text if rendered else None,
            "exact": rendered.exact if rendered else None,
            "error": self.error.code if self.error else None,
        }


@dataclass
class _Run:
    path: str
    llm_calls: int = 0
    repairs: int = 0
    prompt_version: int | None = None


async def run(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
    lang = "fa" if inp.response_language == "fa" else "en"
    direct = _direct_expression(inp)
    if direct is not None:
        return _output([_evaluate(direct, "")], lang, _Run(path="direct"))

    prompt = ctx.prompts.load(PROMPT_NAME)
    state = _Run(path="tool", prompt_version=prompt.version)
    messages: list[ChatMessage] = [
        {"role": "system", "content": prompt.render()},
        {"role": "user", "content": _user_message(inp)},
    ]
    calculations = await _plan(messages, ctx, state)
    if not calculations:
        return _rejected(_NOT_MATH[lang], state, [], reason="no_calculation")

    items = [_evaluate(c.expression, c.label) for c in calculations]
    if any(item.needs_repair for item in items):
        await _repair(messages, calculations, items, ctx, state)
    if all(item.needs_repair for item in items):
        return _rejected(_UNPARSEABLE[lang], state, items, reason="invalid_expressions")
    return _output(items, lang, state)


# --- direct path -------------------------------------------------------------------------


def _direct_expression(inp: SkillInput) -> str | None:
    """A pure expression in the text or the instruction is evaluated with zero LLM calls."""
    for candidate in (inp.text, inp.instruction):
        if len(candidate) > MAX_DIRECT_TEXT_CHARS:
            continue
        stripped = strip_cues(candidate)
        if stripped and looks_like_expression(stripped):
            return to_expression(stripped)
    return None


# --- LLM path ----------------------------------------------------------------------------


def _user_message(inp: SkillInput) -> str:
    """Delimited request. Our own tags are removed from user data so the text cannot
    close a block early and pose as instructions."""
    text = _DELIMITER_TAG.sub("", inp.text)
    instruction = _DELIMITER_TAG.sub("", inp.instruction)
    if inp.is_chained:
        return (
            f"<request>\n{instruction}\n</request>\n<previous_result>\n{text}\n</previous_result>"
        )
    return f"<task>{instruction}</task>\n<request>\n{text}\n</request>"


def _tools_supported(settings: Settings) -> bool:
    try:
        return resolve_profile(settings).supports_tools
    except ConfigError:
        return True  # unknown endpoint: try tools; a 400 still falls back to JSON


def _is_tool_rejection(exc: LLMProviderError) -> bool:
    return exc.status_code == 400 and "tool" in str(exc).lower()


async def _plan(messages: list[ChatMessage], ctx: SkillContext, state: _Run) -> list[Calculation]:
    """Forced tool call first; JSON mode when tools are rejected or come back unusable."""
    if _tools_supported(ctx.settings):
        try:
            state.llm_calls += 1
            response = await ctx.llm.complete(
                messages,
                tools=[EVALUATE_TOOL],
                tool_choice=EVALUATE_TOOL.name,
                temperature=BUDGET.temperature,
                max_tokens=BUDGET.max_output_tokens,
                purpose=PURPOSE,
            )
        except LLMProviderError as exc:
            if not _is_tool_rejection(exc):
                raise
            logger.warning("calculator: provider rejected tools, using JSON mode (%s)", exc)
        else:
            calculations = parse_response(response)
            if calculations is not None:
                return calculations
            logger.warning("calculator: no usable tool call or JSON, using JSON mode")
    state.path = "json_fallback"
    return await _plan_json(messages, ctx, state, purpose=f"{PURPOSE}:json")


async def _plan_json(
    messages: list[ChatMessage], ctx: SkillContext, state: _Run, *, purpose: str, repairs: int = 1
) -> list[Calculation]:
    conversation = [*messages, {"role": "user", "content": _JSON_INSTRUCTION}]
    state.llm_calls += 1
    try:
        result = await ctx.llm.complete_structured(
            conversation,
            CalculationPlan,
            max_repairs=repairs,
            temperature=BUDGET.temperature,
            max_tokens=BUDGET.max_output_tokens,
            purpose=purpose,
        )
    except StructuredOutputError:
        state.llm_calls += repairs
        raise
    state.llm_calls += result.repairs
    return result.value.calculations


async def _repair(
    messages: list[ChatMessage],
    calculations: list[Calculation],
    items: list[_Item],
    ctx: SkillContext,
    state: _Run,
) -> None:
    """One repair round for expressions the evaluator could not parse.

    Only syntax/unsupported errors are repaired: `1/0` is a correct expression whose
    answer is "undefined", and asking again would just invite the model to change it.
    Best effort: if the repair call itself fails, the original errors are reported.
    """
    failing = [item for item in items if item.needs_repair]
    lines = "\n".join(
        f"- `{item.expression}` → {item.error.code}: {item.error.message}"
        for item in failing
        if item.error
    )
    conversation: list[ChatMessage] = [
        *messages,
        {
            "role": "assistant",
            "content": json.dumps(
                {"calculations": [c.model_dump() for c in calculations]}, ensure_ascii=False
            ),
        },
        {
            "role": "user",
            "content": (
                f"These expressions could not be evaluated:\n{lines}\n"
                f"Call evaluate again with corrected expressions for ONLY these "
                f"{len(failing)} calculation(s), in the same order, using only the allowed "
                "syntax and functions."
            ),
        },
    ]
    state.repairs += 1
    purpose = f"{PURPOSE}:repair"
    try:
        if state.path == "tool":
            state.llm_calls += 1
            response = await ctx.llm.complete(
                conversation,
                tools=[EVALUATE_TOOL],
                tool_choice=EVALUATE_TOOL.name,
                temperature=BUDGET.temperature,
                max_tokens=BUDGET.max_output_tokens,
                purpose=purpose,
            )
            fixed = parse_response(response) or []
        else:
            fixed = await _plan_json(conversation, ctx, state, purpose=purpose, repairs=0)
    except (LLMError, StructuredOutputError) as exc:
        logger.warning("calculator: repair call failed (%s); reporting original errors", exc)
        return
    for item, replacement in zip(failing, fixed, strict=False):
        repaired = _evaluate(replacement.expression, replacement.label or item.label)
        item.expression, item.label = repaired.expression, repaired.label
        item.value, item.error = repaired.value, repaired.error


# --- evaluation & output -----------------------------------------------------------------


def _evaluate(expression: str, label: str) -> _Item:
    normalized = to_expression(expression)
    item = _Item(expression=normalized or expression.strip(), label=label)
    try:
        item.value = evaluate(item.expression)
    except CalculatorError as exc:
        item.error = exc
    return item


def _output(items: list[_Item], lang: str, state: _Run) -> SkillOutput:
    lines = []
    for item in items:
        if item.value is not None:
            lines.append(format_result_line(item.expression, item.label, item.value, lang))
        elif item.error is not None:
            lines.append(
                format_error_line(
                    item.expression, item.label, item.error.code, item.error.message, lang
                )
            )
    return SkillOutput(
        status="ok",
        output="\n".join(lines),
        output_kind="number",
        meta=_meta(items, state),
    )


def _rejected(message: str, state: _Run, items: list[_Item], *, reason: str) -> SkillOutput:
    return SkillOutput(
        status="rejected",
        output=message,
        output_kind="number",
        meta=_meta(items, state) | {"reason": reason},
    )


def _meta(items: list[_Item], state: _Run) -> dict[str, Any]:
    return {
        "path": state.path,
        "calculations": [item.meta() for item in items],
        "prompt_version": state.prompt_version,
        "llm_calls": state.llm_calls,
        "repairs": state.repairs,
    }
