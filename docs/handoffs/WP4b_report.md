# WP4b Handoff Report — Compact router prompt

- **Agent session date:** 2026-11-26
- **Branch / worktree:** `feat/router-compact` / `.worktrees/wp4b` (Mode A, local Windows)
- **Final commit:** this report commit
- **Status:** partial. Code, tests and calibration are done. The full live dev run was started but had not finished when the session hit its usage limit, so the accuracy results below are pending.

## 1. Summary
The router prompt for the 4 real skills shrank from 3 773 to 1 877 estimated tokens (−50%). It is still rendered entirely from the registry, and every rule from WP4 §3 is kept. One live calibration call on the old v1 prompt measured 4 873 provider tokens against 3 945 estimated (system plus user message), a ratio of about 1.235. By that ratio, the new system prompt should come to about 2 320 provider tokens. The first live calls on the new prompt measured 2 442 (D01) and 2 578 (D02) provider tokens. Both of those totals include long summarization payloads in the user message. Plan and language were correct on both.

## 2. Deliverables
| Path | Purpose |
|---|---|
| `skillagent/prompts/router/v1.md` | tightened template (replaces v1 in place) |
| `skillagent/router/cards.py` | compact cards (3 Use + 2 Don't-use cues, both scripts kept), one-line params; examples: 1 JSON + compact notation; SPEC examples only for skills no router example covers |
| `skillagent/router/examples.py` | 10 policy examples (dropped the word-problem and derivative ones), `PlanExample.compact()`, `LEGEND` |
| `tests/unit/router/test_cards_prompt.py` | cue caps/bilingual selection, compact rendering, SPEC-example rule, budget test (estimate ≤ 2 000) |
| `tests/live/router_dev_smoke.py` | live dev-set smoke: per-case plan/lang/params/source/prompt_tokens, summary, TPM throttle (7K/min) |

## 3. How to verify
```
uv run pytest -q            → 1139 passed
uv run ruff check .         → All checks passed!
uv run python tests/live/router_dev_smoke.py --out docs/handoffs/WP4b_dev_smoke.md
```

## 6. Measured results
**Breakdown** (`estimate_tokens`, 4 real skills):

| Part | v1 before | compact after |
|---|---|---|
| Role, rules, schema (static template) | 837 | 603 |
| summarizer / translator / calculator / general_chat cards | 331 / 378 / 292 / 320 | 226 / 231 / 191 / 224 |
| Router examples | 1 124 (12 × JSON) | 405 (1 JSON + 9 compact) |
| SPEC examples | 472 (21) | 0 (all 4 skills covered by router examples) |
| **Total** | **3 773** | **1 877** |

The WP4 claim was partly correct. Examples dominated v1 (router + SPEC examples ≈ 42%). The translator card, not the calculator card, was the largest card.

**Template sha:** 19ad6d4e53e8 → 535b63458c5a. **rendered_sha** (for "hello", hints en/en): e71faff2726b → dcceebb1f395.

**Scalability table** (estimated tokens, all cards shown):

| Skills | synthetic only, before → after | 4 real + synthetic, before → after |
|---|---|---|
| 4 | 1 374 → 1 012 | 3 773 → 1 877 |
| 10 | 1 923 → 1 455 | 4 351 → 2 349 |
| 20 | 2 842 → 2 197 | 5 283 → 3 104 |

With 20 skills, Top-K (BM25, k = 6) brings the prompt to 2 029 estimated tokens (v1: 3 960).

**Live** (Groq `qwen/qwen3.8-27b`): one v1 calibration call (D01: 4 873 provider tokens). The full dev run on the compact prompt is pending. Its results go to `docs/handoffs/WP4b_dev_smoke.md` when it completes; they were not reviewed in this session.

## 7. Known issues
- D01–D20 accuracy (≥ 19/20 plan, 20/20 language) is **not yet verified**. If it drops, restore the dropped levers one at a time: first the third Don't-use cue (`MAX_DONT_CUES = 3`), then the word-problem example.
- The ≤ 2 500 provider-token target is not yet measured directly. It needs a short-message case (e.g. D07) from the live run to confirm.

## 9. Files touched outside my ownership
None.

## 10. Dependencies added
None.

## 12. Live LLM calls made
1 calibration call, plus the background dev run (up to about 39 calls; final count printed at the end of the run).
