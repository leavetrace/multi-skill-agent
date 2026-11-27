"""Blind A/B of text-skill prompts v1 vs v2 for the owner's Persian review (WP7a §2).

Costs real free-tier quota: one skill call per sample and version (8 × 2 = 16), ≥ 2 s
apart. Not collected by pytest (no `test_` prefix); run it explicitly:

    uv run python tests/live/run_prompt_ab.py              # live run (resumes), then build
    uv run python tests/live/run_prompt_ab.py --build-only # rebuild the sheets, 0 calls

Every finished call is appended to the raw JSONL at once, so a stopped run (quota, closed
session) resumes without repeating calls. A 429 that the gateway gives up on (a daily quota)
stops the run instead of retrying. The review sheet shows each sample's two outputs as A/B
in a seeded random order; the key (which letter is v2) is written to a separate file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from run_text_samples import RUNNERS, SAMPLES, CountingLLM, Sample

from skillagent.config import get_settings
from skillagent.core.errors import LLMRateLimitError
from skillagent.core.types import SkillInput
from skillagent.llm import OpenAICompatGateway
from skillagent.prompts import PromptLoader
from skillagent.skills.base import SkillContext

THROTTLE_S = 2.0
SEED = 20261127
ROOT = Path(__file__).resolve().parents[2]
HANDOFFS = ROOT / "docs" / "handoffs"
RAW = HANDOFFS / "WP7a_ab_raw.jsonl"
SHEET = HANDOFFS / "WP7a_persian_review.md"
KEY = HANDOFFS / "WP7a_persian_review_key.md"
TEXT_SKILLS = ("summarizer", "translator", "general_chat")

# New samples, one per target (1: EN→FA summary, 3: technical EN→FA, 4: casual FA chat).
# Original texts, unrelated to the prompts' few-shots and to the eval sets.
_RAIL_NEWS = (
    "The national rail operator announced on Thursday that ticket prices on intercity routes "
    "will rise by 9 percent from 1 February, the second increase in a year. The company said "
    "the extra revenue will pay for 40 new carriages and faster Wi-Fi on its busiest lines. "
    "Passenger groups, led by commuter advocate Hannah Weiss, criticised the decision and said "
    "that many people who travel to work every day can no longer afford the train. The "
    "transport ministry asked the operator to keep its discounts for students and pensioners, "
    "and advised regular travellers to buy annual passes before the end of January, while the "
    "old prices still apply. Officials still expect passenger numbers to grow by 5 percent "
    "this year. A parliamentary committee will question the company's chief executive next week."
)
NEW_SAMPLES: tuple[Sample, ...] = (
    Sample("n1", "summarizer", "new: EN news → FA summary (target 1, 2)",
           f"{_RAIL_NEWS}\n\nاین خبر را به فارسی خلاصه کن",
           "Summarize the news in Persian", "fa", {"output_language": "fa"}),
    Sample("n2", "translator", "new: technical EN → FA (target 3)",
           "Translate into Persian: Our open-source machine learning library now supports "
           "distributed training on multiple GPUs, and the new release cuts memory usage by "
           "30 percent. Users can download the pretrained models from the cloud and fine-tune "
           "them on their own datasets.",
           "Translate the text into Persian", "en", {"target_language": "fa"}),
    Sample("n3", "general_chat", "new: colloquial FA chat line (target 4)",
           "امروز تو جلسه حسابی ضایع شدم، رئیسم جلوی همه ازم ایراد گرفت. حوصله هیچی رو ندارم",
           "Respond to the user's feelings", "fa"),
)  # fmt: skip
AB_IDS = ("s4", "s2", "t1", "c2", "c5", "n1", "n2", "n3")


def ab_samples() -> list[Sample]:
    by_id = {s.id: s for s in (*SAMPLES, *NEW_SAMPLES)}
    return [by_id[i] for i in AB_IDS]


def _load_raw() -> dict[tuple[str, int], dict[str, Any]]:
    if not RAW.exists():
        return {}
    """The last row per (sample, version) wins: a `--rerun` after a prompt fix supersedes the
    draft output, which stays in the log as history."""
    rows = (json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line)
    return {(r["id"], r["version"]): r for r in rows}


async def _run_live(samples: list[Sample], rerun_v2: set[str]) -> None:
    settings = get_settings()
    gateway = OpenAICompatGateway(settings)  # one gateway per event loop (CONTRACTS §4)
    done = _load_raw()
    todo = [
        (s, v)
        for s in samples
        for v in (1, 2)
        if (s.id, v) not in done or (v == 2 and s.id in rerun_v2)
    ]
    print(f"{len(done)} calls already in {RAW.name}; {len(todo)} to run", flush=True)
    for i, (sample, version) in enumerate(todo):
        if i:
            await asyncio.sleep(THROTTLE_S)
        llm = CountingLLM(gateway)
        loader = PromptLoader(pinned=dict.fromkeys(TEXT_SKILLS, version))
        ctx = SkillContext(llm=llm, settings=settings, prompts=loader)
        inp = SkillInput(
            text=sample.text,
            instruction=sample.instruction,
            params=sample.params,
            response_language=sample.response_language,
        )
        start = time.perf_counter()
        try:
            result = await RUNNERS[sample.skill](inp, ctx)
        except LLMRateLimitError as exc:
            print(f"STOP: rate limit on {sample.id} v{version}: {exc}", flush=True)
            break
        row = {
            "id": sample.id,
            "version": version,
            "status": result.status,
            "output": result.output,
            "ms": round((time.perf_counter() - start) * 1000),
            "attempts": sum(r.attempts for r in llm.responses),
            "model": gateway.model,
            "meta": dict(result.meta),
        }
        with RAW.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{i + 1}/{len(todo)}] {sample.id} v{version}: {result.status}", flush=True)


def _superseded() -> int:
    lines = RAW.read_text(encoding="utf-8").splitlines() if RAW.exists() else []
    return sum(1 for line in lines if line) - len(_load_raw())


def _fence(text: str) -> str:
    return "````text\n" + text + "\n````"


def build(samples: list[Sample]) -> None:
    """Write the blind sheet and its key from the raw log (0 calls)."""
    raw = _load_raw()
    rng = random.Random(SEED)
    sheet = [
        "# WP7a — blind A/B Persian review (prompt v1 vs v2)",
        "",
        "For each sample, two outputs **A** and **B** of the same skill on the same input; one "
        "is the current prompt, one the new prompt, in random order. Please score each output "
        "1–5 (F = fluency, A = accuracy/appropriateness, N = naturalness), as in "
        "`WP3_samples_groq_scores.md`, and pick a preference. Don't open "
        "`WP7a_persian_review_key.md` or `WP7a_ab_raw.jsonl` before scoring.",
        "",
        "| Sample | Out | F | A | N | Prefer (A / B / =) | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in samples:
        sheet += [f"| {s.id} | A |  |  |  |  |  |", f"| {s.id} | B |  |  |  |  |  |"]
    key = [
        "# WP7a — key to the blind A/B review",
        "",
        f"Order drawn with `random.Random({SEED})`, one draw per sample in sheet order. "
        "Raw outputs with meta: `WP7a_ab_raw.jsonl`. The sheet shows the last output per "
        f"sample and version; {_superseded()} earlier draft-v2 outputs stay in the raw log "
        "(their `prompt_sha` differs).",
        "",
        "| Sample | A | B | v1 sha | v2 sha |",
        "|---|---|---|---|---|",
    ]
    for s in samples:
        v2_is_a = rng.random() < 0.5
        order = (2, 1) if v2_is_a else (1, 2)
        rows = [raw.get((s.id, v)) for v in order]
        sheet += [
            f"\n## {s.id} — {s.note}",
            f"Skill `{s.skill}` · instruction: {s.instruction}",
            "\n**Input**\n",
            _fence(s.text),
        ]
        for label, row in zip("AB", rows, strict=True):
            body = _fence(row["output"]) if row else "_not run_"
            status = f" (status `{row['status']}`)" if row and row["status"] != "ok" else ""
            sheet += [f"\n**{label}**{status}\n", body]
        shas = {
            v: (raw[(s.id, v)]["meta"].get("prompt_sha", "—") if (s.id, v) in raw else "—")
            for v in (1, 2)
        }
        key.append(f"| {s.id} | v{order[0]} | v{order[1]} | `{shas[1]}` | `{shas[2]}` |")
    SHEET.write_text("\n".join(sheet) + "\n", encoding="utf-8")
    KEY.write_text("\n".join(key) + "\n", encoding="utf-8")
    print(f"wrote {SHEET.name} and {KEY.name} ({len(raw)} outputs)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build-only", action="store_true", help="rebuild the sheets, 0 calls")
    parser.add_argument("--rerun-v2", default="", help="sample ids whose v2 output is redone")
    args = parser.parse_args()
    samples = ab_samples()
    if not args.build_only:
        rerun = {s.strip() for s in args.rerun_v2.split(",") if s.strip()}
        asyncio.run(_run_live(samples, rerun))
    build(samples)


if __name__ == "__main__":
    main()
