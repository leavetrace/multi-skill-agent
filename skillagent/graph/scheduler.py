"""Deterministic wave scheduler over the router's mini-DAG (ADR-001, ARCHITECTURE §4.4).

The router decides *what* runs; these pure functions decide *when*. A step is READY when it
has no result yet and its input is either the user's prompt or an `ok` result. Each wave
dispatches up to `max_parallel` READY steps; a step whose dependency ended in anything but
`ok` is skipped and never runs, so one failure cannot cascade into garbage input.

Nothing here imports LangGraph except `Send`, the payload type `dispatch` returns, so the
scheduling rules are unit-testable on plain `RoutingDecision`/`SkillResult` values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from langgraph.types import Send

from skillagent.core.types import (
    PlanStep,
    RoutingDecision,
    SkillInput,
    SkillResult,
    StepTask,
    TraceEvent,
)

__all__ = [
    "COMPOSER",
    "SkipReason",
    "Wave",
    "build_step_task",
    "dispatch",
    "plan_wave",
    "propagate_skips",
    "ready_steps",
    "skill_node_name",
    "skipped_result",
    "waves_done",
]

COMPOSER = "composer"
SkipReason = Literal["dependency", "max_waves", "deadline"]


def skill_node_name(skill: str) -> str:
    """Graph node for a skill. LangGraph reserves ':', so trace names (`skill:x`) differ."""
    return f"skill_{skill}"


def skipped_result(step: PlanStep, reason: SkipReason, detail: str = "") -> SkillResult:
    return SkillResult(
        step_id=step.id,
        skill=step.skill,
        status="skipped",
        error=detail or reason,
        meta={"reason": reason, "llm_calls": 0},
    )


def ready_steps(decision: RoutingDecision, results: Mapping[str, SkillResult]) -> list[PlanStep]:
    """Steps without a result whose input is available, in plan order."""
    ready = []
    for step in decision.steps:
        if step.id in results:
            continue
        dep = results.get(step.input_from)
        if step.input_from == "user" or (dep is not None and dep.status == "ok"):
            ready.append(step)
    return ready


def propagate_skips(
    decision: RoutingDecision, results: Mapping[str, SkillResult]
) -> dict[str, SkillResult]:
    """`skipped` results for every pending step downstream of a non-`ok` result.

    One pass suffices: V4 guarantees a step only references *earlier* steps, so plan order
    is a topological order and a skip is known before its own dependents are visited.
    """
    known = dict(results)
    skipped: dict[str, SkillResult] = {}
    for step in decision.steps:
        if step.id in known or step.input_from == "user":
            continue
        dep = known.get(step.input_from)
        if dep is not None and dep.status != "ok":
            result = skipped_result(
                step, "dependency", f"input step {dep.step_id} ended with status {dep.status!r}"
            )
            known[step.id] = skipped[step.id] = result
    return skipped


@dataclass(frozen=True)
class Wave:
    """What the scheduler node does next: run `steps` now, after recording `skipped`."""

    steps: list[PlanStep]
    skipped: dict[str, SkillResult] = field(default_factory=dict)


def plan_wave(
    decision: RoutingDecision,
    results: Mapping[str, SkillResult],
    *,
    waves_done: int,
    max_waves: int,
    max_parallel: int,
    time_left_s: float,
) -> Wave:
    """Next wave, or an empty wave (→ composer) once nothing can or may run.

    When the wave cap or the request deadline is hit, every still-pending step is
    recorded as skipped so the composer can tell the user instead of silently dropping it.
    """
    skipped = propagate_skips(decision, results)
    merged = {**results, **skipped}
    ready = ready_steps(decision, merged)
    if not ready:
        return Wave(steps=[], skipped=skipped)
    limit: SkipReason | None = None
    if waves_done >= max_waves:
        limit = "max_waves"
    elif time_left_s <= 0:
        limit = "deadline"
    if limit is not None:
        for step in decision.steps:
            if step.id not in merged:
                skipped[step.id] = skipped_result(step, limit)
        return Wave(steps=[], skipped=skipped)
    return Wave(steps=ready[:max_parallel], skipped=skipped)


def waves_done(trace: Sequence[TraceEvent]) -> int:
    """Waves dispatched so far; the scheduler records one `wave` event per dispatch."""
    return sum(1 for e in trace if e.node == "scheduler" and e.event == "wave")


def build_step_task(
    step: PlanStep,
    *,
    user_text: str,
    response_language: str,
    results: Mapping[str, SkillResult],
    deadline: float,
) -> StepTask:
    """The only payload a skill node receives (ADR-009): its own text, never the plan.

    A chained step gets exactly its declared dependency's output, not the user prompt, so a
    translator after a summarizer translates the summary and nothing else.
    """
    chained = step.input_from != "user"
    text = results[step.input_from].output if chained else user_text
    return StepTask(
        step=step,
        skill_input=SkillInput(
            text=text,
            instruction=step.instruction,
            params=dict(step.params),
            response_language=response_language,
            is_chained=chained,
        ),
        deadline_monotonic=deadline,
    )


def dispatch(
    decision: RoutingDecision,
    results: Mapping[str, SkillResult],
    *,
    user_text: str,
    max_parallel: int,
    deadline: float,
) -> list[Send] | str:
    """`Send`s for the wave the scheduler node just planned, or `"composer"` when done.

    It recomputes READY instead of reading a scratch field: after the scheduler node has
    recorded its skips (including wave-cap and deadline skips), the READY set is exactly
    the planned wave, so state stays the frozen CONTRACTS §10 shape.
    """
    ready = ready_steps(decision, results)[:max_parallel]
    if not ready:
        return COMPOSER
    return [
        Send(
            skill_node_name(step.skill),
            build_step_task(
                step,
                user_text=user_text,
                response_language=decision.response_language,
                results=results,
                deadline=deadline,
            ),
        )
        for step in ready
    ]
