"""Summarizer skill — STUB created by WP1; WP3 replaces this file completely."""

from __future__ import annotations

from skillagent.core.types import SkillInput, SkillOutput
from skillagent.skills.base import SkillBudget, SkillContext, SkillSpec
from skillagent.skills.params import SummarizerParams


async def run(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
    return SkillOutput(status="ok", output=f"[stub:summarizer] {inp.instruction}")


SPEC = SkillSpec(
    name="summarizer",
    description="Condenses a provided text into a faithful summary.",
    when_to_use=(
        "The user provides a text and asks to summarize, shorten or get the key points of it.",
        "کاربر متنی آورده و خلاصه، چکیده یا نکات اصلی آن را می‌خواهد.",
    ),
    when_not_to_use=("No text to summarize is provided (ask for it instead).",),
    examples=(),
    params_model=SummarizerParams,
    accepts=frozenset({"text"}),
    output_kind="text",
    requires_payload=True,
    budget=SkillBudget(max_input_tokens=4000, max_output_tokens=700, timeout_s=30, temperature=0.3),
    run=run,
    order=10,
)
