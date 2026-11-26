"""Report rendering (eval/report.py): partial runs are labelled, never silently averaged."""

from __future__ import annotations

from eval.metrics import CaseScore, summarize_run
from eval.report import ReportMeta, render_report
from eval.schema import EvalCase


def _case(case_id: str) -> EvalCase:
    return EvalCase.model_validate(
        {
            "id": case_id,
            "prompt": "hi",
            "lang": "en",
            "category": "single",
            "expected": {
                "outcome": "plan",
                "skills": ["general_chat"],
                "structure": "single",
                "response_language": "en",
            },
            "rationale": "report rendering fixture",
        }
    )


def _score(case_id: str, run: int, ok: bool) -> CaseScore:
    return CaseScore(
        case_id=case_id,
        run=run,
        lang="en",
        category="single",
        expected="general_chat@en",
        got="general_chat@en" if ok else "translator@en",
        matched="expected" if ok else None,
        routing_correct=ok,
        skill_set=ok,
        skill_set_unordered=ok,
        structure=None,
        language=True,
        params=None,
        dropped=None,
        calc=None,
        planned_skills=["general_chat"] if ok else ["translator"],
        expected_skills=["general_chat"],
        clarify_expected=False,
        clarify_predicted=False,
        route_source="llm",
        total_ms=1000,
        llm_calls=2,
        reason="" if ok else "skills translator@en ≠ general_chat@en",
    )


def _meta(**extra: object) -> ReportMeta:
    values: dict[str, object] = {
        "title_label": "unit",
        "set_name": "test",
        "dataset_path": "eval/test_set.yaml",
        "dataset_cases": 15,
        "selected_cases": ["T01", "T02"],
        "started_local": "2026-11-26 20:00:00 +0330",
        "started_utc": "2026-11-26 16:30:00",
        "duration_s": 120.0,
        "runs_requested": 2,
        "provider": "groq",
        "model": "qwen/qwen3.8-27b",
        "git_commit": "abc",
        "git_dirty": False,
        "throttle": "auto",
    }
    values.update(extra)
    return ReportMeta.model_validate(values)


def test_partial_run_is_listed_separately_and_not_averaged() -> None:
    cases = [_case("T01"), _case("T02")]
    run1 = [_score("T01", 1, True), _score("T02", 1, True)]
    run2 = [_score("T01", 2, False)]
    summaries = [
        summarize_run(run1, run=1, planned_cases=2),
        summarize_run(run2, run=2, planned_cases=2, partial=True),
    ]
    text = render_report(
        _meta(stop_reason="quota/rate limit at T02 (run 2)"), summaries, run1 + run2, cases
    )
    assert "2 requested · 1 complete · 1 partial" in text
    assert "**Stopped early:** quota/rate limit at T02 (run 2)" in text
    assert "Partial run(s) [2] are excluded from the means" in text
    # Headline mean is run 1 only (100%), not the 2/3 a naive pooled average would give.
    assert "| **Routing-correct (skill-detection accuracy)** | 100.0% | — | 2/2 |" in text
    assert "## Partial runs (not averaged)" in text
    assert "| 2 | 1/2 | 0.0% (0/1) |" in text
    assert "One case = 50.0 points (2 cases)" in text
    # Per-case table: run 2 never reached T02, so that cell is blank.
    t02 = next(line for line in text.splitlines() if line.startswith("| T02 |"))
    assert t02.count("✓") == 1 and t02.rstrip().endswith("|  |  |")


def test_no_scored_case() -> None:
    summaries = [summarize_run([], run=1, planned_cases=2, partial=True)]
    text = render_report(_meta(stop_reason="quota at T01"), summaries, [], [_case("T01")])
    assert "No case was scored." in text
