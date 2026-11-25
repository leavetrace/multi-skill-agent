"""Calculator skill — STUB created by WP1; WP2 expands this package completely."""

from __future__ import annotations

from skillagent.core.types import SkillInput, SkillOutput
from skillagent.skills.base import SkillBudget, SkillContext, SkillSpec


async def run(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
    return SkillOutput(status="ok", output=f"[stub:calculator] {inp.instruction}")


SPEC = SkillSpec(
    name="calculator",
    description="Evaluates arithmetic and numeric expressions exactly with a safe evaluator.",
    when_to_use=(
        "The user asks to compute, calculate or evaluate a math expression or percentage.",
        "کاربر محاسبهٔ یک عبارت ریاضی، درصد یا عملیات عددی را می‌خواهد.",
    ),
    when_not_to_use=("Questions about math concepts that need no computation (use general_chat).",),
    examples=(),
    params_model=None,
    accepts=frozenset({"text", "number"}),
    output_kind="number",
    requires_payload=False,
    budget=SkillBudget(max_input_tokens=800, max_output_tokens=300, timeout_s=20, temperature=0.0),
    run=run,
    order=30,
)
