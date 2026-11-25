"""Translator skill — STUB created by WP1; WP3 replaces this file completely."""

from __future__ import annotations

from skillagent.core.types import SkillInput, SkillOutput
from skillagent.skills.base import SkillBudget, SkillContext, SkillSpec
from skillagent.skills.params import TranslatorParams


async def run(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
    return SkillOutput(status="ok", output=f"[stub:translator] {inp.instruction}")


SPEC = SkillSpec(
    name="translator",
    description="Translates a provided text into another language.",
    when_to_use=(
        "The user provides a text and asks to translate it into another language.",
        "کاربر متنی آورده و ترجمهٔ آن به زبان دیگری را می‌خواهد.",
    ),
    when_not_to_use=("The user writes in a language but wants an answer, not a translation.",),
    examples=(),
    params_model=TranslatorParams,
    accepts=frozenset({"text", "number"}),
    output_kind="text",
    requires_payload=True,
    budget=SkillBudget(
        max_input_tokens=4000, max_output_tokens=1500, timeout_s=30, temperature=0.2
    ),
    run=run,
    order=20,
)
