"""Integration fixtures: the real registry, `FakeLLM` rules keyed by `purpose`, plan builders.

Helpers are fixtures because tests run with `--import-mode=importlib` (no test packages).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest

from skillagent.api import AgentRun, run_agent
from skillagent.config import Settings
from skillagent.core.registry import SkillRegistry
from skillagent.llm.types import ToolCall
from skillagent.testing import FakeLLM, FakeRule

Reply = Any  # str | list[ToolCall] | Exception | callable, as FakeRule accepts


def step(
    sid: str, skill: str, instruction: str, input_from: str = "user", **params: Any
) -> dict[str, Any]:
    return {
        "id": sid,
        "skill": skill,
        "instruction": instruction,
        "input_from": input_from,
        "params": params,
    }


@pytest.fixture
def plan() -> Callable[..., str]:
    """`plan("en", step(...), ...)` → router JSON reply."""

    def build(lang: str, *steps: dict[str, Any], **extra: Any) -> str:
        return json.dumps(
            {"response_language": lang, "steps": list(steps), "confidence": 0.9, **extra},
            ensure_ascii=False,
        )

    return build


@pytest.fixture
def mk_step() -> Callable[..., dict[str, Any]]:
    return step


@pytest.fixture
def fake_llm() -> Callable[..., FakeLLM]:
    """`fake_llm(router=..., translator=..., ...)`: one rule per purpose (`skill:<name>`)."""

    def build(router: Reply, **skills: Reply) -> FakeLLM:
        rules = [FakeRule(match=lambda m, p: p.startswith("router"), reply=router)]  # + repair
        for name, reply in skills.items():
            purpose = f"skill:{name}"
            rules.append(FakeRule(match=lambda m, p, want=purpose: p == want, reply=reply))
        return FakeLLM(rules)

    return build


@pytest.fixture
def calc_call() -> Callable[..., list[ToolCall]]:
    """`calc_call("0.25*840", label=...)` → an `evaluate` tool-call reply."""

    def build(expression: str, label: str = "") -> list[ToolCall]:
        args = {"calculations": [{"expression": expression, "label": label}]}
        return [ToolCall(id="c1", name="evaluate", arguments=args, raw_arguments=json.dumps(args))]

    return build


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def run(settings: Settings) -> Callable[..., Any]:
    """`await run(prompt, llm, registry=None, settings=None)` → `AgentRun`."""

    async def go(
        prompt: str,
        llm: Any,
        *,
        registry: SkillRegistry | None = None,
        settings_override: Settings | None = None,
    ) -> AgentRun:
        return await run_agent(
            prompt, settings=settings_override or settings, llm=llm, registry=registry
        )

    return go


class BarrierLLM(FakeLLM):
    """Skill calls wait until `parties` of them are in flight: passes only if concurrent."""

    def __init__(self, rules: list[FakeRule], parties: int) -> None:
        super().__init__(rules)
        self.barrier = asyncio.Barrier(parties)

    async def complete(self, messages: Any, **kwargs: Any) -> Any:
        if kwargs.get("purpose", "").startswith("skill:"):
            await asyncio.wait_for(self.barrier.wait(), timeout=2)
        return await super().complete(messages, **kwargs)


@pytest.fixture
def barrier_llm() -> type[BarrierLLM]:
    return BarrierLLM
