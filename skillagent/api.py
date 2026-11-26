"""Public API (CONTRACTS §9): `run_agent(prompt) -> AgentRun`, used by the CLI and eval.

`run_agent` never raises for model or provider trouble: whatever escapes the graph becomes
a degraded `AgentRun` with the bilingual apology and the exception in the trace, so a
REPL session or an eval run survives a bad turn. Configuration errors do raise
(`ConfigError`), because only the user can fix them and the CLI prints how.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from skillagent.config import Settings
from skillagent.core.errors import ConfigError
from skillagent.core.registry import SkillRegistry
from skillagent.core.types import RoutingDecision, SkillResult, TraceEvent
from skillagent.graph.builder import build_graph, recursion_limit
from skillagent.graph.composer import APOLOGY
from skillagent.graph.state import RUN_KEY, RunContext
from skillagent.llm import OpenAICompatGateway, resolve_profile
from skillagent.llm.types import LLMClient
from skillagent.prompts import PromptLoader
from skillagent.skills.catalog import build_default_registry

__all__ = ["AgentRun", "count_llm_calls", "run_agent"]

logger = logging.getLogger("skillagent.api")


class AgentRun(BaseModel):
    response: str
    decision: RoutingDecision | None
    results: dict[str, SkillResult]
    trace: list[TraceEvent]
    total_ms: float
    llm_calls: int


def count_llm_calls(trace: list[TraceEvent], results: dict[str, SkillResult]) -> int:
    """Router calls (from its `end` event) plus each skill's `meta["llm_calls"]`."""
    router = sum(
        int(e.data.get("llm_calls", 0)) for e in trace if e.node == "router" and e.event == "end"
    )
    return router + sum(int(r.meta.get("llm_calls", 0)) for r in results.values())


async def run_agent(
    prompt: str,
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    registry: SkillRegistry | None = None,
) -> AgentRun:
    """Run one request through the graph.

    Without an injected `llm`, a gateway is created here, inside the running loop, and
    closed afterwards (one gateway per event loop, ADR-021). Long-lived callers (the REPL,
    eval) pass their own so rate limits and connections are shared across turns.
    """
    settings = settings or Settings()
    registry = registry or build_default_registry()
    if llm is not None:
        return await _run(prompt, settings, llm, registry)
    gateway = OpenAICompatGateway(settings, resolve_profile(settings))
    try:
        return await _run(prompt, settings, gateway, registry)
    finally:
        await gateway.aclose()


async def _run(
    prompt: str, settings: Settings, llm: LLMClient, registry: SkillRegistry
) -> AgentRun:
    run = RunContext.start(prompt, settings.request_deadline_s)
    graph = build_graph(registry, settings, llm, PromptLoader(pinned=settings.prompt_versions))
    config: dict[str, Any] = {
        "configurable": {RUN_KEY: run},
        "recursion_limit": recursion_limit(settings),
    }
    # Stream full-state snapshots so a failure mid-run still reports what had happened.
    state: dict[str, Any] = {}
    try:
        async for snapshot in graph.astream({"trace": []}, config, stream_mode="values"):
            state = snapshot
    except ConfigError:
        raise
    except Exception as exc:
        logger.warning("run_agent degraded: %s: %s", type(exc).__name__, exc)
        trace = [
            *state.get("trace", []),
            TraceEvent(
                node="agent",
                event="error",
                data={"error": f"{type(exc).__name__}: {str(exc)[:300]}"},
                t_ms=run.elapsed_ms(),
            ),
        ]
        state = {**state, "trace": trace, "final_response": APOLOGY}

    trace = list(state.get("trace", []))
    results = dict(state.get("results", {}))
    return AgentRun(
        response=state.get("final_response") or APOLOGY,
        decision=state.get("decision"),
        results=results,
        trace=trace,
        total_ms=run.elapsed_ms(),
        llm_calls=count_llm_calls(trace, results),
    )
