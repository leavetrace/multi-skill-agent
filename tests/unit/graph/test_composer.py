"""Deterministic composer: shapes, failure notes, dropped notice, Persian text rules."""

from __future__ import annotations

import pytest

from skillagent.core.types import PlanStep, RoutingDecision, SkillResult
from skillagent.graph.composer import (
    APOLOGY,
    clarify_message,
    compose,
    limit_message,
    skill_label,
)


def plan(lang: str, *steps: tuple[str, str, str], dropped: list[str] | None = None):
    return RoutingDecision(
        response_language=lang,
        steps=[PlanStep(id=i, skill=s, instruction="x", input_from=f) for i, s, f in steps],
        dropped_intents=dropped or [],
    )


def res(sid: str, skill: str, status: str = "ok", output: str = "", **meta) -> SkillResult:
    return SkillResult(step_id=sid, skill=skill, status=status, output=output, meta=meta)  # type: ignore[arg-type]


def test_single_step_is_bare_output() -> None:
    d = plan("en", ("s1", "calculator", "user"))
    assert compose(d, {"s1": res("s1", "calculator", output="2+2 = 4")}, max_skills=2) == "2+2 = 4"


def test_chain_shows_only_final_output() -> None:
    d = plan("en", ("s1", "summarizer", "user"), ("s2", "translator", "s1"))
    results = {
        "s1": res("s1", "summarizer", output="summary"),
        "s2": res("s2", "translator", output="خلاصه"),
    }
    assert compose(d, results, max_skills=2) == "خلاصه"


def test_parallel_sections_in_plan_order_with_fallback_label() -> None:
    d = plan("en", ("s1", "weather_lookup", "user"), ("s2", "translator", "user"))
    results = {
        "s2": res("s2", "translator", output="Hallo"),
        "s1": res("s1", "weather_lookup", output="Sunny"),
    }
    assert compose(d, results, max_skills=2) == (
        "**weather_lookup**\nSunny\n\n**Translation**\nHallo"
    )


def test_same_skill_twice_gets_numbered_labels() -> None:
    d = plan("fa", ("s1", "translator", "user"), ("s2", "translator", "user"))
    results = {
        "s1": res("s1", "translator", output="Hallo"),
        "s2": res("s2", "translator", output="Bonjour"),
    }
    text = compose(d, results, max_skills=2)
    assert "**ترجمه (۱)**\nHallo" in text and "**ترجمه (۲)**\nBonjour" in text


def test_rejected_is_shown_as_output() -> None:
    d = plan("en", ("s1", "translator", "user"))
    out = compose(d, {"s1": res("s1", "translator", "rejected", "Which text?")}, max_skills=2)
    assert out == "Which text?"


@pytest.mark.parametrize(
    ("status", "meta", "note"),
    [
        ("error", {}, "The calculation step ran into an error, so it has no result."),
        ("timeout", {}, "The calculation step took too long and was stopped."),
        ("skipped", {"reason": "max_waves"}, "reached its time or step limit"),
    ],
)
def test_partial_failure_keeps_successes(status: str, meta: dict, note: str) -> None:
    d = plan("en", ("s1", "translator", "user"), ("s2", "calculator", "user"))
    results = {
        "s1": res("s1", "translator", output="Hallo"),
        "s2": res("s2", "calculator", status, **meta),
    }
    text = compose(d, results, max_skills=2)
    assert text.startswith("**Translation**\nHallo\n\n**Calculation**\n")
    assert note in text
    assert APOLOGY not in text


def test_nothing_succeeded_is_the_bilingual_apology_plus_notes() -> None:
    d = plan("fa", ("s1", "summarizer", "user"), ("s2", "translator", "s1"))
    results = {
        "s1": res("s1", "summarizer", "timeout"),
        "s2": res("s2", "translator", "skipped", reason="dependency"),
    }
    text = compose(d, results, max_skills=2)
    assert text.startswith(APOLOGY)
    assert "مرحلهٔ «خلاصه» بیش از حد طول کشید و متوقف شد." in text
    assert "مرحلهٔ «ترجمه» انجام نشد، چون مرحله‌ای که به آن وابسته بود موفق نبود." in text


def test_dropped_intents_notice_localized() -> None:
    d = plan("fa", ("s1", "calculator", "user"), dropped=["ترجمه به آلمانی", "نوشتن شعر"])
    text = compose(d, {"s1": res("s1", "calculator", output="۴")}, max_skills=2)
    assert text == (
        "۴\n\nتوجه: من در هر درخواست حداکثر ۲ کار را انجام می‌دهم؛ "
        "این موارد انجام نشد: ترجمه به آلمانی، نوشتن شعر."
    )
    en = compose(
        plan("de", ("s1", "calculator", "user"), dropped=["a", "b"]),
        {"s1": res("s1", "calculator", output="4")},
        max_skills=2,
    )
    assert en.endswith("Note: I handle up to 2 tasks per request, so I skipped: a; b.")


def test_messages_follow_persian_rules() -> None:
    texts = [
        APOLOGY,
        limit_message("fa", tokens=7000, limit=6000),
        clarify_message("fa", "کدام متن؟"),
        *(skill_label(s, "fa") for s in ("summarizer", "translator", "calculator", "general_chat")),
    ]
    for text in texts:
        assert "ي" not in text and "ك" not in text
    assert "۷۰۰۰" in texts[1] and "۶۰۰۰" in texts[1]
    assert "‌" in texts[2]  # ZWNJ in «پیام‌های»
    assert limit_message("en", tokens=7000, limit=6000).startswith("Your message is too long")
