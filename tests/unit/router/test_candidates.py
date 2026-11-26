"""Top-K selection: threshold switching and measured BM25 recall on synthetic skills."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from skillagent.core.registry import SkillRegistry
from skillagent.router import Router, build_user_request
from skillagent.router.candidates import AllSkills, BM25TopK, CandidateSelector, tokenize
from skillagent.skills.base import SkillSpec
from skillagent.skills.catalog import build_default_registry
from skillagent.testing import FakeLLM, make_skill_spec


def _registry(specs: list[SkillSpec], n: int, *, with_product: bool) -> SkillRegistry:
    reg = build_default_registry() if with_product else SkillRegistry()
    for spec in specs[:n]:
        reg.register(spec)
    return reg


def test_tokenizer_normalizes_persian_and_zwnj() -> None:
    assert tokenize("می‌شود") == tokenize("میشود") == ["میشود"]
    assert tokenize("كتاب ي") == ["کتاب"]  # Arabic → Persian; 1-char tokens dropped
    assert tokenize("Weather_Forecast, rain!") == ["weather", "forecast", "rain"]


def test_selectors_satisfy_protocol() -> None:
    assert isinstance(AllSkills(), CandidateSelector)
    assert isinstance(BM25TopK(3), CandidateSelector)
    with pytest.raises(ValueError):
        BM25TopK(0)


@pytest.mark.parametrize(("extra", "expected"), [(8, AllSkills), (9, BM25TopK)])
def test_selector_switches_at_threshold(
    make_router: Callable[..., Router],
    synthetic_specs: list[SkillSpec],
    extra: int,
    expected: type,
) -> None:
    reg = _registry(synthetic_specs, extra, with_product=True)  # 4 + extra skills
    router = make_router(reg)
    assert len(reg) in (12, 13)
    assert isinstance(router.selector, expected)


async def test_selection_is_logged(
    make_router: Callable[..., Router], synthetic_specs: list[SkillSpec], plan
) -> None:
    reg = _registry(synthetic_specs, 20, with_product=True)
    llm = FakeLLM([], default=plan())
    result = await make_router(reg).route(build_user_request("Will it rain tomorrow?"), llm)
    event = next(e for e in result.events if e.event == "candidates")
    assert event.data["selector"] == "BM25TopK"
    assert "weather_forecast" in event.data["skills"]
    assert "general_chat" in event.data["skills"]
    assert event.data["registry_size"] == 24


def test_general_chat_and_literal_names_always_included(
    synthetic_specs: list[SkillSpec],
) -> None:
    reg = _registry(synthetic_specs, 20, with_product=True)
    chosen = BM25TopK(2).select(build_user_request("use taxi ride please, rain"), reg)
    assert "general_chat" in chosen
    assert "taxi_ride" in chosen
    assert (
        BM25TopK(2)
        .select(build_user_request("please use the poem_writer skill"), reg)
        .count("poem_writer")
        == 1
    )


def _recall(selector: BM25TopK, reg: SkillRegistry, queries: list[tuple[str, str]]) -> float:
    hits = sum(gold in selector.select(build_user_request(q), reg) for q, gold in queries)
    return hits / len(queries)


def test_bm25_recall_at_k(synthetic_specs: list[SkillSpec], queries: list[tuple[str, str]]) -> None:
    """20 synthetic bilingual skills + general_chat, 40 queries (20 EN, 20 FA)."""
    assert len(queries) >= 40
    reg = _registry(synthetic_specs, 20, with_product=False)
    reg.register(make_skill_spec("general_chat", description="Small talk and fallback."))
    recall = {k: _recall(BM25TopK(k), reg, queries) for k in (3, 6, 10)}
    en = [q for q in queries if q[0].isascii()]
    fa = [q for q in queries if not q[0].isascii()]
    by_lang = {
        "en@6": _recall(BM25TopK(6), reg, en),
        "fa@6": _recall(BM25TopK(6), reg, fa),
    }
    print(f"\nBM25 recall@k over {len(queries)} queries: {recall}; {by_lang}")
    assert recall[6] >= 0.9
    assert recall[3] <= recall[6] <= recall[10]


def test_bm25_selects_product_skills_too(synthetic_specs: list[SkillSpec]) -> None:
    reg = _registry(synthetic_specs, 20, with_product=True)
    chosen = BM25TopK(6).select(build_user_request("این متن را خلاصه کن"), reg)
    assert "summarizer" in chosen
    chosen = BM25TopK(6).select(build_user_request("Translate this into French"), reg)
    assert "translator" in chosen
