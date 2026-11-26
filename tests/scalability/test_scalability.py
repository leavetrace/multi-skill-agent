"""Scalability proof with 20 synthetic skills + the 4 real ones (ADR-008, ARCHITECTURE §7).

Nothing in `skillagent/` changes between these registries: the graph, the router prompt
and the limits all follow from the registry and the settings. Run with `-s` to see the
measured numbers recorded in the WP5 report.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest

from skillagent.api import run_agent
from skillagent.config import Settings
from skillagent.core.registry import SkillRegistry
from skillagent.core.types import SkillInput, SkillOutput
from skillagent.graph import build_graph
from skillagent.graph.builder import FIXED_NODES
from skillagent.prompts import PromptLoader
from skillagent.router import Router, build_user_request
from skillagent.router.candidates import AllSkills, BM25TopK
from skillagent.skills.base import SkillContext
from skillagent.skills.catalog import build_default_registry
from skillagent.testing import FakeLLM, FakeRule, make_skill_spec

# name, description, bilingual cues
DOMAINS: tuple[tuple[str, str, str], ...] = (
    (
        "weather_forecast",
        "Weather forecast for a city.",
        "weather rain temperature | آب و هوا باران",
    ),
    (
        "currency_exchange",
        "Converts money between currencies.",
        "exchange rate dollar | نرخ ارز دلار",
    ),
    ("recipe_finder", "Finds cooking recipes.", "recipe cook ingredients | دستور پخت آشپزی"),
    ("flight_search", "Searches airline flights.", "flight ticket airport | پرواز بلیط هواپیما"),
    ("hotel_booking", "Books hotel rooms.", "hotel room reservation | هتل اتاق رزرو"),
    ("music_player", "Plays songs and playlists.", "play music song | پخش موسیقی آهنگ"),
    ("movie_guide", "Recommends films.", "movie film cinema | فیلم سینما"),
    ("stock_market", "Reports stock prices.", "stock share market | سهام بورس"),
    ("fitness_coach", "Creates workout plans.", "workout exercise gym | ورزش تمرین باشگاه"),
    ("email_writer", "Drafts emails.", "email draft letter | ایمیل نامه"),
    ("calendar_manager", "Schedules meetings.", "calendar meeting schedule | تقویم جلسه"),
    ("news_digest", "Gives news headlines.", "news headlines | اخبار خبر"),
    ("dictionary_lookup", "Defines words.", "define meaning synonym | معنی کلمه"),
    ("unit_converter", "Converts units.", "convert miles kilometers | تبدیل واحد کیلومتر"),
    ("sports_scores", "Shows match results.", "football match score | فوتبال نتیجه بازی"),
    ("traffic_info", "Reports road traffic.", "traffic road jam | ترافیک جاده"),
    ("book_recommender", "Recommends books.", "book novel author | کتاب رمان نویسنده"),
    ("plant_care", "Advises on plant care.", "plant water garden | گیاه آبیاری باغچه"),
    ("pet_advisor", "Answers pet care questions.", "dog cat pet vet | سگ گربه دامپزشک"),
    ("travel_planner", "Plans trips and itineraries.", "trip travel itinerary | سفر برنامه سفر"),
)
SIZES = (4, 10, 20, 24)  # total registry sizes: 4 real + 0/6/16/20 synthetic

Seen = list[tuple[str, Any]]


def synthetic(name: str, description: str, cues: str, seen: Seen) -> Any:
    async def runner(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
        seen.append((name, inp))
        return SkillOutput(status="ok", output=f"{name} done: {inp.instruction}")

    spec = make_skill_spec(name, description=description, run=runner)
    return dataclasses.replace(spec, when_to_use=tuple(c.strip() for c in cues.split("|")))


def registry_of(size: int, seen: Seen | None = None) -> SkillRegistry:
    registry = build_default_registry()
    for name, description, cues in DOMAINS[: size - len(registry)]:
        registry.register(synthetic(name, description, cues, seen if seen is not None else []))
    assert len(registry) == size
    return registry


def router_llm(plan: dict[str, Any]) -> FakeLLM:
    return FakeLLM([FakeRule(match=lambda m, p: p == "router", reply=json.dumps(plan))])


def steps(names: list[str], *, chained: bool) -> list[dict[str, Any]]:
    return [
        {
            "id": f"s{i}",
            "skill": name,
            "instruction": f"task {i}",
            "input_from": f"s{i - 1}" if chained and i > 1 else "user",
        }
        for i, name in enumerate(names, start=1)
    ]


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


def test_graph_nodes_follow_the_registry(settings: Settings) -> None:
    rows = []
    for size in SIZES:
        registry = registry_of(size)
        graph = build_graph(registry, settings, router_llm({}), PromptLoader())
        nodes = set(graph.get_graph().nodes)
        skill_nodes = {n for n in nodes if n.startswith("skill_")}
        assert skill_nodes == {f"skill_{name}" for name in registry.names()}
        assert len(nodes) == 2 + len(FIXED_NODES) + size  # + __start__/__end__
        rows.append((size, len(FIXED_NODES), len(skill_nodes), len(nodes)))
    print("\nN skills | fixed nodes | skill nodes | total incl. START/END")
    for row in rows:
        print(" | ".join(str(v) for v in row))


def test_router_prompt_tokens_by_registry_size(settings: Settings) -> None:
    request = build_user_request("Will it rain in Tehran tomorrow? فردا در تهران باران می‌آید؟")
    prompts = PromptLoader()
    rows = []
    for size in SIZES:
        registry = registry_of(size)
        router = Router(registry, settings, prompts)
        candidates = router.selector.select(request, registry)
        _, shown = router.build_messages(request, candidates)
        _, everything = router.build_messages(request, registry.names())
        rows.append(
            (size, type(router.selector).__name__, len(candidates), shown["system_tokens"],
             everything["system_tokens"])
        )  # fmt: skip
        if size > settings.router_top_k_threshold:
            assert shown["system_tokens"] < everything["system_tokens"]
    print("\nN skills | selector | cards shown | system tokens (est.) | all-cards tokens (est.)")
    for row in rows:
        print(" | ".join(str(v) for v in row))
    assert rows[0][1] == "AllSkills" and rows[-1][1] == "BM25TopK"


async def test_bm25_top_k_above_threshold(settings: Settings) -> None:
    registry = registry_of(24)
    router = Router(registry, settings, PromptLoader())
    assert isinstance(router.selector, BM25TopK)
    assert isinstance(Router(registry_of(4), settings, PromptLoader()).selector, AllSkills)

    plan = {"response_language": "en", "steps": steps(["weather_forecast"], chained=False)}
    run = await run_agent(
        "Will it rain in Tehran tomorrow?", settings=settings, llm=router_llm(plan),
        registry=registry,
    )  # fmt: skip
    (event,) = [e for e in run.trace if e.node == "router" and e.event == "candidates"]
    print(f"\nBM25 candidates for a weather prompt: {event.data['skills']}")
    assert event.data["selector"] == "BM25TopK"
    assert "general_chat" in event.data["skills"]
    assert "weather_forecast" in event.data["skills"]
    assert event.data["count"] <= settings.router_top_k + 1
    assert run.results["s1"].status == "ok"


async def test_six_step_plan_runs_two_and_drops_four(settings: Settings) -> None:
    seen: Seen = []
    registry = registry_of(24, seen)
    names = [d[0] for d in DOMAINS[:6]]
    plan = {"response_language": "en", "steps": steps(names, chained=False)}
    run = await run_agent("do six things", settings=settings, llm=router_llm(plan),
                          registry=registry)  # fmt: skip
    assert run.decision is not None
    assert [s.skill for s in run.decision.steps] == names[:2]
    assert run.decision.dropped_intents == ["task 3", "task 4", "task 5", "task 6"]
    assert [name for name, _ in seen] == names[:2]
    assert "I handle up to 2 tasks per request, so I skipped: task 3; task 4" in run.response
    print(f"\n6-step plan: ran {len(seen)}, dropped {len(run.decision.dropped_intents)}")


@pytest.mark.parametrize(("max_waves", "expected_ok"), [(2, 2), (10, 10)])
async def test_ten_step_chain_stops_at_max_waves(
    make_settings: Callable[..., Settings], max_waves: int, expected_ok: int
) -> None:
    settings = make_settings(max_skills_per_request=10, max_waves=max_waves)
    seen: Seen = []
    registry = registry_of(24, seen)
    names = [d[0] for d in DOMAINS[:10]]
    plan = {"response_language": "en", "steps": steps(names, chained=True)}
    run = await run_agent("ten chained steps", settings=settings, llm=router_llm(plan),
                          registry=registry)  # fmt: skip
    statuses = [run.results[f"s{i}"].status for i in range(1, 11)]
    assert statuses == ["ok"] * expected_ok + ["skipped"] * (10 - expected_ok)
    waves = [e for e in run.trace if e.node == "scheduler" and e.event == "wave"]
    assert len(waves) == expected_ok
    if expected_ok < 10:
        reasons = {run.results[f"s{i}"].meta["reason"] for i in range(expected_ok + 1, 11)}
        assert reasons == {"max_waves"}
        assert "reached its time or step limit" in run.response
    # chain isolation: each step received exactly the previous step's output
    for (_, inp), previous in zip(seen[1:], seen, strict=False):
        assert inp.is_chained and inp.text == f"{previous[0]} done: {previous[1].instruction}"
    print(f"\n10-step chain, max_waves={max_waves}: {statuses.count('ok')} ran, "
          f"{statuses.count('skipped')} skipped")  # fmt: skip


async def test_every_skill_node_receives_only_skill_input(settings: Settings) -> None:
    seen: Seen = []
    registry = registry_of(24, seen)
    for first, second in zip(DOMAINS[0::2], DOMAINS[1::2], strict=True):
        plan = {
            "response_language": "fa",
            "steps": steps([first[0], second[0]], chained=False),
            "rationale": "ROUTER-ONLY rationale",
        }
        await run_agent("یک درخواست", settings=settings, llm=router_llm(plan), registry=registry)
    assert len(seen) == len(DOMAINS)
    for _, inp in seen:
        assert type(inp) is SkillInput
        assert inp.text == "یک درخواست" and not inp.is_chained
        assert "ROUTER-ONLY" not in inp.model_dump_json()
