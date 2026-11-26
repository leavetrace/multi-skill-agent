"""Case scoring and aggregation (WP6b §3). Pure functions: no I/O, no LLM, no clock.

A reviewer must be able to recompute every reported number from the raw JSONL, so the
rules live here in one place and are unit-tested with hand-built `AgentRun`s.

Scoring rules, in short:
- The **effective expectation** is `expected`, unless `expected` fails the routing fields
  and an `also_ok` entry matches them; then that entry is used for every component (an
  `also_ok` match counts as correct and is reported separately).
- Routing fields are outcome, skills (ordered), structure and response language. An
  `also_ok` entry is compared only on the fields it sets (`eval/README.md`).
- **Routing-correct** = skill set + structure + language all pass. That is the headline
  "skill-detection accuracy"; params, dropped intents, calculator values and output checks
  are separate components, never folded into it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eval.checks import run_checks
from eval.schema import EvalCase, Expectation
from skillagent.api import AgentRun
from skillagent.core.language import normalize_lang_code, to_ascii_digits
from skillagent.core.types import SKILL_NAMES, RoutingDecision

__all__ = [
    "Aggregate",
    "CaseScore",
    "PrecisionRecall",
    "Rate",
    "RunSummary",
    "Stat",
    "aggregate",
    "calc_values_found",
    "expectation_signature",
    "flat_metrics",
    "matches_routing",
    "percentile",
    "plan_structure",
    "planned_skills",
    "postprocess_fired",
    "score_case",
    "signature",
    "summarize_run",
    "to_decimal",
]

PlanShape = Literal["clarify", "single", "chain", "parallel", "none"]
MULTI_STEP = ("chain", "parallel")
HEADLINE = (
    "routing",
    "skill_set",
    "skill_set_unordered",
    "structure",
    "language",
    "params",
    "dropped",
    "calc",
)


# --- plan helpers ------------------------------------------------------------------------


def planned_skills(decision: RoutingDecision | None) -> list[str]:
    """Ordered skills of the plan; `[]` for a clarification or a missing decision."""
    if decision is None or decision.needs_clarification:
        return []
    return [step.skill for step in decision.steps]


def plan_structure(decision: RoutingDecision | None) -> PlanShape:
    """`chain` when some step reads another step's output, `parallel` when all read `user`."""
    if decision is None:
        return "none"
    if decision.needs_clarification:
        return "clarify"
    if len(decision.steps) <= 1:
        return "single" if decision.steps else "none"
    return "chain" if any(s.input_from != "user" for s in decision.steps) else "parallel"


def signature(decision: RoutingDecision | None) -> str:
    """Compact plan notation (CONTRACTS §2): `a -> b`, `a + b`, `CLARIFY`, plus `@lang`."""
    if decision is None:
        return "—"
    if decision.needs_clarification:
        return f"CLARIFY@{decision.response_language}"
    joiner = " -> " if plan_structure(decision) == "chain" else " + "
    return joiner.join(planned_skills(decision)) + f"@{decision.response_language}"


def expectation_signature(exp: Expectation) -> str:
    lang = f"@{exp.response_language}" if exp.response_language else ""
    if exp.outcome == "clarify":
        return f"CLARIFY{lang}"
    if not exp.skills:
        return f"plan{lang}"
    joiner = " -> " if exp.structure == "chain" else " + "
    return joiner.join(exp.skills) + lang


def matches_routing(decision: RoutingDecision | None, exp: Expectation) -> bool:
    """Outcome, ordered skills, structure and language, on the fields `exp` sets."""
    if decision is None:
        return False
    outcome = "clarify" if decision.needs_clarification else "plan"
    if outcome != exp.outcome:
        return False
    if exp.outcome == "plan":
        if exp.skills is not None and planned_skills(decision) != exp.skills:
            return False
        if exp.structure is not None and plan_structure(decision) != exp.structure:
            return False
    return exp.response_language is None or decision.response_language == exp.response_language


# --- numbers -----------------------------------------------------------------------------


def to_decimal(value: object) -> Decimal | None:
    """Decimal from a canonical or display number: Persian digits, `٫` decimal point and
    `,`/`٬` thousands separators are accepted. Non-numbers give None."""
    text = to_ascii_digits(str(value)).strip()
    text = text.replace("٫", ".").replace(",", "").replace("٬", "").replace("_", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def calc_values_found(run: AgentRun) -> list[Decimal]:
    """Every value the calculator produced (CONTRACTS §13 `meta.calculations[*].value`)."""
    values: list[Decimal] = []
    for result in run.results.values():
        if result.skill != "calculator":
            continue
        for calc in result.meta.get("calculations") or []:
            number = to_decimal(calc.get("value")) if isinstance(calc, dict) else None
            if number is not None:
                values.append(number)
    return values


# --- per-case scoring --------------------------------------------------------------------


class CaseScore(BaseModel):
    """Everything the report needs about one case in one run (also written to the JSONL)."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    run: int
    lang: str
    category: str
    expected: str
    got: str
    matched: str | None  # "expected" | "also_ok[i]" | None
    routing_correct: bool
    skill_set: bool
    skill_set_unordered: bool
    structure: bool | None  # None: not a multi-step expectation
    language: bool
    params: bool | None
    dropped: bool | None
    calc: bool | None
    checks: dict[str, bool] = Field(default_factory=dict)
    check_details: dict[str, str] = Field(default_factory=dict)
    planned_skills: list[str]
    expected_skills: list[str]
    clarify_expected: bool
    clarify_predicted: bool
    route_source: str | None
    total_ms: float
    llm_calls: int
    postprocess_fired: list[str] = Field(default_factory=list)  # "<skill>.<flag>"
    reason: str = ""


def _effective(case: EvalCase, decision: RoutingDecision | None) -> tuple[Expectation, str | None]:
    if matches_routing(decision, case.expected):
        return case.expected, "expected"
    for i, alt in enumerate(case.also_ok):
        if matches_routing(decision, alt):
            return alt, f"also_ok[{i}]"
    return case.expected, None


def _same_value(key: str, want: object, got: object) -> bool:
    if got is None:
        return False
    if key.endswith("language"):
        try:
            return normalize_lang_code(str(want)) == normalize_lang_code(str(got))
        except ValueError:
            return False
    return str(want).strip().casefold() == str(got).strip().casefold()


def _params_ok(
    decision: RoutingDecision | None, wanted: dict[str, dict[str, object]]
) -> tuple[bool, str]:
    if decision is None:
        return False, "no decision"
    misses = []
    for skill, params in wanted.items():
        step = next((s for s in decision.steps if s.skill == skill), None)
        for key, want in params.items():
            got = step.params.get(key) if step else None
            if not _same_value(key, want, got):
                misses.append(f"{skill}.{key}={got!r}≠{want!r}")
    return not misses, ", ".join(misses)


def postprocess_fired(run: AgentRun) -> list[str]:
    """`<skill>.<flag>` for every clean-up rule that fired (CONTRACTS §14 `postprocess`).

    A fired `preamble_removed` or `think_stripped` means the model leaked text that code
    had to remove: the final response may be clean, but the prompt is not yet.
    """
    fired = []
    for result in run.results.values():
        flags = result.meta.get("postprocess")
        if isinstance(flags, dict):
            fired.extend(f"{result.skill}.{name}" for name, on in sorted(flags.items()) if on)
    return fired


def _degraded_reason(run: AgentRun) -> str:
    for event in run.trace:
        if event.event == "fallback" or (event.node == "agent" and event.event == "error"):
            detail = event.data.get("error") or ""
            return f"{event.node} {event.event}: {detail}".strip()
    return ""


def score_case(case: EvalCase, run: AgentRun, run_index: int = 1) -> CaseScore:
    """Score one `AgentRun` against its case (rules in the module docstring)."""
    decision = run.decision
    effective, matched = _effective(case, decision)
    via_alt = matched is not None and matched != "expected"
    got_skills = planned_skills(decision)
    shape = plan_structure(decision)
    clarify_expected = effective.outcome == "clarify"
    clarify_predicted = shape == "clarify"
    want_skills = list(effective.skills if effective.skills is not None else [])
    if effective.skills is None:  # partial also_ok without skills: compare with `expected`
        want_skills = list(case.expected.skills or [])

    failures: list[str] = []
    if via_alt:
        skill_set = skill_set_unordered = language = True
        structure: bool | None = True if effective.structure in MULTI_STEP else None
    else:
        exp = case.expected
        if exp.outcome == "clarify":
            skill_set = skill_set_unordered = clarify_predicted
        else:
            skill_set = not clarify_predicted and got_skills == exp.skills
            skill_set_unordered = not clarify_predicted and sorted(got_skills) == sorted(
                exp.skills or []
            )
        structure = shape == exp.structure if exp.structure in MULTI_STEP else None
        language = decision is not None and decision.response_language == exp.response_language
        if decision is None:
            failures.append(_degraded_reason(run) or "no routing decision")
        elif decision.route_source == "fallback":
            failures.append(_degraded_reason(run) or "router fallback")
        if not skill_set:
            failures.append(f"skills {signature(decision)} ≠ {expectation_signature(exp)}")
        elif structure is False:
            failures.append(f"structure {shape} ≠ {exp.structure}")
        if not language and decision is not None:
            failures.append(f"lang {decision.response_language} ≠ {exp.response_language}")
    routing_correct = skill_set and language and structure is not False

    params: bool | None = None
    if effective.params:
        params, detail = _params_ok(decision, effective.params)
        if not params:
            failures.append(f"params {detail}")

    dropped: bool | None = None
    if effective.dropped is not None:
        count = len(decision.dropped_intents) if decision else 0
        dropped = decision is not None and count == effective.dropped
        if not dropped:
            failures.append(f"dropped {count} ≠ {effective.dropped}")

    calc: bool | None = None
    if effective.calc_values:
        found = calc_values_found(run)
        missing = [v for v in effective.calc_values if to_decimal(v) not in found]
        calc = not missing
        if missing:
            failures.append(f"calc {missing} ∉ {[str(v) for v in found]}")

    results = run_checks(case.output_checks, run.response, case.must_contain_any)
    for name, result in results.items():
        if not result.passed:
            failures.append(f"{name}: {result.detail}" if result.detail else name)

    bad_steps = [
        f"{r.skill} {r.status}" + (f" ({r.error[:60]})" if r.error else "")
        for r in run.results.values()
        if r.status in ("error", "timeout")
    ]
    failures.extend(bad_steps)

    return CaseScore(
        case_id=case.id,
        run=run_index,
        lang=case.lang,
        category=case.category,
        expected=expectation_signature(case.expected),
        got=signature(decision),
        matched=matched,
        routing_correct=routing_correct,
        skill_set=skill_set,
        skill_set_unordered=skill_set_unordered,
        structure=structure,
        language=language,
        params=params,
        dropped=dropped,
        calc=calc,
        checks={name: r.passed for name, r in results.items()},
        check_details={name: r.detail for name, r in results.items() if r.detail},
        planned_skills=got_skills,
        expected_skills=want_skills,
        clarify_expected=clarify_expected,
        clarify_predicted=clarify_predicted,
        route_source=decision.route_source if decision else None,
        total_ms=run.total_ms,
        llm_calls=run.llm_calls,
        postprocess_fired=postprocess_fired(run),
        reason="; ".join(f for f in failures if f),
    )


# --- per-run summary ---------------------------------------------------------------------


class Rate(BaseModel):
    model_config = ConfigDict(frozen=True)

    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None


class PrecisionRecall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None


class RunSummary(BaseModel):
    """One run's numbers. `partial` runs stopped early (quota) and cover fewer cases."""

    run: int
    partial: bool = False
    planned_cases: int
    scored_cases: int
    rates: dict[str, Rate]
    also_ok_matches: list[str]
    per_category: dict[str, Rate]
    per_lang: dict[str, Rate]
    per_skill: dict[str, PrecisionRecall]
    clarify: PrecisionRecall
    checks: dict[str, Rate]
    route_sources: dict[str, int]
    postprocess: dict[str, int] = Field(default_factory=dict)  # flag → cases where it fired
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    calls_mean: float | None
    calls_max: int | None


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in [0, 100]); None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _rate(flags: Iterable[bool | None]) -> Rate:
    applicable = [f for f in flags if f is not None]
    return Rate(k=sum(applicable), n=len(applicable))


def _grouped(scores: Sequence[CaseScore], key: str) -> dict[str, Rate]:
    groups: dict[str, list[bool]] = {}
    for s in scores:
        groups.setdefault(getattr(s, key), []).append(s.routing_correct)
    return {name: _rate(flags) for name, flags in sorted(groups.items())}


def summarize_run(
    scores: Sequence[CaseScore],
    *,
    run: int = 1,
    planned_cases: int | None = None,
    partial: bool = False,
    skills: Sequence[str] = SKILL_NAMES,
) -> RunSummary:
    """Rates over applicable cases only (e.g. structure counts multi-step expectations)."""
    rates = {
        "routing": _rate(s.routing_correct for s in scores),
        "skill_set": _rate(s.skill_set for s in scores),
        "skill_set_unordered": _rate(s.skill_set_unordered for s in scores),
        "structure": _rate(s.structure for s in scores),
        "language": _rate(s.language for s in scores),
        "params": _rate(s.params for s in scores),
        "dropped": _rate(s.dropped for s in scores),
        "calc": _rate(s.calc for s in scores),
    }
    per_skill = {
        skill: PrecisionRecall(
            tp=sum(skill in s.planned_skills and skill in s.expected_skills for s in scores),
            fp=sum(skill in s.planned_skills and skill not in s.expected_skills for s in scores),
            fn=sum(skill not in s.planned_skills and skill in s.expected_skills for s in scores),
        )
        for skill in skills
    }
    clarify = PrecisionRecall(
        tp=sum(s.clarify_predicted and s.clarify_expected for s in scores),
        fp=sum(s.clarify_predicted and not s.clarify_expected for s in scores),
        fn=sum(not s.clarify_predicted and s.clarify_expected for s in scores),
    )
    check_names = sorted({name for s in scores for name in s.checks})
    checks = {name: _rate(s.checks.get(name) for s in scores) for name in check_names}
    sources: dict[str, int] = {}
    for s in scores:
        key = s.route_source or "none"
        sources[key] = sources.get(key, 0) + 1
    fired: dict[str, int] = {}
    for s in scores:
        for flag in set(s.postprocess_fired):
            fired[flag] = fired.get(flag, 0) + 1
    latencies = [s.total_ms for s in scores]
    calls = [s.llm_calls for s in scores]
    return RunSummary(
        run=run,
        partial=partial,
        planned_cases=planned_cases if planned_cases is not None else len(scores),
        scored_cases=len(scores),
        rates=rates,
        also_ok_matches=[
            s.case_id for s in scores if s.routing_correct and s.matched not in (None, "expected")
        ],
        per_category=_grouped(scores, "category"),
        per_lang=_grouped(scores, "lang"),
        per_skill=per_skill,
        clarify=clarify,
        checks=checks,
        route_sources=dict(sorted(sources.items())),
        postprocess=dict(sorted(fired.items())),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        calls_mean=sum(calls) / len(calls) if calls else None,
        calls_max=max(calls) if calls else None,
    )


# --- aggregation over runs ---------------------------------------------------------------


def flat_metrics(summary: RunSummary) -> dict[str, float | None]:
    """Every number of a run under a stable key, so runs can be averaged key by key."""
    out: dict[str, float | None] = {f"rate:{k}": r.value for k, r in summary.rates.items()}
    out.update({f"category:{k}": r.value for k, r in summary.per_category.items()})
    out.update({f"lang:{k}": r.value for k, r in summary.per_lang.items()})
    for skill, pr in summary.per_skill.items():
        out[f"skill:{skill}:precision"] = pr.precision
        out[f"skill:{skill}:recall"] = pr.recall
    out["clarify:precision"] = summary.clarify.precision
    out["clarify:recall"] = summary.clarify.recall
    out.update({f"check:{k}": r.value for k, r in summary.checks.items()})
    out["latency_p50_ms"] = summary.latency_p50_ms
    out["latency_p95_ms"] = summary.latency_p95_ms
    out["calls_mean"] = summary.calls_mean
    out["calls_max"] = float(summary.calls_max) if summary.calls_max is not None else None
    return out


class Stat(BaseModel):
    model_config = ConfigDict(frozen=True)

    mean: float
    lo: float
    hi: float
    runs: int


class Aggregate(BaseModel):
    """Mean and min–max per metric over the **complete** runs.

    Partial runs are never averaged with complete ones. If every run is partial (e.g. the
    only run hit the quota), the stats come from the partial runs and `from_partial` says so.
    """

    full_runs: list[int]
    partial_runs: list[int]
    from_partial: bool
    stats: dict[str, Stat]


def aggregate(summaries: Sequence[RunSummary]) -> Aggregate:
    full = [s for s in summaries if not s.partial]
    partial = [s for s in summaries if s.partial]
    used = full or partial
    collected: dict[str, list[float]] = {}
    for summary in used:
        for key, value in flat_metrics(summary).items():
            if value is not None:
                collected.setdefault(key, []).append(value)
    stats = {
        key: Stat(mean=sum(vals) / len(vals), lo=min(vals), hi=max(vals), runs=len(vals))
        for key, vals in collected.items()
    }
    return Aggregate(
        full_runs=[s.run for s in full],
        partial_runs=[s.run for s in partial],
        from_partial=not full and bool(partial),
        stats=stats,
    )
