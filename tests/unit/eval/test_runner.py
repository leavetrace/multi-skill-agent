"""Eval runner end to end, offline: FakeLLM behind the real graph, files in a temp dir."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eval.report import UsageTotals
from eval.runner import MeteredLLM, Pacer, main, parse_args, quota_exhaustion
from skillagent.api import AgentRun
from skillagent.config import Settings
from skillagent.core.errors import LLMRateLimitError
from skillagent.core.types import TraceEvent
from skillagent.llm.types import ChatMessage, LLMClient, ToolCall
from skillagent.testing import FakeLLM, FakeRule

FIXED_NOW = datetime(2026, 11, 26, 18, 30, tzinfo=UTC)

SUMMARY = "A honeybee colony works like one organism, with tasks shared by age."


def _plan(lang: str, *steps: dict[str, Any], **extra: Any) -> str:
    return json.dumps({"response_language": lang, "steps": list(steps), **extra})


def _router_reply(messages: list[ChatMessage]) -> str:
    """Route by the user message, like a well-behaved model would for D01/D05/D13."""
    user = messages[-1].get("content", "")
    if "Translate this" in user:
        return _plan(
            "en", needs_clarification=True, clarification_question="What should I translate?"
        )
    if "honeybee" in user.lower():
        step = {"id": "s1", "skill": "summarizer", "instruction": "Summarize the text."}
        return _plan("en", step)
    step = {"id": "s1", "skill": "general_chat", "instruction": "Answer the user."}
    return _plan("en", step)


def _calc_call(expression: str) -> list[ToolCall]:
    args = {"calculations": [{"expression": expression, "label": ""}]}
    return [ToolCall(id="c1", name="evaluate", arguments=args, raw_arguments=json.dumps(args))]


def _good_llm() -> FakeLLM:
    return FakeLLM(
        [
            FakeRule(match=lambda m, p: p.startswith("router"), reply=_router_reply),
            FakeRule(match=lambda m, p: p == "skill:summarizer", reply=SUMMARY),
            FakeRule(
                match=lambda m, p: p.startswith("skill:calculator"), reply=_calc_call("0.17*2340")
            ),
            FakeRule(match=lambda m, p: p == "skill:general_chat", reply="Hello! I'm fine."),
        ]
    )


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _run_main(
    argv: list[str], llm: LLMClient | None, tmp_path: Path
) -> tuple[int, str, Sleeps, list[LLMClient]]:
    out = io.StringIO()
    sleeps = Sleeps()
    made: list[LLMClient] = []

    def factory(settings: Settings) -> LLMClient:
        assert llm is not None, "no LLM may be created in this test"
        made.append(llm)
        return llm

    code = main(
        [*argv, "--out-dir", str(tmp_path)],
        llm_factory=factory,
        sleep=sleeps,
        now=lambda: FIXED_NOW,
        out=out,
    )
    return code, out.getvalue(), sleeps, made


def _jsonl(tmp_path: Path) -> list[dict[str, Any]]:
    files = list((tmp_path / "raw").glob("*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def test_end_to_end_three_dev_cases(tmp_path: Path) -> None:
    llm = _good_llm()
    code, out, sleeps, made = _run_main(
        ["--set", "dev", "--cases", "D01,D05,D13", "--label", "unit"], llm, tmp_path
    )
    assert code == 0, out
    assert len(made) == 1  # one gateway (client) for the whole invocation

    report = tmp_path / "dev_20261126-1830_unit.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "# Eval report: dev set, unit" in text
    assert "Routing-correct (skill-detection accuracy)" in text
    assert "| 100.0% | — | 3/3 |" in text
    assert "One case = 33.3 points (3 cases)" in text
    assert "router v1 `535b63458c5a`" in text
    for case_id in ("D01", "D05", "D13"):
        assert f"| {case_id} |" in text
    assert "\r\n" not in report.read_bytes().decode("utf-8")

    lines = _jsonl(tmp_path)
    assert [row["case_id"] for row in lines] == ["D01", "D05", "D13"]
    first = lines[0]
    assert set(first) >= {"case_id", "run", "prompt_sha", "agent_run", "score", "llm_usage"}
    assert len(first["prompt_sha"]) == 12
    assert first["score"]["routing_correct"] is True
    assert first["agent_run"]["response"] == SUMMARY
    assert all(row["aborted"] is None for row in lines)

    # D01 made LLM calls, so a pause followed it; the last case is never followed by one.
    assert sleeps.calls and all(s >= 2.0 for s in sleeps.calls)
    assert "routing-correct 3/3" in out


def test_quota_exhaustion_stops_and_writes_partial_report(tmp_path: Path) -> None:
    llm = FakeLLM(
        [
            FakeRule(match=lambda m, p: p.startswith("router"), reply=_router_reply, times=1),
            FakeRule(match=lambda m, p: p == "skill:summarizer", reply=SUMMARY),
            FakeRule(
                match=lambda m, p: True,
                reply=LLMRateLimitError("rate limited by provider (provider asks to wait 3600s)"),
            ),
        ]
    )
    code, out, _, _ = _run_main(
        ["--set", "dev", "--cases", "D01,D07,D09", "--runs", "2"], llm, tmp_path
    )
    assert code == 3
    assert "STOP: quota/rate limit at D07 (run 1)" in out

    lines = _jsonl(tmp_path)
    assert [row["case_id"] for row in lines] == ["D01", "D07"]
    assert lines[1]["score"] is None and "LLMRateLimitError" in lines[1]["aborted"]
    # D09 and run 2 never started: no further provider call after the stop.
    assert sum(1 for c in llm.calls if c.purpose.startswith("router")) == 2

    text = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "**Stopped early:** quota/rate limit at D07" in text
    assert "**Partial:** every run stopped early" in text
    assert "run 1: 1/3" in text
    assert "| 1 requested" not in text and "2 requested · 0 complete · 1 partial" in text


def test_call_budget_stops_before_overrun(tmp_path: Path) -> None:
    code, out, _, _ = _run_main(
        ["--set", "dev", "--cases", "D01,D07,D09", "--max-calls", "6"], _good_llm(), tmp_path
    )
    assert code == 3
    lines = _jsonl(tmp_path)
    # 2 calls per case; before D09, 4 made + 4 reserved > 6, so D09 never starts.
    assert [row["case_id"] for row in lines] == ["D01", "D07"]
    text = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "call budget" in text


def test_test_set_requires_the_explicit_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _, made = _run_main(["--set", "test"], None, tmp_path)
    assert code == 2 and not made
    assert "--i-know-this-is-the-test-set" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
    code, out, _, made = _run_main(
        ["--set", "test", "--i-know-this-is-the-test-set", "--dry-run"], None, tmp_path
    )
    assert code == 0 and not made
    assert "T01" in out


def test_dry_run_makes_no_calls_and_writes_nothing(tmp_path: Path) -> None:
    code, out, sleeps, made = _run_main(["--set", "dev", "--dry-run"], None, tmp_path)
    assert code == 0
    assert not made and not sleeps.calls
    assert not list(tmp_path.iterdir())
    assert "D40" in out and "0 calls made" in out
    assert "D05" in out and "fast path" in out


def test_bad_arguments_exit_2(tmp_path: Path) -> None:
    assert _run_main(["--cases", "D99"], None, tmp_path)[0] == 2
    assert _run_main(["--prompt-versions", "router=9"], None, tmp_path)[0] == 2
    assert _run_main(["--prompt-versions", "router"], None, tmp_path)[0] == 2


def test_parse_args_defaults_and_label() -> None:
    opts = parse_args(["--label", "v1 baseline/x", "--cases", "d01, D05"])
    assert opts.set_name == "dev" and opts.runs == 1 and opts.throttle_s is None
    assert opts.label == "v1-baseline-x"
    assert opts.case_ids == ["D01", "D05"]
    with pytest.raises(SystemExit):
        parse_args(["--runs", "0"])


# --- pieces --------------------------------------------------------------------------------


def test_pacer() -> None:
    auto = Pacer(tpm=7000, output_tpm=900)
    assert auto.pause_after(UsageTotals(), 1.0) == 0.0  # no LLM call (fast path)
    usage = UsageTotals(calls=2, prompt_tokens=3200, completion_tokens=300)
    assert auto.pause_after(usage, 5.0) == pytest.approx(3500 * 60 / 7000 - 5.0)
    heavy_output = UsageTotals(calls=1, prompt_tokens=100, completion_tokens=900)
    assert auto.pause_after(heavy_output, 0.0) == pytest.approx(60.0)
    assert auto.pause_after(UsageTotals(calls=1, prompt_tokens=10), 30.0) == 2.0  # min gap
    assert Pacer(12.5).pause_after(usage, 99.0) == 12.5
    assert "auto" in auto.describe() and "fixed 12.5 s" in Pacer(12.5).describe()


def _run_with(event: TraceEvent) -> AgentRun:
    return AgentRun(response="", decision=None, results={}, trace=[event], total_ms=1, llm_calls=1)


@pytest.mark.parametrize(
    ("event", "found"),
    [
        (
            TraceEvent(
                node="router",
                event="fallback",
                data={"error": "LLMRateLimitError", "detail": "wait 3600s"},
                t_ms=1,
            ),
            True,
        ),
        (
            TraceEvent(
                node="skill:translator",
                event="end",
                data={"status": "error", "error": "LLMRateLimitError: quota"},
                t_ms=1,
            ),
            True,
        ),
        (
            TraceEvent(node="agent", event="error", data={"error": "LLMRateLimitError: x"}, t_ms=1),
            True,
        ),
        (
            TraceEvent(node="router", event="fallback", data={"error": "LLMTimeoutError"}, t_ms=1),
            False,
        ),
        (TraceEvent(node="skill:translator", event="end", data={"error": None}, t_ms=1), False),
    ],
)
def test_quota_exhaustion_detection(event: TraceEvent, found: bool) -> None:
    assert (quota_exhaustion(_run_with(event)) is not None) is found


async def test_metered_llm_records_calls_repairs_and_failures() -> None:
    from pydantic import BaseModel

    class Out(BaseModel):
        x: int

    inner = FakeLLM(
        [
            FakeRule(match="first", reply="not json", times=1),
            FakeRule(match="repair|first", reply='{"x": 1}'),
            FakeRule(match="boom", reply=LLMRateLimitError("quota")),
        ]
    )
    metered = MeteredLLM(inner)
    result = await metered.complete_structured(
        [{"role": "user", "content": "first"}], Out, purpose="router", temperature=0.0
    )
    assert result.value.x == 1 and result.repairs == 1
    with pytest.raises(LLMRateLimitError):
        await metered.complete([{"role": "user", "content": "boom"}], purpose="skill:x")
    totals = metered.totals()
    assert totals.calls == 3 and totals.failed == 1
    assert [r.purpose for r in metered.records] == ["router", "router:repair", "skill:x"]
    assert metered.records[0].temperature == 0.0


# --- resume and redaction ----------------------------------------------------------------


def test_resume_reuses_scored_cases_and_reruns_aborted_ones(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    quota = FakeLLM(
        [
            FakeRule(match=lambda m, p: p.startswith("router"), reply=_router_reply, times=1),
            FakeRule(match=lambda m, p: p == "skill:summarizer", reply=SUMMARY),
            FakeRule(match=lambda m, p: True, reply=LLMRateLimitError("quota org_abc123XYZ")),
        ]
    )
    code, *_ = _run_main(["--cases", "D01,D07,D09", "--label", "base"], quota, first_dir)
    assert code == 3
    raw = next((first_dir / "raw").glob("*.jsonl"))
    report = next(first_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "org_abc123XYZ" not in report and "org_<redacted>" in report  # account id
    assert "org_abc123XYZ" not in raw.read_text(encoding="utf-8")  # raw log redacted too
    assert f"--resume {raw.as_posix()}" in report

    second_dir = tmp_path / "second"
    good = _good_llm()
    code, out, _, _ = _run_main(
        ["--cases", "D01,D07,D09", "--label", "base", "--resume", str(raw)], good, second_dir
    )
    assert code == 0, out
    assert "D01 (resumed) ✓" in out
    routed = [c for c in good.calls if c.purpose.startswith("router")]
    assert len(routed) == 2  # only D07 and D09 ran; D01 came from the first log
    lines = _jsonl(second_dir)
    assert [row["case_id"] for row in lines] == ["D01", "D07", "D09"]
    assert lines[0]["resumed_from"] == raw.as_posix()
    assert lines[1]["resumed_from"] is None and lines[1]["code_commit"]
    assert lines[0]["temperatures"] == {"router": 0.0, "skill:summarizer": 0.3}
    text = next(second_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "| Resumed | 1 case-runs re-scored from" in text
    assert "skill:summarizer 0.3" in text  # resumed D01's temperatures are reported too
    assert "routing-correct 3/3" in out


def test_resume_rejects_a_changed_prompt_or_other_set(tmp_path: Path) -> None:
    code, *_ = _run_main(["--cases", "D01", "--label", "x"], _good_llm(), tmp_path / "a")
    assert code == 0
    raw = next((tmp_path / "a" / "raw").glob("*.jsonl"))
    record = json.loads(raw.read_text(encoding="utf-8"))
    record["prompt_sha"] = "000000000000"
    edited = tmp_path / "edited.jsonl"
    edited.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert _run_main(["--cases", "D01", "--resume", str(edited)], None, tmp_path / "b")[0] == 2
    # The resumed log names D01, which is not among the selected cases.
    assert _run_main(["--cases", "D07", "--resume", str(raw)], None, tmp_path / "c")[0] == 2


async def test_metered_llm_trips_after_a_rate_limit() -> None:
    inner = FakeLLM(
        [
            FakeRule(match="first", reply=LLMRateLimitError("quota org_secret1"), times=1),
            FakeRule(match=".*", reply="fine"),
        ]
    )
    metered = MeteredLLM(inner)
    with pytest.raises(LLMRateLimitError):
        await metered.complete([{"role": "user", "content": "first"}], purpose="router")
    with pytest.raises(LLMRateLimitError, match="not sent"):
        await metered.complete([{"role": "user", "content": "second"}], purpose="skill:x")
    assert len(inner.calls) == 1  # the second call never reached the provider
    assert metered.calls == 1
    assert metered.tripped is not None and "org_secret1" not in metered.tripped


def test_log_records_are_redacted_while_the_runner_is_active(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from eval.runner import redacted_logging

    logger = logging.getLogger("skillagent.router")
    with caplog.at_level(logging.WARNING), redacted_logging():
        logger.warning("router fallback: %s", "429 in organization `org_01abcDEF` on TPD")
    logger.warning("outside: org_keepme")  # the factory is restored afterwards
    messages = [r.getMessage() for r in caplog.records]
    assert messages[0] == "router fallback: 429 in organization `org_<redacted>` on TPD"
    assert "org_keepme" in messages[-1]
