"""Live router smoke on the dev set (WP4b §4): plan/language accuracy and prompt tokens.

Costs real free-tier quota: at most one router call (plus one repair) per dev case that
misses the fast path, throttled to stay under the provider's tokens-per-minute budget.
Not collected by pytest (no `test_` prefix); run it explicitly:

    uv run python tests/live/router_dev_smoke.py                    # all 40 dev cases
    uv run python tests/live/router_dev_smoke.py --only D01         # one calibration call
    uv run python tests/live/router_dev_smoke.py --dry-run          # no calls: fast path +
                                                                    # estimated prompt size

Reads `eval/dev_set.yaml` only; never the test set. Output is printed and, with `--out`,
written as a markdown table (UTF-8).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # `eval/` is a top-level folder, not an installed package

from eval.schema import EvalCase, Expectation, load_cases, render_prompt  # noqa: E402
from skillagent.config import get_settings  # noqa: E402
from skillagent.core.registry import SkillRegistry  # noqa: E402
from skillagent.core.types import RoutingDecision, TraceEvent  # noqa: E402
from skillagent.llm import OpenAICompatGateway  # noqa: E402
from skillagent.llm.types import ChatMessage, LLMResponse  # noqa: E402
from skillagent.prompts import PromptLoader  # noqa: E402
from skillagent.router import Router, build_user_request  # noqa: E402
from skillagent.router.fast_path import try_route  # noqa: E402
from skillagent.skills.catalog import build_default_registry  # noqa: E402

pytestmark = pytest.mark.live

DEV_SET = ROOT / "eval" / "dev_set.yaml"
TPM_BUDGET = 7_000  # Groq free tier allows 8 000 tokens/min; keep a margin
MIN_GAP_S = 2.0  # CLAUDE.md §8
OUTPUT_ALLOWANCE = 300  # completion tokens reserved per call before its usage is known


class TokenWindow:
    """Sliding 60 s window of provider tokens, so calls wait *before* a 429, not after it."""

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.spent: deque[tuple[float, int]] = deque()
        self.last_call = 0.0

    def used(self, now: float) -> int:
        while self.spent and now - self.spent[0][0] >= 60.0:
            self.spent.popleft()
        return sum(tokens for _, tokens in self.spent)

    async def wait_for(self, tokens: int) -> None:
        while True:
            now = time.monotonic()
            gap = MIN_GAP_S - (now - self.last_call)
            if gap > 0:
                await asyncio.sleep(gap)
                continue
            if not self.spent or self.used(now) + tokens <= self.budget:
                return
            # Budget-bound: sleep until the oldest call leaves the 60 s window.
            await asyncio.sleep(max(0.5, 60.0 - (now - self.spent[0][0])))

    def record(self, tokens: int) -> None:
        self.last_call = time.monotonic()
        self.spent.append((self.last_call, tokens))


class RecordingGateway:
    """Delegates to the real gateway; records every HTTP-level response (repairs included)."""

    def __init__(self, inner: OpenAICompatGateway, window: TokenWindow) -> None:
        self.inner = inner
        self.window = window
        self.responses: list[LLMResponse] = []
        inner.complete = self._complete  # type: ignore[method-assign]
        self._inner_complete = OpenAICompatGateway.complete.__get__(inner)
        self.next_estimate = 3_000

    async def _complete(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        await self.window.wait_for(self.next_estimate + OUTPUT_ALLOWANCE)
        response = await self._inner_complete(messages, **kwargs)
        usage = response.usage
        total = (usage.prompt_tokens or self.next_estimate) + (usage.completion_tokens or 0)
        self.window.record(total)
        if usage.prompt_tokens:
            self.next_estimate = usage.prompt_tokens + 100  # the user message varies
        self.responses.append(response)
        return response

    async def complete(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        return await self._complete(messages, **kwargs)

    async def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
        return await self.inner.complete_structured(*args, **kwargs)


@dataclass
class Row:
    case: EvalCase
    decision: RoutingDecision | None = None
    error: str = ""
    route_source: str = ""
    prompt_tokens: int | None = None
    est_tokens: int | None = None
    latency_ms: float = 0.0
    calls: int = 0
    plan_ok: bool = False
    lang_ok: bool = False
    matched: str = ""
    guards: list[str] = field(default_factory=list)


def structure_of(decision: RoutingDecision) -> str:
    if len(decision.steps) == 1:
        return "single"
    return "chain" if any(s.input_from != "user" for s in decision.steps) else "parallel"


def signature(decision: RoutingDecision) -> str:
    """Compact plan notation (CONTRACTS §2): `a(user) -> b(s1, k=v)`, `a + b`, CLARIFY."""
    if decision.needs_clarification:
        return f"CLARIFY({decision.response_language})"
    parts = []
    for step in decision.steps:
        args = [step.input_from, *(f"{k}={v}" for k, v in sorted(step.params.items()))]
        parts.append(f"{step.skill}({', '.join(args)})")
    joiner = " -> " if structure_of(decision) == "chain" else " + "
    return joiner.join(parts)


def plan_matches(decision: RoutingDecision, exp: Expectation) -> bool:
    """Same outcome, same ordered skills, same structure; unset (partial) fields ignored."""
    if decision.needs_clarification:
        return exp.outcome == "clarify"
    if exp.outcome != "plan":
        return False
    skills = [s.skill for s in decision.steps]
    if exp.skills is not None and skills != exp.skills:
        return False
    return exp.structure is None or exp.structure == structure_of(decision)


def lang_matches(decision: RoutingDecision, exp: Expectation) -> bool:
    return exp.response_language is None or exp.response_language == decision.response_language


def score(row: Row) -> None:
    decision = row.decision
    if decision is None:
        return
    options = [("expected", row.case.expected)] + [
        (f"also_ok[{i}]", alt) for i, alt in enumerate(row.case.also_ok)
    ]
    for name, exp in options:
        if plan_matches(decision, exp):
            row.plan_ok, row.matched = True, name
            break
    # Language: the primary expectation, or an also_ok entry that matches plan and language.
    row.lang_ok = decision.response_language == row.case.expected.response_language or any(
        plan_matches(decision, alt)
        and alt.response_language is not None
        and lang_matches(decision, alt)
        for alt in row.case.also_ok
    )


def _event(events: list[TraceEvent], name: str) -> dict[str, Any]:
    return next((e.data for e in events if e.event == name), {})


async def run(cases: list[EvalCase], dry_run: bool) -> tuple[list[Row], RecordingGateway | None]:
    settings = get_settings()
    registry: SkillRegistry = build_default_registry()
    router = Router(registry, settings, PromptLoader.from_settings(settings))
    gateway = (
        None
        if dry_run
        else RecordingGateway(OpenAICompatGateway(settings), TokenWindow(TPM_BUDGET))
    )
    rows: list[Row] = []
    for i, case in enumerate(cases, 1):
        row = Row(case)
        request = build_user_request(render_prompt(case, ROOT / "eval" / "texts"))
        _, info = router.build_messages(request, router.selector.select(request, registry))
        row.est_tokens = int(info["system_tokens"]) + int(info["user_tokens"])
        if dry_run:
            fast = try_route(request, registry)
            row.route_source = "rule" if fast else "(llm)"
            row.decision = fast.decision if fast else None
        else:
            assert gateway is not None
            start = time.perf_counter()
            try:
                result = await router.route(request, gateway)  # type: ignore[arg-type]
            except Exception as exc:  # report and continue
                row.error = f"{type(exc).__name__}: {exc}"[:200]
            else:
                row.decision = result.decision
                row.route_source = result.decision.route_source
                row.calls = result.llm_calls
                llm = _event(result.events, "llm")
                row.prompt_tokens = llm.get("prompt_tokens")
                row.latency_ms = float(llm.get("latency_ms") or 0.0)
                row.guards = [e.data.get("guard", "") for e in result.events if e.event == "guard"]
                if row.route_source == "rule":
                    row.latency_ms = (time.perf_counter() - start) * 1000
        score(row)
        rows.append(row)
        print(_line(row, i, len(cases)), flush=True)
    if gateway is not None:
        await gateway.inner.aclose()
    return rows, gateway


def _line(row: Row, i: int, n: int) -> str:
    d = row.decision
    sig = signature(d) if d else (row.error or "—")
    lang = d.response_language if d else "-"
    mark = ("PLAN✓" if row.plan_ok else "PLAN✗") + (" LANG✓" if row.lang_ok else " LANG✗")
    return (
        f"[{i}/{n}] {row.case.id} {mark} {sig} lang={lang} src={row.route_source} "
        f"prompt_tokens={row.prompt_tokens} est={row.est_tokens} "
        f"latency={row.latency_ms:.0f}ms guards={row.guards} {row.matched}"
    )


def summary(rows: list[Row], gateway: RecordingGateway | None, subset: str = "") -> str:
    scored = [r for r in rows if r.decision is not None]
    llm_rows = [r for r in rows if r.route_source == "llm"]
    fallbacks = sum(r.route_source == "fallback" for r in rows)
    tokens = [r.prompt_tokens for r in llm_rows if r.prompt_tokens]
    latencies = [r.latency_ms for r in llm_rows if r.latency_ms]
    lines = [
        f"cases{subset}: {len(rows)} (scored {len(scored)}, errors {len(rows) - len(scored)})",
        f"plan accuracy: {sum(r.plan_ok for r in rows)}/{len(rows)}",
        f"language accuracy: {sum(r.lang_ok for r in rows)}/{len(rows)}",
        f"route_source: llm {len(llm_rows)}, rule {sum(r.route_source == 'rule' for r in rows)},"
        f" fallback {fallbacks}",
        f"p50 router latency (llm cases): {statistics.median(latencies):.0f} ms"
        if latencies
        else "p50 latency: n/a",
        f"median prompt_tokens: {statistics.median(tokens):.0f}"
        if tokens
        else "prompt_tokens: n/a",
    ]
    if gateway is not None:
        attempts = sum(r.attempts for r in gateway.responses)
        lines.append(
            f"live HTTP responses: {len(gateway.responses)} (attempts incl. retries: {attempts})"
        )
    return "\n".join(lines)


def markdown(rows: list[Row], text: str) -> str:
    out = [
        f"# Router dev smoke ({time.strftime('%Y-%m-%d %H:%M')})\n",
        "| id | plan | lang | signature | resp. lang | src | prompt_tokens | latency ms | guards |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        d = r.decision
        sig = (signature(d) if d else r.error or "—").replace("|", "\\|")
        out.append(
            f"| {r.case.id} | {'✓' if r.plan_ok else '✗'} | {'✓' if r.lang_ok else '✗'} | "
            f"`{sig}` | {d.response_language if d else '-'} | {r.route_source} | "
            f"{r.prompt_tokens or ''} | {r.latency_ms:.0f} | {', '.join(r.guards)} |"
        )
    return "\n".join(out) + "\n\n```\n" + text + "\n```\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="comma-separated case ids, e.g. D01,D16")
    parser.add_argument("--dry-run", action="store_true", help="no LLM calls")
    parser.add_argument("--out", type=Path, default=None, help="write a markdown table")
    args = parser.parse_args()
    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    cases = [c for c in load_cases(DEV_SET) if not wanted or c.id in wanted]
    rows, gateway = asyncio.run(run(cases, args.dry_run))
    text = summary(rows, gateway)
    first20 = [r for r in rows if int(r.case.id[1:]) <= 20]
    if first20 and len(first20) != len(rows):
        text += "\n\n" + summary(first20, None, " D01–D20")
    print("\n" + text)
    if args.out:
        args.out.write_text(markdown(rows, text), encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
