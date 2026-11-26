"""Markdown report for one eval invocation (WP6b §4).

Rendering is pure (`render_report` returns a string) so tests can assert on it; the
runner owns the file system. Only measured numbers appear: every cell comes from a
`RunSummary`, an `Aggregate` or a `CaseScore`, and empty applicability is shown as "n/a".
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from eval.metrics import (
    HEADLINE,
    Aggregate,
    CaseScore,
    RunSummary,
    aggregate,
    expectation_signature,
)
from eval.schema import EvalCase

__all__ = ["PromptInfo", "ReportMeta", "UsageTotals", "render_report", "write_report"]

_HEADLINE_LABELS = {
    "routing": "**Routing-correct (skill-detection accuracy)**",
    "skill_set": "Skill set exact (ordered)",
    "skill_set_unordered": "Skill set (order-insensitive)",
    "structure": "Structure (multi-step cases)",
    "language": "Response language",
    "params": "Params (listed keys only)",
    "dropped": "Dropped-intent count",
    "calc": "Calculator exactness",
}


class PromptInfo(BaseModel):
    name: str
    version: int | None
    sha: str | None
    observed: dict[str, int] = Field(default_factory=dict)  # sha seen in trace/meta → count


class UsageTotals(BaseModel):
    calls: int = 0  # completed or failed provider calls, as seen by the eval's meter
    attempts: int = 0  # HTTP attempts incl. gateway retries (429/5xx/timeouts)
    failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ReportMeta(BaseModel):
    title_label: str
    set_name: str
    dataset_path: str
    dataset_cases: int
    selected_cases: list[str]
    started_local: str
    started_utc: str
    duration_s: float
    runs_requested: int
    provider: str
    model: str
    models_observed: list[str] = Field(default_factory=list)
    temperatures: dict[str, float] = Field(default_factory=dict)
    settings_limits: dict[str, Any] = Field(default_factory=dict)
    prompt_pins: dict[str, int] = Field(default_factory=dict)
    prompts: list[PromptInfo] = Field(default_factory=list)
    git_commit: str
    git_dirty: bool | None
    throttle: str
    usage: UsageTotals = Field(default_factory=UsageTotals)
    stop_reason: str | None = None
    raw_log: str = ""
    resumed_from: str | None = None
    resumed_cases: int = 0
    resumed_usage: UsageTotals | None = None
    resumed_commits: list[str] = Field(default_factory=list)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value / 1000:.2f} s"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _stat_cells(agg: Aggregate, key: str, fmt: Any = _pct) -> tuple[str, str]:
    stat = agg.stats.get(key)
    if stat is None:
        return "n/a", "n/a"
    if stat.runs == 1:
        return fmt(stat.mean), "—"
    return fmt(stat.mean), f"{fmt(stat.lo)} – {fmt(stat.hi)}"


def _fractions(summaries: Sequence[RunSummary], pick: Any) -> str:
    parts = []
    for s in summaries:
        rate = pick(s)
        parts.append("n/a" if rate is None or rate.n == 0 else f"{rate.k}/{rate.n}")
    return " · ".join(parts)


def _header(meta: ReportMeta, summaries: Sequence[RunSummary], agg: Aggregate) -> list[str]:
    complete = len(agg.full_runs)
    partial = len(agg.partial_runs)
    prompts = []
    for p in meta.prompts:
        seen = ", ".join(f"`{sha}` ×{n}" for sha, n in p.observed.items())
        prompts.append(
            f"{p.name} v{p.version} `{p.sha}`" + (f" (observed: {seen})" if seen else "")
        )
    temps = " · ".join(f"{k} {v:g}" for k, v in sorted(meta.temperatures.items()))
    limits = " · ".join(f"{k}={v}" for k, v in meta.settings_limits.items())
    pins = ", ".join(f"{k}={v}" for k, v in meta.prompt_pins.items()) or "none (latest)"
    u = meta.usage
    dirty = {True: " (uncommitted changes)", False: " (clean)", None: ""}[meta.git_dirty]
    observed = ", ".join(meta.models_observed) or "none (no live call)"
    lines = [
        f"# Eval report: {meta.set_name} set, {meta.title_label}",
        "",
        "| | |",
        "|---|---|",
        f"| Date | {meta.started_local} (local) · {meta.started_utc} (UTC) |",
        f"| Set | `{meta.set_name}` (`{meta.dataset_path}`, {len(meta.selected_cases)} of "
        f"{meta.dataset_cases} cases) |",
        f"| Runs | {meta.runs_requested} requested · {complete} complete · {partial} partial |",
        f"| Provider / model | {meta.provider} / `{meta.model}` (observed: {observed}) |",
        f"| Temperature (observed per call purpose, all scored cases) | {temps or 'n/a'} |",
        f"| Settings limits | {limits} |",
        f"| Prompt pins | {pins} |",
        f"| Prompts (version, template sha; observed shas) | {'<br>'.join(prompts)} |",
        f"| Code | git `{meta.git_commit}`{dirty} |",
        f"| Live LLM usage | {u.calls} calls ({u.attempts} HTTP attempts incl. retries, "
        f"{u.failed} failed) · {u.prompt_tokens} prompt + {u.completion_tokens} completion "
        "tokens |",
        f"| Throttle | {meta.throttle} |",
        f"| Wall clock (this invocation) | {meta.duration_s / 60:.1f} min |",
        f"| Raw log | `{meta.raw_log}` (not committed) |",
    ]
    if meta.resumed_from:
        r = meta.resumed_usage or UsageTotals()
        commits = ", ".join(f"`{c}`" for c in meta.resumed_commits)
        lines.append(
            f"| Resumed | {meta.resumed_cases} case-runs re-scored from `{meta.resumed_from}` "
            f"(code {commits}; their LLM usage: {r.calls} calls, {r.attempts} attempts, "
            f"{r.prompt_tokens} + {r.completion_tokens} tokens). Live usage above covers this "
            "invocation only. |"
        )
    lines.append("")
    n = len(meta.selected_cases)
    if n:
        lines.append(
            f"> One case = {100 / n:.1f} points ({n} cases). Measured numbers only. "
            "Free endpoints are nondeterministic even at temperature 0."
        )
    if meta.stop_reason:
        lines.append(f">\n> **Stopped early:** {meta.stop_reason}")
    if agg.from_partial:
        scored = ", ".join(f"run {s.run}: {s.scored_cases}/{s.planned_cases}" for s in summaries)
        lines.append(
            f">\n> **Partial:** every run stopped early, so the numbers below cover only the "
            f"cases completed ({scored})."
        )
    elif agg.partial_runs:
        lines.append(
            f">\n> **Partial run(s) {agg.partial_runs} are excluded from the means** "
            f"(only complete runs {agg.full_runs} are averaged); their numbers are listed "
            "separately below."
        )
    return [*lines, ""]


def _headline(summaries: Sequence[RunSummary], agg: Aggregate) -> list[str]:
    used = [s for s in summaries if s.run in (agg.full_runs or agg.partial_runs)]
    lines = [
        "## Headline",
        "",
        "| metric | mean | min – max | per run (k/n applicable) |",
        "|---|---|---|---|",
    ]
    for key in HEADLINE:
        mean, span = _stat_cells(agg, f"rate:{key}")
        frac = _fractions(used, lambda s, k=key: s.rates.get(k))
        lines.append(f"| {_HEADLINE_LABELS[key]} | {mean} | {span} | {frac} |")
    also = " · ".join(f"run {s.run}: {', '.join(s.also_ok_matches) or 'none'}" for s in used)
    lines += [
        "",
        f"`also_ok` matches (counted as correct, listed here): {also}",
        "",
    ]
    return lines


def _grouped_table(
    title: str, field: str, summaries: Sequence[RunSummary], agg: Aggregate, prefix: str
) -> list[str]:
    used = [s for s in summaries if s.run in (agg.full_runs or agg.partial_runs)]
    names = sorted({name for s in used for name in getattr(s, field)})
    lines = [
        f"## {title}",
        "",
        "| group | routing-correct mean | min – max | per run (k/n) |",
        "|---|---|---|---|",
    ]
    for name in names:
        mean, span = _stat_cells(agg, f"{prefix}:{name}")
        frac = _fractions(used, lambda s, n=name: getattr(s, field).get(n))
        lines.append(f"| {name} | {mean} | {span} | {frac} |")
    return [*lines, ""]


def _skills(summaries: Sequence[RunSummary], agg: Aggregate) -> list[str]:
    used = [s for s in summaries if s.run in (agg.full_runs or agg.partial_runs)]
    lines = [
        "## Per-skill precision / recall (planned vs expected skill sets)",
        "",
        "| skill | precision | min – max | recall | min – max | TP/FP/FN per run |",
        "|---|---|---|---|---|---|",
    ]
    skills = sorted({name for s in used for name in s.per_skill})
    for skill in skills:
        p, p_span = _stat_cells(agg, f"skill:{skill}:precision")
        r, r_span = _stat_cells(agg, f"skill:{skill}:recall")
        counts = " · ".join(
            f"{pr.tp}/{pr.fp}/{pr.fn}" for s in used if (pr := s.per_skill.get(skill))
        )
        lines.append(f"| {skill} | {p} | {p_span} | {r} | {r_span} | {counts} |")
    p, p_span = _stat_cells(agg, "clarify:precision")
    r, r_span = _stat_cells(agg, "clarify:recall")
    counts = " · ".join(f"{s.clarify.tp}/{s.clarify.fp}/{s.clarify.fn}" for s in used)
    lines.append(f"| *clarify* | {p} | {p_span} | {r} | {r_span} | {counts} |")
    return [*lines, ""]


def _checks(summaries: Sequence[RunSummary], agg: Aggregate) -> list[str]:
    used = [s for s in summaries if s.run in (agg.full_runs or agg.partial_runs)]
    names = sorted({name for s in used for name in s.checks})
    lines = [
        "## Output checks (on the final response)",
        "",
        "| check | pass rate | min – max | per run (k/n) |",
        "|---|---|---|---|",
    ]
    for name in names:
        mean, span = _stat_cells(agg, f"check:{name}")
        frac = _fractions(used, lambda s, n=name: s.checks.get(n))
        lines.append(f"| `{name}` | {mean} | {span} | {frac} |")
    return [*lines, ""]


def _postprocess(summaries: Sequence[RunSummary], agg: Aggregate) -> list[str]:
    used = [s for s in summaries if s.run in (agg.full_runs or agg.partial_runs)]
    flags = sorted({flag for s in used for flag in s.postprocess})
    lines = [
        "## Skill clean-up flags fired (CONTRACTS §14 `postprocess`)",
        "",
        "Cases in which code had to clean a skill's raw model output. The final response "
        "can pass every check while these still count prompt leakage.",
        "",
    ]
    if not flags:
        return [*lines, "None fired.", ""]
    lines += ["| skill.flag | cases per run |", "|---|---|"]
    for flag in flags:
        counts = " · ".join(f"{s.postprocess.get(flag, 0)}/{s.scored_cases}" for s in used)
        lines.append(f"| `{flag}` | {counts} |")
    return [*lines, ""]


def _latency(summaries: Sequence[RunSummary], agg: Aggregate) -> list[str]:
    used = [s for s in summaries if s.run in (agg.full_runs or agg.partial_runs)]
    rows = [
        ("Latency p50 (`total_ms`)", "latency_p50_ms", _ms),
        ("Latency p95 (`total_ms`)", "latency_p95_ms", _ms),
        ("LLM calls per case, mean", "calls_mean", _num),
        ("LLM calls per case, max", "calls_max", lambda v: _num(v, 0)),
    ]
    lines = ["## Latency and LLM calls", "", "| metric | mean | min – max |", "|---|---|---|"]
    for label, key, fmt in rows:
        mean, span = _stat_cells(agg, key, fmt)
        lines.append(f"| {label} | {mean} | {span} |")
    sources = " · ".join(
        f"run {s.run}: " + ", ".join(f"{k} {v}" for k, v in s.route_sources.items()) for s in used
    )
    lines += [
        "",
        f"Route sources: {sources}. Latency includes waits on provider `retry-after` "
        "inside a case, not the throttle pause between cases.",
        "",
    ]
    return lines


def _partial_runs(summaries: Sequence[RunSummary], agg: Aggregate) -> list[str]:
    if agg.from_partial or not agg.partial_runs:
        return []
    lines = [
        "## Partial runs (not averaged)",
        "",
        "| run | cases scored | routing-correct |",
        "|---|---|---|",
    ]
    for s in summaries:
        if s.partial:
            r = s.rates["routing"]
            lines.append(
                f"| {s.run} | {s.scored_cases}/{s.planned_cases} | {_pct(r.value)} ({r.k}/{r.n}) |"
            )
    return [*lines, ""]


def _other_ok(score: CaseScore) -> bool:
    parts = [score.params, score.dropped, score.calc, *score.checks.values()]
    return all(p is not False for p in parts)


def _cases(
    cases: Sequence[EvalCase], scores: Sequence[CaseScore], summaries: Sequence[RunSummary]
) -> list[str]:
    runs = [s.run for s in summaries]
    by_key = {(s.case_id, s.run): s for s in scores}
    head = "| id | lang | category | expected | " + " | ".join(f"run {r}" for r in runs)
    head += " | reason (failures) |"
    lines = [
        "## Per-case results",
        "",
        "Routing ✓/✗ = skill set + structure + language; the second mark covers params, "
        "dropped intents, calculator values and output checks (· = nothing to check). "
        "`(alt)` = matched an `also_ok` entry. Blank = not run (stopped early).",
        "",
        head,
        "|" + "---|" * (5 + len(runs)),
    ]
    for case in cases:
        cells = []
        reasons: list[str] = []
        for r in runs:
            score = by_key.get((case.id, r))
            if score is None:
                cells.append("")
                continue
            route = "✓" if score.routing_correct else "✗"
            extra_checks = [score.params, score.dropped, score.calc, *score.checks.values()]
            if all(p is None for p in extra_checks):
                other = "·"
            else:
                other = "✓" if _other_ok(score) else "✗"
            alt = " (alt)" if score.matched not in (None, "expected") else ""
            cells.append(f"`{_cell(score.got)}` {route}{other}{alt}")
            if score.reason and score.reason not in reasons:
                reasons.append(score.reason)
        if not any(cells):
            continue
        row = (
            f"| {case.id} | {case.lang} | {case.category} | `{_cell(_expected_cell(case))}` | "
            + " | ".join(cells)
            + f" | {_cell(' ‖ '.join(reasons))} |"
        )
        lines.append(row)
    return [*lines, ""]


def _expected_cell(case: EvalCase) -> str:
    alts = [expectation_signature(a) for a in case.also_ok]
    base = expectation_signature(case.expected)
    return base + (f" (or {', '.join(alts)})" if alts else "")


def render_report(
    meta: ReportMeta,
    summaries: Sequence[RunSummary],
    scores: Sequence[CaseScore],
    cases: Sequence[EvalCase],
) -> str:
    agg = aggregate(summaries)
    parts: list[str] = _header(meta, summaries, agg)
    if not summaries or all(s.scored_cases == 0 for s in summaries):
        parts += ["No case was scored.", ""]
        return "\n".join(parts)
    parts += _headline(summaries, agg)
    parts += _grouped_table("Per category", "per_category", summaries, agg, "category")
    parts += _grouped_table("Per prompt language", "per_lang", summaries, agg, "lang")
    parts += _skills(summaries, agg)
    parts += _checks(summaries, agg)
    parts += _postprocess(summaries, agg)
    parts += _latency(summaries, agg)
    parts += _partial_runs(summaries, agg)
    parts += _cases(cases, scores, summaries)
    return "\n".join(parts).rstrip() + "\n"


def write_report(path: Path, text: str) -> Path:
    """UTF-8 with LF newlines on every OS (the repo's `.gitattributes` expects LF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path
