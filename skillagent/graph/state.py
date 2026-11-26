"""Graph state (CONTRACTS §10) and the per-run context that is deliberately *not* state.

The state holds only what nodes exchange: the request, the plan, step results and the
trace. Run-scoped constants (the raw prompt, the start time, the absolute deadline) travel
in LangGraph's `config["configurable"]`, so they are readable by every node, including the
skill nodes that receive nothing but a `StepTask`, without widening the frozen state.
"""

from __future__ import annotations

import operator
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig

from skillagent.core.types import RoutingDecision, SkillResult, TraceEvent, UserRequest

__all__ = ["RUN_KEY", "AgentState", "RunContext", "merge_results", "run_context"]

RUN_KEY = "skillagent_run"


def merge_results(
    left: dict[str, SkillResult] | None, right: dict[str, SkillResult] | None
) -> dict[str, SkillResult]:
    """Dict merge keyed by step_id: parallel skill nodes each contribute their own key."""
    return {**(left or {}), **(right or {})}


class AgentState(TypedDict, total=False):
    request: UserRequest
    decision: RoutingDecision
    results: Annotated[dict[str, SkillResult], merge_results]
    final_response: str
    trace: Annotated[list[TraceEvent], operator.add]


@dataclass(frozen=True)
class RunContext:
    """Per-request constants. `started`/`deadline` are `time.monotonic()` values."""

    prompt: str
    started: float
    deadline: float

    @classmethod
    def start(cls, prompt: str, deadline_s: float) -> RunContext:
        now = time.monotonic()
        return cls(prompt=prompt, started=now, deadline=now + deadline_s)

    def elapsed_ms(self) -> float:
        return round((time.monotonic() - self.started) * 1000, 2)

    def remaining_s(self) -> float:
        return self.deadline - time.monotonic()


def run_context(config: RunnableConfig) -> RunContext:
    """The `RunContext` that `run_agent` put into the config; a clear error if missing."""
    ctx = (config.get("configurable") or {}).get(RUN_KEY)
    if not isinstance(ctx, RunContext):
        raise RuntimeError(f"graph invoked without config['configurable'][{RUN_KEY!r}]")
    return ctx
