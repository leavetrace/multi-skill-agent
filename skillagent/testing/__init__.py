"""Offline test helpers shared by every work package.

`FakeLLM` scripts model replies; `make_skill_spec` builds throwaway specs (e.g. the 20
synthetic skills of the scalability tests) without touching the product catalog.
"""

from __future__ import annotations

from pydantic import BaseModel

from skillagent.core.types import IOKind, SkillInput, SkillOutput
from skillagent.skills.base import SkillBudget, SkillContext, SkillRunner, SkillSpec
from skillagent.testing.fake_llm import FakeLLM, FakeRule, RecordedCall

__all__ = ["FakeLLM", "FakeRule", "RecordedCall", "echo_runner", "make_skill_spec"]


async def echo_runner(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
    """Runner that returns its instruction; handy when a test only cares about wiring."""
    return SkillOutput(status="ok", output=inp.instruction)


def make_skill_spec(
    name: str,
    *,
    accepts: frozenset[IOKind] = frozenset({"text", "number"}),
    output_kind: IOKind = "text",
    params_model: type[BaseModel] | None = None,
    requires_payload: bool = False,
    run: SkillRunner = echo_runner,
    order: int = 100,
    description: str | None = None,
) -> SkillSpec:
    return SkillSpec(
        name=name,
        description=description or f"Synthetic test skill {name}.",
        when_to_use=(f"use {name}",),
        when_not_to_use=(),
        examples=(),
        params_model=params_model,
        accepts=accepts,
        output_kind=output_kind,
        requires_payload=requires_payload,
        budget=SkillBudget(
            max_input_tokens=1000, max_output_tokens=200, timeout_s=5, temperature=0
        ),
        run=run,
        order=order,
    )
