"""General chat skill — STUB created by WP1; WP3 replaces this file completely."""

from __future__ import annotations

from skillagent.core.types import SkillInput, SkillOutput
from skillagent.skills.base import SkillBudget, SkillContext, SkillSpec


async def run(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
    return SkillOutput(status="ok", output=f"[stub:general_chat] {inp.instruction}")


SPEC = SkillSpec(
    name="general_chat",
    description="Answers greetings, small talk and general questions; fallback for anything else.",
    when_to_use=(
        "Greetings, small talk, general-knowledge questions, or requests no other skill covers.",
        "سلام و احوال‌پرسی، گفت‌وگوی عمومی، پرسش‌های دانش عمومی یا درخواست‌های خارج از مهارت‌ها.",
    ),
    when_not_to_use=("Arithmetic or numeric computation (use calculator).",),
    examples=(),
    params_model=None,
    accepts=frozenset({"text", "number"}),
    output_kind="text",
    requires_payload=False,
    budget=SkillBudget(max_input_tokens=1500, max_output_tokens=600, timeout_s=25, temperature=0.7),
    run=run,
    order=90,
)
