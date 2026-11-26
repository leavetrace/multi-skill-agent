"""Eval runner CLI (WP6b): `python -m eval.runner --set dev --runs 1 --label v1-baseline`.

Runs every case through the real agent (`skillagent.api.run_agent`), scores it with
`eval.metrics`, appends one JSONL line per case to `eval/reports/raw/` and writes a
markdown report to `eval/reports/`.

Free-tier rules this runner enforces (ADR-021, ADR-026, CLAUDE.md §8):
- one gateway per invocation, created inside `asyncio.run`, shared by every case;
- cases run sequentially, with a pause sized from the tokens each case actually used;
- an `LLMRateLimitError` in a trace stops the run: the report is written for the cases
  completed and marked partial. The runner never sleeps through a daily quota.
- `--set test` refuses to run without `--i-know-this-is-the-test-set` (ADR-011, ADR-023).
- `--resume <raw.jsonl>` finishes a stopped run later: cases already scored there are
  re-scored from their logged `AgentRun` (scoring is pure) instead of being paid for twice.

Exit codes: 0 complete · 2 usage/config error · 3 stopped early (partial report written).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from eval.metrics import CaseScore, RunSummary, expectation_signature, score_case, summarize_run
from eval.report import PromptInfo, ReportMeta, UsageTotals, render_report, write_report
from eval.schema import EvalCase, load_cases, render_prompt
from skillagent.api import AgentRun, run_agent
from skillagent.config import Settings
from skillagent.core.errors import ConfigError, LLMRateLimitError
from skillagent.core.language import estimate_tokens
from skillagent.core.registry import SkillRegistry
from skillagent.llm import OpenAICompatGateway, resolve_profile
from skillagent.llm.structured import complete_structured_with
from skillagent.llm.types import ChatMessage, LLMClient, LLMResponse, StructuredResult, T
from skillagent.prompts import PromptLoader
from skillagent.router import build_user_request
from skillagent.router.fast_path import try_route
from skillagent.skills.catalog import build_default_registry

__all__ = [
    "DATASETS",
    "MeteredLLM",
    "Pacer",
    "PriorCase",
    "RunnerOptions",
    "load_resume",
    "main",
    "parse_args",
    "quota_exhaustion",
    "run_eval",
]

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
TEXTS_DIR = EVAL_DIR / "texts"
DATASETS = {"dev": EVAL_DIR / "dev_set.yaml", "test": EVAL_DIR / "test_set.yaml"}
TEST_SET_FLAG = "--i-know-this-is-the-test-set"

# Groq free tier (ADR-026): 8K tokens/min and ~1K output tokens/min. Keep a margin.
DEFAULT_TPM = 7_000
DEFAULT_OUTPUT_TPM = 900
MIN_GAP_S = 2.0  # CLAUDE.md §8
DEFAULT_MAX_CALLS = 130  # WP6b live budget; override for multi-run evals
CALL_RESERVE = 4  # worst common case: router + repair + two skills
FALLBACK_TOKENS_PER_CALL = 3_000  # if a provider omits usage

EXIT_OK, EXIT_USAGE, EXIT_PARTIAL = 0, 2, 3

LLMFactory = Callable[[Settings], LLMClient]
Sleep = Callable[[float], Awaitable[None]]


# --- metering & pacing -------------------------------------------------------------------


@dataclass
class CallRecord:
    purpose: str
    ok: bool
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int | None = None
    latency_ms: float | None = None
    temperature: float | None = None
    error: str = ""


class MeteredLLM:
    """`LLMClient` proxy that records every provider-level call (repairs and failures too).

    `complete_structured` reuses the shared repair loop with `self.complete`, so each repair
    round is metered exactly like the gateway would send it.

    It is also a circuit breaker: once a call raised `LLMRateLimitError`, every later call
    fails locally without reaching the provider. The run stops after that case anyway, and
    without the breaker the router's `general_chat` fallback would spend tokens on a case
    that is discarded.
    """

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.records: list[CallRecord] = []
        self.tripped: str | None = None

    async def complete(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        purpose = str(kwargs.get("purpose", ""))
        temperature = kwargs.get("temperature")
        if self.tripped is not None:
            raise LLMRateLimitError(f"not sent: an earlier call hit the limit ({self.tripped})")
        try:
            response = await self.inner.complete(messages, **kwargs)
        except Exception as exc:
            if isinstance(exc, LLMRateLimitError):
                self.tripped = redact_ids(str(exc))[:120]
            self.records.append(
                CallRecord(
                    purpose=purpose,
                    ok=False,
                    temperature=temperature,
                    error=f"{type(exc).__name__}: {str(exc)[:200]}",
                )
            )
            raise
        self.records.append(
            CallRecord(
                purpose=purpose,
                ok=True,
                model=response.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                attempts=response.attempts,
                latency_ms=response.latency_ms,
                temperature=temperature,
            )
        )
        return response

    async def complete_structured(
        self,
        messages: list[ChatMessage],
        schema: type[T],
        *,
        validation_context: dict[str, Any] | None = None,
        max_repairs: int = 1,
        temperature: float = 0.0,
        max_tokens: int = 512,
        timeout_s: float | None = None,
        purpose: str = "",
    ) -> StructuredResult[T]:
        return await complete_structured_with(
            self.complete,
            messages,
            schema,
            validation_context=validation_context,
            max_repairs=max_repairs,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            purpose=purpose,
        )

    @property
    def calls(self) -> int:
        return len(self.records)

    def totals(self, start: int = 0) -> UsageTotals:
        records = self.records[start:]
        return UsageTotals(
            calls=len(records),
            attempts=sum(r.attempts or 1 for r in records),
            failed=sum(not r.ok for r in records),
            prompt_tokens=sum(r.prompt_tokens or 0 for r in records),
            completion_tokens=sum(r.completion_tokens or 0 for r in records),
        )


class Pacer:
    """Pause between cases. `fixed_s` (from `--throttle-s`) wins; otherwise the pause is
    sized from the tokens the case just used, so the average stays under the provider's
    tokens-per-minute and output-tokens-per-minute budgets (a token bucket)."""

    def __init__(
        self,
        fixed_s: float | None = None,
        *,
        tpm: int = DEFAULT_TPM,
        output_tpm: int = DEFAULT_OUTPUT_TPM,
        min_gap_s: float = MIN_GAP_S,
    ) -> None:
        self.fixed_s = fixed_s
        self.tpm = tpm
        self.output_tpm = output_tpm
        self.min_gap_s = min_gap_s

    def describe(self) -> str:
        if self.fixed_s is not None:
            return f"fixed {self.fixed_s:g} s between cases that called the LLM"
        return (
            f"auto: pause = tokens used × 60 / budget − case time, budgets {self.tpm} tokens/min "
            f"and {self.output_tpm} output tokens/min, at least {self.min_gap_s:g} s"
        )

    def pause_after(self, usage: UsageTotals, case_seconds: float) -> float:
        if usage.calls == 0:
            return 0.0
        if self.fixed_s is not None:
            return self.fixed_s
        total = usage.prompt_tokens + usage.completion_tokens
        if total == 0:
            total = FALLBACK_TOKENS_PER_CALL * usage.calls
        need = max(
            total * 60 / self.tpm,
            usage.completion_tokens * 60 / self.output_tpm,
        )
        return max(self.min_gap_s, need - case_seconds)


def quota_exhaustion(run: AgentRun) -> str | None:
    """The trace detail if any node failed with `LLMRateLimitError`, else None.

    Router fallbacks record `error="LLMRateLimitError"`; skill nodes and the agent wrapper
    record `"LLMRateLimitError: …"`. The gateway only raises it after its retries or for a
    `retry-after` over 60 s, i.e. when waiting longer would mean sleeping through a quota.
    """
    for event in run.trace:
        error = str(event.data.get("error") or "")
        if "LLMRateLimitError" in error:
            detail = str(event.data.get("detail") or "")
            text = f"{event.node} {event.event}: {error}" + (f": {detail}" if detail else "")
            return redact_ids(text)[:300]
    return None


_ACCOUNT_ID = re.compile(r"\borg_[A-Za-z0-9]+")
REDACTED_ID = "org_<redacted>"  # same marker as the WP0 bake-off logs


def redact_ids(text: str) -> str:
    """Provider error bodies echo the account id (`org_…`); reports, raw logs and console
    output must not carry it, so every path out of the runner goes through here."""
    return _ACCOUNT_ID.sub(REDACTED_ID, text)


@contextmanager
def redacted_logging() -> Iterator[None]:
    """Redact account ids from every log record created while the runner is active.

    The router and gateway log provider messages verbatim (`router fallback: …`); a record
    factory catches all loggers and handlers without touching code the eval does not own.
    """
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        message = record.getMessage()
        cleaned = redact_ids(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return record

    logging.setLogRecordFactory(factory)
    try:
        yield
    finally:
        logging.setLogRecordFactory(previous)


# --- options -----------------------------------------------------------------------------


@dataclass
class RunnerOptions:
    set_name: str = "dev"
    runs: int = 1
    case_ids: list[str] = field(default_factory=list)
    prompt_versions: str | None = None
    throttle_s: float | None = None
    dry_run: bool = False
    label: str = "run"
    out_dir: Path = EVAL_DIR / "reports"
    max_calls: int = DEFAULT_MAX_CALLS
    allow_test_set: bool = False
    resume: Path | None = None


def parse_args(argv: Sequence[str] | None = None) -> RunnerOptions:
    parser = argparse.ArgumentParser(
        prog="python -m eval.runner",
        description="Run the eval set through the agent and write a markdown report.",
    )
    parser.add_argument("--set", dest="set_name", choices=sorted(DATASETS), default="dev")
    parser.add_argument("--runs", type=int, default=1, help="repetitions (default 1)")
    parser.add_argument("--cases", default="", help="subset, e.g. D01,D05")
    parser.add_argument(
        "--prompt-versions",
        default=None,
        help="prompt pins passed to Settings.prompt_versions, e.g. router=1,translator=1",
    )
    parser.add_argument(
        "--throttle-s",
        type=float,
        default=None,
        help="fixed pause between cases; default: auto-sized for Groq's free tier",
    )
    parser.add_argument("--dry-run", action="store_true", help="render prompts, 0 LLM calls")
    parser.add_argument("--label", default="run", help="report file label, e.g. v1-baseline")
    parser.add_argument("--out-dir", type=Path, default=EVAL_DIR / "reports")
    parser.add_argument(
        "--max-calls",
        type=int,
        default=DEFAULT_MAX_CALLS,
        help=f"stop (partial) before a case could exceed this many LLM calls "
        f"(default {DEFAULT_MAX_CALLS})",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="raw JSONL of an earlier (stopped) run: its scored cases are reused, not re-run",
    )
    parser.add_argument(
        TEST_SET_FLAG,
        dest="allow_test_set",
        action="store_true",
        help="required with --set test: the test set is reported, never tuned on",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.throttle_s is not None and args.throttle_s < 0:
        parser.error("--throttle-s must be >= 0")
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", args.label).strip("-") or "run"
    return RunnerOptions(
        set_name=args.set_name,
        runs=args.runs,
        case_ids=[c.strip().upper() for c in args.cases.split(",") if c.strip()],
        prompt_versions=args.prompt_versions,
        throttle_s=args.throttle_s,
        dry_run=args.dry_run,
        label=label,
        out_dir=args.out_dir,
        max_calls=args.max_calls,
        allow_test_set=args.allow_test_set,
        resume=args.resume,
    )


def select_cases(cases: list[EvalCase], ids: Sequence[str]) -> list[EvalCase]:
    if not ids:
        return cases
    known = {c.id for c in cases}
    if missing := [i for i in ids if i not in known]:
        raise ValueError(f"unknown case id(s) {missing}")
    wanted = set(ids)
    return [c for c in cases if c.id in wanted]


# --- metadata ----------------------------------------------------------------------------


def prompt_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def git_state(root: Path = ROOT) -> tuple[str, bool | None]:
    """(commit sha, dirty?) of the code under test; ("unknown", None) without git."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", None
    if sha.returncode != 0:
        return "unknown", None
    return sha.stdout.strip(), bool(status.stdout.strip()) if status.returncode == 0 else None


def settings_limits(settings: Settings) -> dict[str, Any]:
    return {
        "max_skills_per_request": settings.max_skills_per_request,
        "max_parallel_steps": settings.max_parallel_steps,
        "max_waves": settings.max_waves,
        "request_deadline_s": settings.request_deadline_s,
        "max_request_tokens": settings.max_request_tokens,
        "llm_timeout_s": settings.llm_timeout_s,
        "llm_max_retries": settings.llm_max_retries,
        "llm_rpm": settings.llm_rpm,
        "router_top_k_threshold": settings.router_top_k_threshold,
    }


def prompt_infos(
    loader: PromptLoader, registry: SkillRegistry, runs: Sequence[AgentRun]
) -> list[PromptInfo]:
    """Template version + sha for the router and each skill, plus the shas seen live.

    Router: the rendered system-prompt sha from each trace `prompt` event (it varies with
    the language hints). Skills: `meta.prompt_sha` (text skills, CONTRACTS §14).
    """
    infos = []
    router_seen: Counter[str] = Counter(
        str(e.data.get("rendered_sha"))
        for run in runs
        for e in run.trace
        if e.node == "router" and e.event == "prompt"
    )
    names = ["router", *registry.names()]
    for name in names:
        if not loader.available(name):
            continue
        template = loader.load(name)
        if name == "router":
            seen = dict(router_seen.most_common())
        else:
            seen = dict(
                Counter(
                    str(r.meta["prompt_sha"])
                    for run in runs
                    for r in run.results.values()
                    if r.skill == name and r.meta.get("prompt_sha")
                ).most_common()
            )
        infos.append(
            PromptInfo(name=name, version=template.version, sha=template.sha, observed=seen)
        )
    return infos


def observed_temperatures(records: Sequence[CallRecord]) -> dict[str, float]:
    temps: dict[str, float] = {}
    for record in records:
        if record.temperature is not None:
            temps.setdefault(record.purpose or "(none)", float(record.temperature))
    return temps


# --- resume ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PriorCase:
    run: AgentRun
    usage: UsageTotals
    code_commit: str | None
    temperatures: dict[str, float] = field(default_factory=dict)


def load_resume(
    path: Path, set_name: str, prompt_shas: Mapping[str, str]
) -> dict[tuple[str, int], PriorCase]:
    """Scored cases of an earlier raw log, keyed by (case id, run index).

    Aborted (quota) lines are skipped so they run again. A line from another set, an
    unselected case or a different rendered prompt is an error: mixing them would report
    numbers for prompts that were never sent.
    """
    prior: dict[tuple[str, int], PriorCase] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("score") is None or record.get("aborted"):
            continue
        where = f"{path.name} line {number}"
        if record.get("set") != set_name:
            raise ValueError(f"{where}: set {record.get('set')!r}, not {set_name!r}")
        case_id = record["case_id"]
        if case_id not in prompt_shas:
            raise ValueError(f"{where}: case {case_id} is not selected in this invocation")
        if record.get("prompt_sha") != prompt_shas[case_id]:
            raise ValueError(f"{where}: {case_id} prompt changed since that run (sha differs)")
        prior[(case_id, int(record["run"]))] = PriorCase(
            run=AgentRun.model_validate(record["agent_run"]),
            usage=UsageTotals.model_validate(record.get("llm_usage") or {}),
            code_commit=record.get("code_commit"),
            temperatures={k: float(v) for k, v in (record.get("temperatures") or {}).items()},
        )
    return prior


# --- running -----------------------------------------------------------------------------


@dataclass
class EvalOutcome:
    summaries: list[RunSummary]
    scores: list[CaseScore]
    agent_runs: list[AgentRun]
    stop_reason: str | None = None
    resumed: int = 0
    resumed_usage: UsageTotals = field(default_factory=UsageTotals)
    temperatures: dict[str, float] = field(default_factory=dict)


def _jsonl_line(
    case: EvalCase,
    run_index: int,
    sha: str,
    run: AgentRun,
    score: CaseScore | None,
    usage: UsageTotals,
    set_name: str,
    aborted: str | None,
    *,
    code_commit: str | None = None,
    resumed_from: str | None = None,
    temperatures: Mapping[str, float] | None = None,
) -> str:
    record = {
        "set": set_name,
        "case_id": case.id,
        "run": run_index,
        "prompt_sha": sha,
        "code_commit": code_commit,
        "resumed_from": resumed_from,
        "aborted": aborted,
        "llm_usage": usage.model_dump(),
        "temperatures": dict(temperatures or {}),
        "score": score.model_dump(mode="json") if score else None,
        "agent_run": run.model_dump(mode="json"),
    }
    return redact_ids(json.dumps(record, ensure_ascii=False))


def _progress(
    score: CaseScore, i: int, n: int, run_index: int, out: TextIO, *, resumed: bool = False
) -> None:
    mark = "✓" if score.routing_correct else "✗"
    tag = " (resumed)" if resumed else ""
    line = (
        f"[run {run_index} {i}/{n}] {score.case_id}{tag} {mark} {score.got} "
        f"(want {score.expected}) calls={score.llm_calls} {score.total_ms / 1000:.1f}s"
    )
    if score.reason:
        line += f" | {score.reason}"
    print(line, file=out, flush=True)


async def run_eval(
    cases: Sequence[EvalCase],
    *,
    settings: Settings,
    llm: MeteredLLM,
    runs: int,
    set_name: str,
    pacer: Pacer,
    raw: TextIO,
    max_calls: int = DEFAULT_MAX_CALLS,
    registry: SkillRegistry | None = None,
    sleep: Sleep = asyncio.sleep,
    out: TextIO = sys.stdout,
    prior: Mapping[tuple[str, int], PriorCase] | None = None,
    resumed_from: str | None = None,
    code_commit: str | None = None,
) -> EvalOutcome:
    """Sequential runs × cases. Stops (partial) on quota exhaustion or the call cap.

    Cases found in `prior` (from `--resume`) are re-scored from their logged run and
    copied into the new raw log; they make no call and cause no pause.
    """
    registry = registry or build_default_registry()
    prior = prior or {}
    prompts = {case.id: render_prompt(case, TEXTS_DIR) for case in cases}
    summaries: list[RunSummary] = []
    scores: list[CaseScore] = []
    agent_runs: list[AgentRun] = []
    stop_reason: str | None = None
    resumed = 0
    resumed_usage = UsageTotals()
    temperatures: dict[str, float] = {}
    for run_index in range(1, runs + 1):
        run_scores: list[CaseScore] = []
        for i, case in enumerate(cases, 1):
            sha = prompt_sha(prompts[case.id])
            earlier = prior.get((case.id, run_index))
            if earlier is not None:
                score = score_case(case, earlier.run, run_index)
                run_scores.append(score)
                agent_runs.append(earlier.run)
                resumed += 1
                resumed_usage = _add_usage(resumed_usage, earlier.usage)
                line = _jsonl_line(
                    case,
                    run_index,
                    sha,
                    earlier.run,
                    score,
                    earlier.usage,
                    set_name,
                    None,
                    code_commit=earlier.code_commit,
                    resumed_from=resumed_from,
                    temperatures=earlier.temperatures,
                )
                for purpose, temp in earlier.temperatures.items():
                    temperatures.setdefault(purpose, temp)
                raw.write(line + "\n")
                _progress(score, i, len(cases), run_index, out, resumed=True)
                continue
            if llm.calls + CALL_RESERVE > max_calls:
                stop_reason = (
                    f"call budget: {llm.calls} LLM calls made; the next case could exceed "
                    f"--max-calls {max_calls} (stopped before {case.id}, run {run_index})"
                )
                break
            mark = llm.calls
            started = time.perf_counter()
            run = await run_agent(prompts[case.id], settings=settings, llm=llm, registry=registry)
            elapsed = time.perf_counter() - started
            usage = llm.totals(mark)
            case_temps = observed_temperatures(llm.records[mark:])
            for purpose, temp in case_temps.items():
                temperatures.setdefault(purpose, temp)
            exhausted = quota_exhaustion(run)
            if exhausted:
                stop_reason = (
                    f"quota/rate limit at {case.id} (run {run_index}): {exhausted}. "
                    "That case is not scored; no retry was attempted."
                )
                line = _jsonl_line(
                    case,
                    run_index,
                    sha,
                    run,
                    None,
                    usage,
                    set_name,
                    exhausted,
                    code_commit=code_commit,
                    temperatures=case_temps,
                )
                raw.write(line + "\n")
                raw.flush()
                print(f"STOP: {stop_reason}", file=out, flush=True)
                break
            score = score_case(case, run, run_index)
            run_scores.append(score)
            agent_runs.append(run)
            line = _jsonl_line(
                case,
                run_index,
                sha,
                run,
                score,
                usage,
                set_name,
                None,
                code_commit=code_commit,
                temperatures=case_temps,
            )
            raw.write(line + "\n")
            raw.flush()
            _progress(score, i, len(cases), run_index, out)
            remaining = [
                (c.id, r)
                for r in range(run_index, runs + 1)
                for c in (cases[i:] if r == run_index else cases)
                if (c.id, r) not in prior
            ]
            if remaining:
                pause = pacer.pause_after(usage, elapsed)
                if pause > 0:
                    await sleep(pause)
        summaries.append(
            summarize_run(
                run_scores,
                run=run_index,
                planned_cases=len(cases),
                partial=stop_reason is not None,
            )
        )
        scores.extend(run_scores)
        if stop_reason:
            break
    return EvalOutcome(
        summaries, scores, agent_runs, stop_reason, resumed, resumed_usage, temperatures
    )


def _add_usage(a: UsageTotals, b: UsageTotals) -> UsageTotals:
    return UsageTotals(
        **{name: getattr(a, name) + getattr(b, name) for name in UsageTotals.model_fields}
    )


def _default_llm(settings: Settings) -> LLMClient:
    return OpenAICompatGateway(settings, resolve_profile(settings))


async def _run_live(
    cases: list[EvalCase],
    opts: RunnerOptions,
    settings: Settings,
    llm_factory: LLMFactory,
    raw_path: Path,
    sleep: Sleep,
    out: TextIO,
    prior: Mapping[tuple[str, int], PriorCase],
    code_commit: str | None,
) -> tuple[EvalOutcome, MeteredLLM]:
    inner = llm_factory(settings)  # inside asyncio.run: one gateway per event loop
    metered = MeteredLLM(inner)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with raw_path.open("w", encoding="utf-8", newline="\n") as raw:
            outcome = await run_eval(
                cases,
                settings=settings,
                llm=metered,
                runs=opts.runs,
                set_name=opts.set_name,
                pacer=Pacer(opts.throttle_s),
                raw=raw,
                max_calls=opts.max_calls,
                sleep=sleep,
                out=out,
                prior=prior,
                resumed_from=_display_path(opts.resume) if opts.resume else None,
                code_commit=code_commit,
            )
    finally:
        close = getattr(inner, "aclose", None)
        if close is not None:
            await close()
    return outcome, metered


def dry_run(
    cases: Sequence[EvalCase],
    opts: RunnerOptions,
    loader: PromptLoader,
    registry: SkillRegistry,
    out: TextIO,
) -> None:
    """Rendered prompts and the plan of work; no network, no LLM call."""
    print(
        f"DRY RUN: set={opts.set_name} cases={len(cases)} runs={opts.runs} "
        f"max_calls={opts.max_calls}",
        file=out,
    )
    for name in ["router", *registry.names()]:
        if loader.available(name):
            template = loader.load(name)
            print(f"prompt {name}: v{template.version} sha {template.sha}", file=out)
    estimate = 0
    for case in cases:
        prompt = render_prompt(case, TEXTS_DIR)
        fast = try_route(build_user_request(prompt), registry)
        exp = case.expected
        calls = 0 if fast else 1
        calls += len(exp.skills or []) if exp.outcome == "plan" else 0
        estimate += calls
        route = f"fast path ({fast.rule})" if fast else "router LLM"
        preview = " ".join(prompt.split())[:70]
        print(
            f"{case.id} {case.lang:8} {case.category:10} want {expectation_signature(exp):34} "
            f"sha {prompt_sha(prompt)} ~{estimate_tokens(prompt)} tok, {route}, ~{calls} calls "
            f"| {preview}",
            file=out,
        )
    print(
        f"estimated LLM calls: ~{estimate * opts.runs} ({opts.runs} run(s)); "
        f"throttle: {Pacer(opts.throttle_s).describe()}; 0 calls made",
        file=out,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    llm_factory: LLMFactory | None = None,
    sleep: Sleep = asyncio.sleep,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    out: TextIO | None = None,
) -> int:
    with redacted_logging():
        return _main(argv, llm_factory=llm_factory, sleep=sleep, now=now, out=out or sys.stdout)


def _main(
    argv: Sequence[str] | None,
    *,
    llm_factory: LLMFactory | None,
    sleep: Sleep,
    now: Callable[[], datetime],
    out: TextIO,
) -> int:
    opts = parse_args(argv)
    if opts.set_name == "test" and not opts.allow_test_set:
        print(
            f"Refusing to run the test set without {TEST_SET_FLAG}: it is reported once per "
            "prompt version and never used for tuning (ADR-011, ADR-023). Use --set dev.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        overrides: dict[str, Any] = {}
        if opts.prompt_versions is not None:
            overrides["prompt_versions"] = opts.prompt_versions
        settings = Settings(**overrides)
        dataset = DATASETS[opts.set_name]
        cases = select_cases(load_cases(dataset), opts.case_ids)
        loader = PromptLoader(pinned=settings.prompt_versions)
        for name in settings.prompt_versions:
            loader.load(name)  # fail now on a bad pin, not in the middle of the run
        prior: dict[tuple[str, int], PriorCase] = {}
        if opts.resume is not None:
            shas = {c.id: prompt_sha(render_prompt(c, TEXTS_DIR)) for c in cases}
            prior = load_resume(opts.resume, opts.set_name, shas)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    registry = build_default_registry()

    if opts.dry_run:
        dry_run(cases, opts, loader, registry, out)
        return EXIT_OK

    started = now()
    stem = f"{opts.set_name}_{started:%Y%m%d-%H%M}_{opts.label}"
    raw_path = opts.out_dir / "raw" / f"{stem}.jsonl"
    if opts.resume is not None and raw_path.resolve() == opts.resume.resolve():
        raw_path = raw_path.with_name(f"{stem}_resumed.jsonl")
    clock = time.perf_counter()
    commit, dirty = git_state()
    try:
        outcome, metered = asyncio.run(
            _run_live(
                cases,
                opts,
                settings,
                llm_factory or _default_llm,
                raw_path,
                sleep,
                out,
                prior,
                commit,
            )
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        profile = resolve_profile(settings)
        provider, model = profile.name, settings.llm_model or profile.default_model
    except ConfigError:
        provider, model = settings.llm_provider, settings.llm_model or "unknown"
    stop_reason = outcome.stop_reason
    if stop_reason:
        stop_reason += (
            f" Finish later with the same options plus `--resume {_display_path(raw_path)}`."
        )
    meta = ReportMeta(
        title_label=opts.label,
        set_name=opts.set_name,
        dataset_path=dataset.relative_to(ROOT).as_posix(),
        dataset_cases=len(load_cases(dataset)),
        selected_cases=[c.id for c in cases],
        started_local=f"{started:%Y-%m-%d %H:%M:%S %z}",
        started_utc=f"{started.astimezone(UTC):%Y-%m-%d %H:%M:%S}",
        duration_s=time.perf_counter() - clock,
        runs_requested=opts.runs,
        provider=provider,
        model=model,
        models_observed=_models(metered, outcome.agent_runs),
        temperatures=outcome.temperatures,
        settings_limits=settings_limits(settings),
        prompt_pins=dict(settings.prompt_versions),
        prompts=prompt_infos(loader, registry, outcome.agent_runs),
        git_commit=commit,
        git_dirty=dirty,
        throttle=Pacer(opts.throttle_s).describe(),
        usage=metered.totals(),
        stop_reason=stop_reason,
        resumed_from=_display_path(opts.resume) if opts.resume else None,
        resumed_cases=outcome.resumed,
        resumed_usage=outcome.resumed_usage if outcome.resumed else None,
        resumed_commits=sorted(
            {p.code_commit or "unknown" for p in prior.values()} if outcome.resumed else set()
        ),
        raw_log=_display_path(raw_path),
    )
    text = render_report(meta, outcome.summaries, outcome.scores, cases)
    report_path = write_report(opts.out_dir / f"{stem}.md", text)
    usage = metered.totals()
    print(
        f"\nreport: {_display_path(report_path)}\nraw:    {_display_path(raw_path)}\n"
        f"LLM calls: {usage.calls} ({usage.attempts} HTTP attempts, {usage.failed} failed)",
        file=out,
    )
    for summary in outcome.summaries:
        r = summary.rates["routing"]
        print(
            f"run {summary.run}: routing-correct {r.k}/{r.n}"
            + (" (partial)" if summary.partial else ""),
            file=out,
        )
    return EXIT_PARTIAL if outcome.stop_reason else EXIT_OK


def _models(metered: MeteredLLM, runs: Sequence[AgentRun]) -> list[str]:
    """Models that answered: this invocation's calls plus router `llm` events of all runs."""
    models = {r.model for r in metered.records if r.model}
    models |= {
        str(e.data["model"])
        for run in runs
        for e in run.trace
        if e.node == "router" and e.event == "llm" and e.data.get("model")
    }
    return sorted(models)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Persian prompts on a Windows console
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(main())
