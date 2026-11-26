"""Graph assembly (ADR-001): fixed control nodes plus one generated node per registered skill.

    START → preprocess ─┬─────────────────────────────→ composer → END   (over the token limit)
                        └→ router ─┬→ clarify → END
                                   └→ scheduler ⇄ skill_<name> …   (Send, one wave at a time)
                                          └→ composer → END

Adding a skill adds a node and an edge back to the scheduler here, with no code change:
the loop over `registry.specs()` is the only place skill nodes come from.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from skillagent.config import Settings
from skillagent.core.registry import SkillRegistry
from skillagent.graph.nodes import (
    CLARIFY,
    PREPROCESS,
    ROUTER,
    SCHEDULER,
    clarify,
    make_composer,
    make_dispatch,
    make_preprocess,
    make_router,
    make_scheduler,
    make_skill_node,
    route_after_preprocess,
    route_after_router,
)
from skillagent.graph.scheduler import COMPOSER, skill_node_name
from skillagent.graph.state import AgentState
from skillagent.llm.types import LLMClient
from skillagent.prompts import PromptLoader
from skillagent.router import Router

__all__ = ["FIXED_NODES", "build_graph", "mermaid", "recursion_limit"]

FIXED_NODES = (PREPROCESS, ROUTER, CLARIFY, SCHEDULER, COMPOSER)

AgentGraph = CompiledStateGraph[AgentState, Any, AgentState, AgentState]


def build_graph(
    registry: SkillRegistry,
    settings: Settings,
    llm: LLMClient,
    prompts: PromptLoader,
    *,
    router: Router | None = None,
) -> AgentGraph:
    """Compile the agent graph. `router` is injectable so tests can pin a candidate selector."""
    router = router or Router(registry, settings, prompts)
    graph = StateGraph(AgentState)
    graph.add_node(PREPROCESS, make_preprocess(settings))
    graph.add_node(ROUTER, make_router(router, llm))
    graph.add_node(CLARIFY, clarify)
    graph.add_node(SCHEDULER, make_scheduler(settings))
    graph.add_node(COMPOSER, make_composer(settings))

    skill_nodes = []
    for spec in registry.specs():
        name = skill_node_name(spec.name)
        graph.add_node(name, make_skill_node(spec, llm=llm, settings=settings, prompts=prompts))
        graph.add_edge(name, SCHEDULER)
        skill_nodes.append(name)

    graph.add_edge(START, PREPROCESS)
    graph.add_conditional_edges(PREPROCESS, route_after_preprocess, [ROUTER, COMPOSER])
    graph.add_conditional_edges(ROUTER, route_after_router, [CLARIFY, SCHEDULER])
    graph.add_conditional_edges(SCHEDULER, make_dispatch(settings), [*skill_nodes, COMPOSER])
    graph.add_edge(CLARIFY, END)
    graph.add_edge(COMPOSER, END)
    return graph.compile(name="skillagent")


def recursion_limit(settings: Settings) -> int:
    """Backstop derived from the caps: preprocess, router, scheduler, then (skills,
    scheduler) per wave, then composer, plus slack. The scheduler's `max_waves` check
    ends the run first; hitting this limit means a scheduling bug."""
    return 4 + 2 * settings.max_waves + 2


class _NoLLM:
    """Placeholder for drawing the graph: drawing never runs a node."""

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("graph built for drawing only; no LLM attached")

    async def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("graph built for drawing only; no LLM attached")


def mermaid(registry: SkillRegistry | None = None, settings: Settings | None = None) -> str:
    """Mermaid source from LangGraph's own drawer, so the README diagram is the real graph."""
    from skillagent.skills.catalog import build_default_registry

    settings = settings or Settings()
    graph = build_graph(
        registry or build_default_registry(),
        settings,
        _NoLLM(),
        PromptLoader(pinned=settings.prompt_versions),
    )
    return graph.get_graph().draw_mermaid()
