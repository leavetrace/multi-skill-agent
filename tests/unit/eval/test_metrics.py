"""Case scoring and aggregation (eval/metrics.py) with hand-built `AgentRun`s."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from eval.metrics import (
    RunSummary,
    aggregate,
    calc_values_found,
    flat_metrics,
    matches_routing,
    percentile,
    plan_structure,
    score_case,
    signature,
    summarize_run,
    to_decimal,
)
from eval.schema import EvalCase, Expectation
from skillagent.api import AgentRun
from skillagent.core.types import RoutingDecision, SkillResult, TraceEvent

# --- builders ------------------------------------------------------------------------------


def case(**fields: Any) -> EvalCase:
    data: dict[str, Any] = {
        "id": "D99",
        "prompt": "test prompt",
        "lang": "en",
        "category": "single",
        "rationale": "hand-built case for metric tests",
    }
    data.update(fields)
    return EvalCase.model_validate(data)


def step(sid: str, skill: str, input_from: str = "user", **params: Any) -> dict[str, Any]:
    return {
        "id": sid,
        "skill": skill,
        "instruction": f"do {skill}",
        "input_from": input_from,
        "params": params,
    }


def decision(lang: str, *steps: dict[str, Any], **extra: Any) -> RoutingDecision:
    return RoutingDecision.model_validate(
        {"response_language": lang, "steps": list(steps), **extra}
    )


def clarify(lang: str = "en") -> RoutingDecision:
    return decision(lang, needs_clarification=True, clarification_question="What text?")


def calc_result(*values: str, step_id: str = "s1") -> SkillResult:
    calculations = [
        {"expression": "x", "label": "", "value": v, "exact": v, "error": None} for v in values
    ]
    return SkillResult(
        step_id=step_id,
        skill="calculator",
        status="ok",
        output="\n".join(values),
        output_kind="number",
        meta={"calculations": calculations, "llm_calls": 1},
    )


def agent_run(
    dec: RoutingDecision | None,
    response: str = "ok",
    results: dict[str, SkillResult] | None = None,
    *,
    total_ms: float = 1000.0,
    llm_calls: int = 2,
    trace: list[TraceEvent] | None = None,
) -> AgentRun:
    return AgentRun(
        response=response,
        decision=dec,
        results=results or {},
        trace=trace or [],
        total_ms=total_ms,
        llm_calls=llm_calls,
    )


SUMMARIZE = case(
    expected={
        "outcome": "plan",
        "skills": ["summarizer"],
        "structure": "single",
        "response_language": "en",
    },
    output_checks=["script_latin", "no_preamble"],
)
PARALLEL = case(
    category="parallel",
    expected={
        "outcome": "plan",
        "skills": ["translator", "calculator"],
        "structure": "parallel",
        "response_language": "en",
        "params": {"translator": {"target_language": "fa"}},
        "calc_values": ["1024"],
    },
)
CHAIN = case(
    category="chain",
    expected={
        "outcome": "plan",
        "skills": ["summarizer", "translator"],
        "structure": "chain",
        "response_language": "en",
        "params": {"translator": {"target_language": "fa"}},
    },
)
CLARIFY = case(
    category="clarify",
    expected={"outcome": "clarify", "response_language": "en"},
)
NO_MATCH = case(
    category="no_match",
    expected={
        "outcome": "plan",
        "skills": ["general_chat"],
        "structure": "single",
        "response_language": "en",
    },
    also_ok=[{"outcome": "clarify"}],
)
OVER_LIMIT = case(
    category="over_limit",
    expected={
        "outcome": "plan",
        "skills": ["summarizer", "translator"],
        "structure": "chain",
        "response_language": "en",
        "dropped": 1,
    },
    also_ok=[{"outcome": "plan", "skills": ["summarizer", "calculator"], "structure": "parallel"}],
)
PERSIAN_CALC = case(
    lang="fa",
    expected={
        "outcome": "plan",
        "skills": ["calculator"],
        "structure": "single",
        "response_language": "fa",
        "calc_values": ["600"],
    },
    output_checks=["script_fa"],
)


# --- plan helpers --------------------------------------------------------------------------


def test_plan_structure_and_signature() -> None:
    single = decision("en", step("s1", "summarizer"))
    chain = decision("en", step("s1", "summarizer"), step("s2", "translator", "s1"))
    par = decision("fa", step("s1", "translator"), step("s2", "calculator"))
    assert plan_structure(single) == "single"
    assert plan_structure(chain) == "chain"
    assert plan_structure(par) == "parallel"
    assert plan_structure(clarify()) == "clarify"
    assert plan_structure(None) == "none"
    assert signature(chain) == "summarizer -> translator@en"
    assert signature(par) == "translator + calculator@fa"
    assert signature(clarify()) == "CLARIFY@en"


def test_partial_expectation_compares_only_set_fields() -> None:
    any_clarify = Expectation(outcome="clarify")
    assert matches_routing(clarify("fa"), any_clarify)
    assert not matches_routing(decision("en", step("s1", "general_chat")), any_clarify)
    chat_any_lang = Expectation(outcome="plan", skills=["general_chat"])
    assert matches_routing(decision("fa", step("s1", "general_chat")), chat_any_lang)


# --- per-case scoring ----------------------------------------------------------------------


def test_correct_single_case() -> None:
    run = agent_run(decision("en", step("s1", "summarizer")), "Bees live in colonies.")
    score = score_case(SUMMARIZE, run)
    assert score.routing_correct and score.skill_set and score.language
    assert score.matched == "expected"
    assert score.structure is None  # single-step: structure is not scored on its own
    assert score.params is None and score.dropped is None and score.calc is None
    assert score.checks == {"script_latin": True, "no_preamble": True}
    assert score.reason == ""


def test_wrong_skill() -> None:
    run = agent_run(decision("en", step("s1", "general_chat")), "Bees.")
    score = score_case(SUMMARIZE, run)
    assert not score.routing_correct and not score.skill_set
    assert score.language
    assert "skills general_chat@en ≠ summarizer@en" in score.reason


def test_wrong_order_fails_ordered_but_passes_unordered() -> None:
    dec = decision(
        "en",
        step(
            "s1",
            "calculator",
        ),
        step("s2", "translator", target_language="fa"),
    )
    run = agent_run(dec, results={"s1": calc_result("1024")})
    score = score_case(PARALLEL, run)
    assert not score.skill_set and score.skill_set_unordered
    assert not score.routing_correct
    assert score.structure is True
    assert score.calc is True and score.params is True


def test_chain_expected_but_parallel_planned() -> None:
    dec = decision("en", step("s1", "summarizer"), step("s2", "translator", target_language="fa"))
    score = score_case(CHAIN, agent_run(dec))
    assert score.skill_set and score.language
    assert score.structure is False
    assert not score.routing_correct
    assert "structure parallel ≠ chain" in score.reason


def test_chain_correct_with_params() -> None:
    dec = decision(
        "en", step("s1", "summarizer"), step("s2", "translator", "s1", target_language="fa")
    )
    score = score_case(CHAIN, agent_run(dec))
    assert score.routing_correct and score.structure is True and score.params is True


def test_params_compare_language_codes_and_report_misses() -> None:
    dec = decision(
        "en", step("s1", "summarizer"), step("s2", "translator", "s1", target_language="de")
    )
    score = score_case(CHAIN, agent_run(dec))
    assert score.routing_correct  # params are a separate component
    assert score.params is False
    assert "translator.target_language='de'≠'fa'" in score.reason


def test_language_mismatch() -> None:
    score = score_case(SUMMARIZE, agent_run(decision("fa", step("s1", "summarizer")), "Bees."))
    assert score.skill_set and not score.language and not score.routing_correct
    assert "lang fa ≠ en" in score.reason


def test_also_ok_match_counts_as_correct_and_is_reported() -> None:
    score = score_case(NO_MATCH, agent_run(clarify("fa")))
    assert score.routing_correct
    assert score.matched == "also_ok[0]"
    assert score.clarify_expected and score.clarify_predicted
    summary = summarize_run([score])
    assert summary.also_ok_matches == ["D99"]
    assert summary.clarify.tp == 1 and summary.clarify.fp == 0


def test_also_ok_uses_its_own_component_expectations() -> None:
    dec = decision("en", step("s1", "summarizer"), step("s2", "calculator"))
    score = score_case(OVER_LIMIT, agent_run(dec, results={"s2": calc_result("7")}))
    assert score.routing_correct and score.matched == "also_ok[0]"
    assert score.dropped is None  # the also_ok entry sets no dropped count
    assert score.expected_skills == ["summarizer", "calculator"]


def test_clarify_cases() -> None:
    assert score_case(CLARIFY, agent_run(clarify())).routing_correct
    wrong = score_case(CLARIFY, agent_run(decision("en", step("s1", "translator"))))
    assert not wrong.routing_correct and not wrong.skill_set
    assert wrong.clarify_expected and not wrong.clarify_predicted
    over = score_case(SUMMARIZE, agent_run(clarify()))
    assert not over.routing_correct
    assert over.clarify_predicted and not over.clarify_expected
    summary = summarize_run([wrong, over])
    assert (summary.clarify.tp, summary.clarify.fp, summary.clarify.fn) == (0, 1, 1)
    assert summary.clarify.precision == 0.0 and summary.clarify.recall == 0.0


def test_dropped_intents() -> None:
    chain = [step("s1", "summarizer"), step("s2", "translator", "s1")]
    ok = decision("en", *chain, dropped_intents=["compute 3+4"])
    assert score_case(OVER_LIMIT, agent_run(ok)).dropped is True
    missing = score_case(OVER_LIMIT, agent_run(decision("en", *chain)))
    assert missing.dropped is False
    assert "dropped 0 ≠ 1" in missing.reason


def test_calculator_exactness() -> None:
    dec = decision("en", step("s1", "translator", target_language="fa"), step("s2", "calculator"))
    exact = agent_run(dec, results={"s2": calc_result("1024")})
    assert score_case(PARALLEL, exact).calc is True
    trailing_zero = agent_run(dec, results={"s2": calc_result("1024.00")})
    assert score_case(PARALLEL, trailing_zero).calc is True  # compared as Decimal
    inexact = agent_run(dec, results={"s2": calc_result("1023.99")})
    score = score_case(PARALLEL, inexact)
    assert score.calc is False
    assert "calc ['1024']" in score.reason
    no_calc = agent_run(decision("en", step("s1", "translator", target_language="fa")))
    assert score_case(PARALLEL, no_calc).calc is False


def test_persian_decimals_and_separators() -> None:
    assert to_decimal("۱۲٫۵") == Decimal("12.5")
    assert to_decimal("۴٬۸۰۰") == Decimal("4800")
    assert to_decimal("1,250.5") == Decimal("1250.5")
    assert to_decimal("abc") is None
    assert to_decimal("Infinity") is None
    run = agent_run(
        decision("fa", step("s1", "calculator")),
        "حاصل: ۶۰۰",
        results={"s1": calc_result("۶۰۰")},
    )
    assert calc_values_found(run) == [Decimal("600")]
    score = score_case(PERSIAN_CALC, run)
    assert score.calc is True and score.checks == {"script_fa": True}


def test_failed_output_check_is_reported_without_touching_routing() -> None:
    run = agent_run(decision("en", step("s1", "summarizer")), "Here is the summary: bees.")
    score = score_case(SUMMARIZE, run)
    assert score.routing_correct
    assert score.checks["no_preamble"] is False
    assert "no_preamble" in score.reason


def test_degraded_run_without_decision() -> None:
    trace = [TraceEvent(node="agent", event="error", data={"error": "RuntimeError: boom"}, t_ms=1)]
    score = score_case(SUMMARIZE, agent_run(None, "Sorry", trace=trace))
    assert not score.routing_correct and not score.skill_set and not score.language
    assert score.got == "—"
    assert "agent error: RuntimeError: boom" in score.reason


def test_router_fallback_and_skill_errors_are_named() -> None:
    trace = [TraceEvent(node="router", event="fallback", data={"error": "LLMTimeoutError"}, t_ms=1)]
    dec = decision("en", step("s1", "general_chat"), route_source="fallback")
    failed = SkillResult(step_id="s1", skill="general_chat", status="error", error="LLMError: x")
    score = score_case(SUMMARIZE, agent_run(dec, results={"s1": failed}, trace=trace))
    assert score.route_source == "fallback"
    assert "router fallback: LLMTimeoutError" in score.reason
    assert "general_chat error (LLMError: x)" in score.reason


# --- run summary & aggregation -------------------------------------------------------------


def _scores() -> list[Any]:
    return [
        score_case(
            SUMMARIZE,
            agent_run(
                decision("en", step("s1", "summarizer")), "Bees.", total_ms=1000, llm_calls=2
            ),
        ),
        score_case(
            SUMMARIZE,
            agent_run(
                decision("en", step("s1", "general_chat")), "Bees.", total_ms=3000, llm_calls=2
            ),
        ),
        score_case(CLARIFY, agent_run(clarify(), "What?", total_ms=500, llm_calls=1)),
        score_case(
            CHAIN,
            agent_run(
                decision(
                    "en",
                    step("s1", "summarizer"),
                    step("s2", "translator", "s1", target_language="fa"),
                ),
                total_ms=5000,
                llm_calls=3,
            ),
        ),
    ]


def test_summarize_run_rates_and_precision_recall() -> None:
    summary = summarize_run(_scores(), run=1)
    assert (summary.rates["routing"].k, summary.rates["routing"].n) == (3, 4)
    assert (summary.rates["structure"].k, summary.rates["structure"].n) == (1, 1)
    assert summary.rates["calc"].n == 0 and summary.rates["calc"].value is None
    summ = summary.per_skill["summarizer"]
    assert (summ.tp, summ.fp, summ.fn) == (2, 0, 1)
    assert summ.precision == 1.0 and summ.recall == pytest.approx(2 / 3)
    chat = summary.per_skill["general_chat"]
    assert (chat.tp, chat.fp, chat.fn) == (0, 1, 0)
    assert chat.recall is None  # never expected: recall undefined, not 0
    assert summary.per_category["single"].k == 1 and summary.per_category["single"].n == 2
    assert summary.checks["no_preamble"].n == 2
    assert summary.latency_p50_ms == 2000.0
    assert summary.calls_mean == 2.0 and summary.calls_max == 3
    assert summary.route_sources == {"llm": 4}


def test_percentile_interpolates() -> None:
    assert percentile([], 50) is None
    assert percentile([7.0], 95) == 7.0
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile(list(range(1, 21)), 95) == pytest.approx(19.05)


def _summary(run: int, routing_k: int, *, partial: bool = False) -> RunSummary:
    scores = _scores()[:2]
    base = summarize_run(scores, run=run, partial=partial)
    rates = dict(base.rates)
    rates["routing"] = rates["routing"].model_copy(update={"k": routing_k, "n": 4})
    return base.model_copy(update={"rates": rates})


def test_aggregate_mean_and_range_over_full_runs() -> None:
    agg = aggregate([_summary(1, 3), _summary(2, 4), _summary(3, 2)])
    stat = agg.stats["rate:routing"]
    assert stat.mean == pytest.approx(0.75) and stat.lo == 0.5 and stat.hi == 1.0
    assert stat.runs == 3
    assert agg.full_runs == [1, 2, 3] and not agg.from_partial


def test_aggregate_never_mixes_partial_with_full_runs() -> None:
    agg = aggregate([_summary(1, 4), _summary(2, 0, partial=True)])
    assert agg.stats["rate:routing"].mean == 1.0
    assert agg.partial_runs == [2] and agg.full_runs == [1]
    only_partial = aggregate([_summary(1, 2, partial=True)])
    assert only_partial.from_partial
    assert only_partial.stats["rate:routing"].mean == 0.5


def test_flat_metrics_keys_are_stable() -> None:
    keys = flat_metrics(summarize_run(_scores()))
    for key in (
        "rate:routing",
        "category:chain",
        "lang:en",
        "skill:translator:recall",
        "clarify:precision",
        "check:no_preamble",
        "latency_p95_ms",
        "calls_max",
    ):
        assert key in keys


def test_postprocess_flags_are_collected() -> None:
    summary_result = SkillResult(
        step_id="s1",
        skill="summarizer",
        status="ok",
        output="Bees.",
        meta={"postprocess": {"preamble_removed": True, "think_stripped": False}},
    )
    run = agent_run(decision("en", step("s1", "summarizer")), "Bees.", {"s1": summary_result})
    score = score_case(SUMMARIZE, run)
    assert score.postprocess_fired == ["summarizer.preamble_removed"]
    clean = score_case(SUMMARIZE, agent_run(decision("en", step("s1", "summarizer")), "Bees."))
    assert summarize_run([score, clean]).postprocess == {"summarizer.preamble_removed": 1}
