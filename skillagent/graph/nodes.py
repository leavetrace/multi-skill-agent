"""Graph nodes: preprocess, router, clarify, scheduler, composer and the skill-node factory.

Each factory closes over the services a node needs (settings, router, LLM) and returns a
plain async/sync function. Run-scoped values come from `RunContext` in the config. Skill
nodes are produced by `make_skill_node` from a `SkillSpec`: graph code never names a skill.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from skillagent.config import Settings
from skillagent.core.language import estimate_tokens, truncate_to_tokens
from skillagent.core.types import (
    RoutingDecision,
    SkillInput,
    SkillOutput,
    SkillResult,
    StepTask,
    TraceEvent,
)
from skillagent.graph import composer
from skillagent.graph.scheduler import COMPOSER, dispatch, plan_wave, waves_done
from skillagent.graph.state import AgentState, run_context
from skillagent.llm.types import ChatMessage, LLMClient, LLMResponse, StructuredResult, T
from skillagent.prompts import PromptLoader
from skillagent.router import Router, build_user_request, leading_segment_hint
from skillagent.skills.base import SkillContext, SkillSpec

__all__ = [
    "CLARIFY",
    "PREPROCESS",
    "ROUTER",
    "SCHEDULER",
    "make_composer",
    "make_dispatch",
    "make_preprocess",
    "make_router",
    "make_scheduler",
    "make_skill_node",
    "clarify",
    "mark_degraded",
    "route_after_preprocess",
    "route_after_router",
]

PREPROCESS, ROUTER, CLARIFY, SCHEDULER = "preprocess", "router", "clarify", "scheduler"
_MAX_TRACE_STR = 160

Update = dict[str, Any]
StepStatus = Literal["ok", "rejected", "error", "timeout", "skipped"]


def _event(config: RunnableConfig, node: str, event: str, **data: Any) -> TraceEvent:
    return TraceEvent(node=node, event=event, data=data, t_ms=run_context(config).elapsed_ms())


# --- preprocess --------------------------------------------------------------------------


def make_preprocess(settings: Settings) -> Callable[[AgentState, RunnableConfig], Update]:
    def preprocess(state: AgentState, config: RunnableConfig) -> Update:
        """Normalize and measure the prompt; refuse oversized input before any LLM call."""
        request = build_user_request(run_context(config).prompt)
        events = [
            _event(
                config,
                PREPROCESS,
                "end",
                lang_hint=request.lang_hint,
                approx_tokens=request.approx_tokens,
                chars=len(request.raw_text),
            )
        ]
        update: Update = {"request": request, "trace": events}
        if request.approx_tokens > settings.max_request_tokens:
            lang = composer.ui_lang(leading_segment_hint(request.raw_text))
            update["final_response"] = composer.limit_message(
                lang, tokens=request.approx_tokens, limit=settings.max_request_tokens
            )
            events.append(
                _event(
                    config,
                    PREPROCESS,
                    "over_limit",
                    approx_tokens=request.approx_tokens,
                    limit=settings.max_request_tokens,
                )
            )
        return update

    return preprocess


def route_after_preprocess(state: AgentState) -> str:
    return COMPOSER if state.get("final_response") else ROUTER


# --- router ------------------------------------------------------------------------------


def mark_degraded(decision: RoutingDecision) -> RoutingDecision:
    """Flag every step of a fallback plan so general chat answers without naming internals."""
    steps = [
        s.model_copy(update={"params": {**s.params, "degraded": True}}) for s in decision.steps
    ]
    return decision.model_copy(update={"steps": steps})


def make_router(
    router: Router, llm: LLMClient
) -> Callable[[AgentState, RunnableConfig], Awaitable[Update]]:
    async def route(state: AgentState, config: RunnableConfig) -> Update:
        """One `Router.route` call; its events (with `llm_calls`) go straight into the trace."""
        result = await router.route(
            state["request"], llm, elapsed_ms=run_context(config).elapsed_ms
        )
        decision = result.decision
        update: Update = {"trace": result.events}
        if decision.route_source == "fallback":
            decision = mark_degraded(decision)
            if _rate_limited(result.events):
                # The provider just refused for quota; a fallback chat call would be refused
                # too (or spend quota on a degraded answer). Record the step as failed so the
                # composer apologises without another call (ADR-029).
                update["results"] = {
                    s.id: SkillResult(
                        step_id=s.id,
                        skill=s.skill,
                        status="error",
                        error="LLMRateLimitError: skipped after router quota error",
                    )
                    for s in decision.steps
                }
        update["decision"] = decision
        return update

    return route


def _rate_limited(events: list[TraceEvent]) -> bool:
    return any(e.event == "fallback" and e.data.get("error") == "LLMRateLimitError" for e in events)


def route_after_router(state: AgentState) -> str:
    """Clarification ends the run; every other decision (fallback included) is a plan."""
    return CLARIFY if state["decision"].needs_clarification else SCHEDULER


def clarify(state: AgentState, config: RunnableConfig) -> Update:
    decision = state["decision"]
    lang = composer.ui_lang(decision.response_language)
    text = composer.clarify_message(lang, decision.clarification_question or "")
    return {"final_response": text, "trace": [_event(config, CLARIFY, "end")]}


# --- scheduler ---------------------------------------------------------------------------


def make_scheduler(settings: Settings) -> Callable[[AgentState, RunnableConfig], Update]:
    def scheduler(state: AgentState, config: RunnableConfig) -> Update:
        """Record skips and the next wave; `make_dispatch` turns that wave into `Send`s."""
        trace = state.get("trace", [])
        done = waves_done(trace)
        wave = plan_wave(
            state["decision"],
            state.get("results", {}),
            waves_done=done,
            max_waves=settings.max_waves,
            max_parallel=settings.max_parallel_steps,
            time_left_s=run_context(config).remaining_s(),
        )
        events = [
            _event(
                config, SCHEDULER, "skip", step=r.step_id, skill=r.skill, reason=r.meta["reason"]
            )
            for r in wave.skipped.values()
        ]
        if wave.steps:
            ids = [s.id for s in wave.steps]
            events.append(_event(config, SCHEDULER, "wave", wave=done + 1, steps=ids))
        else:
            events.append(_event(config, SCHEDULER, "done", waves=done))
        return {"results": wave.skipped, "trace": events}

    return scheduler


def make_dispatch(settings: Settings) -> Callable[[AgentState, RunnableConfig], list[Send] | str]:
    def route_steps(state: AgentState, config: RunnableConfig) -> list[Send] | str:
        run = run_context(config)
        return dispatch(
            state["decision"],
            state.get("results", {}),
            user_text=state["request"].raw_text,
            max_parallel=settings.max_parallel_steps,
            deadline=run.deadline,
        )

    return route_steps


# --- composer ----------------------------------------------------------------------------


def make_composer(settings: Settings) -> Callable[[AgentState, RunnableConfig], Update]:
    def compose(state: AgentState, config: RunnableConfig) -> Update:
        """Assemble the answer; a response written earlier (over-limit) is kept as is."""
        if "decision" not in state:
            return {"trace": [_event(config, COMPOSER, "end", kept=True)]}
        results = state.get("results", {})
        text = composer.compose(
            state["decision"], results, max_skills=settings.max_skills_per_request
        )
        statuses = {sid: r.status for sid, r in results.items()}
        return {
            "final_response": text,
            "trace": [_event(config, COMPOSER, "end", statuses=statuses)],
        }

    return compose


# --- skill nodes -------------------------------------------------------------------------


class _CountingLLM:
    """Counts the calls one skill run makes, for skills whose meta omits `llm_calls`
    and for runs that fail before returning any meta."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.calls = 0

    async def complete(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        return await self._inner.complete(messages, **kwargs)

    async def complete_structured(
        self, messages: list[ChatMessage], schema: type[T], **kwargs: Any
    ) -> StructuredResult[T]:
        self.calls += 1
        result = await self._inner.complete_structured(messages, schema, **kwargs)
        self.calls += result.repairs
        return result


def _budget_input(spec: SkillSpec, inp: SkillInput) -> tuple[SkillInput, bool]:
    """CONTRACTS §15: payload skills own their budgets; others are truncated here."""
    if spec.requires_payload:
        return inp, False
    text, truncated = truncate_to_tokens(inp.text, spec.budget.max_input_tokens)
    return (inp.model_copy(update={"text": text}) if truncated else inp), truncated


def _compact(value: Any) -> Any:
    """Trace-friendly copy of skill meta: long strings (e.g. 5 000-digit exact values) elided."""
    if isinstance(value, str) and len(value) > _MAX_TRACE_STR:
        return f"{value[:_MAX_TRACE_STR]}… ({len(value)} chars)"
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_compact(v) for v in value]
    return value


def make_skill_node(
    spec: SkillSpec, *, llm: LLMClient, settings: Settings, prompts: PromptLoader
) -> Callable[[StepTask, RunnableConfig], Awaitable[Update]]:
    """Generic wrapper around `spec.run` (ARCHITECTURE §4.5).

    The node sees only its `StepTask` (context isolation, ADR-009) and never raises: every
    outcome becomes a `SkillResult`. `asyncio.wait_for` is the only overall deadline, since
    the gateway retries without one (ADR-021).
    """
    trace_node = f"skill:{spec.name}"

    async def skill_node(task: StepTask, config: RunnableConfig) -> Update:
        step = task.step
        inp, truncated = _budget_input(spec, task.skill_input)
        events = [
            _event(
                config,
                trace_node,
                "start",
                step=step.id,
                is_chained=inp.is_chained,
                input_tokens=estimate_tokens(inp.text),
                input_truncated=truncated,
            )
        ]
        counter = _CountingLLM(llm)
        timeout_s = min(spec.budget.timeout_s, task.deadline_monotonic - time.monotonic())
        started = time.perf_counter()
        output: SkillOutput | None = None
        error: str | None = None
        status: StepStatus
        try:
            if timeout_s <= 0:
                raise TimeoutError
            output = await asyncio.wait_for(
                spec.run(inp, SkillContext(llm=counter, settings=settings, prompts=prompts)),
                timeout=timeout_s,
            )
            status = output.status
        except TimeoutError:
            status, error = "timeout", f"TimeoutError: no result within {max(timeout_s, 0):.1f}s"
        except Exception as exc:  # a skill failure must never escape the node
            status, error = "error", f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        meta: dict[str, Any] = dict(output.meta) if output else {}
        meta["llm_calls"] = meta.get("llm_calls", counter.calls)
        meta["latency_ms"] = latency_ms
        if truncated:
            meta["input_truncated"] = True
        result = SkillResult(
            step_id=step.id,
            skill=spec.name,
            status=status,
            output=output.output if output else "",
            output_kind=output.output_kind if output else spec.output_kind,
            error=error,
            meta=meta,
        )
        events.append(
            _event(
                config,
                trace_node,
                "end",
                step=step.id,
                status=status,
                latency_ms=latency_ms,
                llm_calls=meta["llm_calls"],
                error=error,
                meta=_compact({k: v for k, v in meta.items() if k not in ("latency_ms",)}),
            )
        )
        return {"results": {step.id: result}, "trace": events}

    skill_node.__name__ = f"skill_{spec.name}"
    return skill_node
