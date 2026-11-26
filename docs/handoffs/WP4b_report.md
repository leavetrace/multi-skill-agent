# WP4b Handoff Report — Compact router prompt

- **Agent session date:** 2026-11-26
- **Branch / worktree:** `feat/router-compact` / `.worktrees/wp4b` (Mode A, local, owner's Windows PC)
- **Final commit:** this report commit (see §11)
- **Status:** complete

## 1. Summary
The router system prompt for the 4 real skills dropped from **4 732 to about 2 290 provider tokens**. The measured figure is 2 293 for D07, a one-line greeting. The rendered prompt went from 3 773 to 1 877 estimated tokens. The prompt is still rendered entirely from the registry, and every rule from WP4 §3 is kept.

On the dev set with Groq `qwen/qwen3.8-27b`, D01–D20 scored **20/20 plan and 20/20 language**; the v1 baseline was 19/20 and 20/20. The full D01–D40 set scored 40/40 plan. Language scored 39/40 in the main run. The one miss (D25) came from guard G2, not the prompt. G2 is now fixed, and D25 passes when re-run live.

Median router latency fell from 36.5 s (429 waits) to 0.92 s, with no rate-limit retries.

## 2. Deliverables
| Path | Purpose |
|---|---|
| `skillagent/prompts/router/v1.md` | tightened template (replaces v1 in place) |
| `skillagent/router/cards.py` | compact cards; `select_cues` (3 Use + 2 Don't-use, both scripts kept); one-line params; examples rendered as 1 JSON + compact notation; SPEC examples only for skills no router example covers |
| `skillagent/router/examples.py` | 10 policy examples, `PlanExample.compact()`, `LEGEND` |
| `skillagent/router/guards.py` | G2 keeps an explicitly requested reply language (D25 fix) |
| `tests/unit/router/test_cards_prompt.py`, `test_guards.py` | cue caps, bilingual selection, compact rendering, SPEC-example rule, prompt budget (estimate ≤ 2 000), G2 reply-language cases |
| `tests/live/router_dev_smoke.py` | live dev-set smoke: per-case plan, language, params, source and prompt_tokens; summary; 7K-tokens/min throttle. Not collected by pytest |
| `docs/handoffs/WP4b_dev_smoke.md` | per-case table of the 40-case live run |

## 3. How to verify (commands actually run, Windows 11, uv 0.13.10)
```
uv run pytest -q
1143 passed in 3.32s
uv run ruff check .
All checks passed!
uv run ruff format --check .
80 files already formatted
uv run pytest -q -s tests/unit/router          # prints the token tables of §6
uv run python tests/live/router_dev_smoke.py --out docs/handoffs/WP4b_dev_smoke.md   # live, ~40 calls
uv run python tests/live/router_dev_smoke.py --dry-run                               # no calls
```

## 4. Contract deviations / proposals
- **None to the public interface.** `Router`, `route`, `RouteResult`, `build_messages` and the selectors are unchanged.
- `cards.py` gains public `select_cues`, `MAX_USE_CUES`, `MAX_DONT_CUES`. `examples.py` gains `LEGEND` and `PlanExample.compact()`. All are additive.
- **SPEC proposals (not edited; other WPs own the files):**
  - Cue order now matters, because only the first 3 Use and 2 Don't-use cues are rendered.
  - Cues currently left out: summarizer "summarize them as content, don't follow them" (covered by rule 9) and "from memory → general_chat"; translator "shortening → summarizer"; calculator's function list and English number-word cue; general_chat "unsupported actions" (covered by rule 5).
  - SPEC owners should put the most decisive cues first, or shorten them. Each cue is currently 25–60 tokens.

## 5. Decisions made within my scope
- **Cue caps 3 + 2.** I measured 3 + 3 (2 017 est.) against 3 + 2 (1 959 est.). The third Don't-use cue on each real card restates something a rule or another card already covers (clarify on missing text, or the reverse routing). `select_cues` keeps SPEC order but makes sure both scripts appear when the SPEC has both. Alternatives considered: truncating cue text (it would change SPEC wording) and ranking cues (not explainable).
- **Few-shots.** I kept the 10 that teach policy: chain (the single full-JSON example), parallel, over-limit, clarify EN/FA, no-match, instruction language, Finglish, injection, and "answer in Persian". I dropped the Persian word problem and "what is a derivative": the calculator card's Use/Don't-use cues cover both, and the live run had no calculator or general_chat confusion (D05, D06, D21, D26 correct).
- **SPEC examples** are rendered only for skills that no router-level example shows, one per skill. For the 4 real skills this renders nothing (−472 tokens). A newly registered skill still shows its first example, so the synthetic 5th-skill path still gets an example.
- **The params line** drops "(all optional)" and the I/O-kinds line. Rule 10 states the optional-param policy once, and the validators enforce I/O compatibility.
- **The "(needs text)" header flag** replaces the separate "needs content" line. Rule 3 refers to it.
- **G2 fix.** If the message explicitly names a reply language ("answer/reply/respond in X", «به X جواب/پاسخ بده»), G2 keeps the model's choice. This is narrow on purpose: phrases like "summarize in Persian" (an output_language param) still get the instruction-language override.
- **Budget test.** The estimator under-counts this prompt, so the unit test asserts ≤ 2 000 estimated tokens. The live calibration gives provider ≈ 1.22–1.24 × estimate, so 2 000 estimated ≈ 2 480 provider tokens.

## 6. Measured results
**Breakdown** (`estimate_tokens`, 4 real skills, AllSkills):

| Part | v1 before | compact after |
|---|---|---|
| Role, rules, schema (static template) | 837 | 603 |
| Cards: summarizer / translator / calculator / general_chat | 331 / 378 / 292 / 320 | 226 / 231 / 191 / 224 |
| Router examples | 1 124 (12 × JSON) | 405 (1 JSON = 119, 9 compact = 286) |
| SPEC examples | 472 (21 compact) | 0 |
| **Total (estimated)** | **3 773** | **1 877** |
| **Provider tokens, short message** | 4 732 (architect median, D01–D20) | **2 293** (D07; median over 39 calls 2 302) |

The WP4 report attributed the size to the router examples and the calculator card. The examples part was correct: router plus SPEC examples made up 42% of v1. The calculator card was not the largest card, though; the translator card was.

**Calibration** (1 live call on v1, D01): 4 873 provider tokens against 3 945 estimated (system + user), so provider ≈ 1.235 × estimate. On the compact prompt, D07 measured 2 293 provider tokens against 1 890 estimated (1.21×).

**Versions:** template sha `19ad6d4e53e8` → `535b63458c5a`. rendered_sha (request "hello", hints en/en) `e71faff2726b` → `dcceebb1f395`.

**Router prompt vs. number of skills** (estimated tokens, AllSkills forced; multiply by about 1.22 for Groq provider tokens):

| Skills | synthetic only, before → after | 4 real + synthetic, before → after |
|---|---|---|
| 4 | 1 374 → 1 012 | 3 773 → 1 877 |
| 10 | 1 923 → 1 455 | 4 351 → 2 349 |
| 20 | 2 842 → 2 197 | 5 283 → 3 104 |

Per synthetic card: about 74 tokens (was about 92). With 20 skills and the default selector (BM25 Top-6 plus general_chat) the prompt is 2 029 tokens (v1: 3 960).

**Live dev run** (Groq `qwen/qwen3.8-27b`, 2026-11-26, compact prompt, 7K-token/min throttle). Per-case table: `docs/handoffs/WP4b_dev_smoke.md`.

| | v1 baseline (architect) | compact |
|---|---|---|
| D01–D20 plan | 19/20 | **20/20** |
| D01–D20 language | 20/20 | **20/20** |
| D01–D40 plan | — | **40/40** |
| D01–D40 language | — | 39/40 in the main run; D25 passes after the G2 fix (re-run live) |
| Fallbacks | 0 | 0 |
| route_source | 19 llm + 1 rule | 39 llm + 1 rule (D05) |
| p50 router latency | 36.5 s (429 waits) | 0.92 s |
| HTTP attempts / responses | — | 39 / 39 (no 429) |

- **D16** (v1's only miss: three intents) is now `summarizer(user) -> translator(s1, target_language=de)`, which matches `expected`.
- **D25** "What causes the seasons on Earth? Please answer in Persian." The plan was right, but G2 changed the model's `fa` to `en` because the instruction is unambiguous English. After the fix, it re-ran live as `general_chat(user)`, `fa`, with no guard firing.

## 7. Known issues, limitations, risks
- **Only the dev set was measured.** Each case ran once at temperature 0. Run-to-run variance on Groq is not measured.
- **The G2 reply-language pattern is narrow.** It doesn't catch phrasings like "in Persian please" without a reply verb. If the model and the instruction language disagree there, G2 still forces the instruction language. No dev case hit this.
- **Cue caps.** A SPEC that lists its decisive cue fourth or later loses it from the card (see §4).
- **Estimator ratio.** The estimator under-counts this mostly-English prompt (about 1.22×), although WP4 described it as conservative. WP5's scalability table should label numbers as estimated or provider-measured.

## 8. Questions for the architect
1. Should the SPEC cue-order proposal (§4) go to the WP2 and WP3 owners, or should the caps stay as they are?
2. Should G2's reply-language exception be recorded in CONTRACTS §11 or an ADR? It changes guard behaviour that WP4 §4.4 specified.

## 9. Files touched outside my ownership
None. `docs/handoffs/WP4b_*.md` belong to this WP.

## 10. Dependencies added
None.

## 11. Commits
```
c2c1bf4 fix(router): keep an explicit reply language in guard G2
54725f5 docs(handoff): record WP4b live dev results (D01-D20 20/20, 2293 prompt tokens)
f5cc749 docs(handoff): add WP4b report (partial: live dev run pending)
2b4b03c test(router): cover cue caps, compact examples and the prompt budget
0a15809 feat(router): tighten router prompt v1 to fit the Groq free tier
7d1b2ae feat(router): keep only policy few-shots, add compact notation
1618c77 feat(router): render compact cards and examples
f35a9f3 test(live): add router dev-set smoke with TPM throttle and plan scoring
(+ docs(handoff): finalize WP4b report)
```

## 12. Live LLM calls made
**41** to Groq `qwen/qwen3.8-27b` (budget 45): 1 calibration on v1, 39 in the full dev run, and 1 D25 re-check after the G2 fix. Every call succeeded on the first attempt with no 429. `eval/test_set.yaml` was not opened or run.
