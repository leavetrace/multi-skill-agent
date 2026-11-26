# WP6b Handoff Report — Evaluation runner, metrics and the dev-set baseline

- **Agent session date:** 2026-11-26
- **Branch / worktree:** `feat/eval-runner` / `.worktrees/wp6b`
- **Final commit:** `cbf6cc5` (code + partial report); this report is committed on top of it
- **Status:** partial. The runner, metrics, checks, report and tests are complete. The dev v1 baseline covers **D01–D10 only**: Groq's **daily** token quota ran out at D11. The owner said not to retry today; the resume command is in §6.3.

## 1. Summary
`python -m eval.runner` runs the dev or test set through `skillagent.api.run_agent`. It scores every case with pure, unit-tested metrics, appends one JSONL line per case per run, and writes a markdown report: header with model, temperature, limits, prompt template/rendered shas and git commit; headline mean and min–max; per category, language and skill P/R; checks; latency and calls; per-case table. One gateway serves the whole invocation. Cases run sequentially with a pause sized from the tokens each case used. The test set needs an explicit flag.

The first live run stopped exactly as the spec requires: an `LLMRateLimitError` in the trace at D11 stopped it, and the case was logged but not scored. The 429 came from Groq's **200 000 tokens/day** limit, not the per-minute one, and earlier sessions had already used ~170K of it today. In response I added three things:
- `--resume <raw.jsonl>`: re-scores the cases already logged and runs only the rest. Output is one merged raw log and one report.
- A circuit breaker: after a 429, no further calls are sent.
- `org_<redacted>` redaction of the provider account id in reports, raw logs and log output.

Measured so far: **10/10 routing-correct on D01–D10** (every component 100%). This partial slice is not a baseline accuracy, because the hard cases are D11–D40.

## 2. Deliverables
| Path | Purpose |
|---|---|
| `eval/runner.py` | CLI: `--set`, `--runs`, `--cases`, `--prompt-versions`, `--throttle-s`, `--dry-run`, `--label`, `--out-dir`, `--max-calls`, `--resume`, `--i-know-this-is-the-test-set`. `MeteredLLM` (records every provider call; circuit breaker), `Pacer`, `quota_exhaustion`, `load_resume`, `redact_ids`, `redacted_logging`. |
| `eval/metrics.py` | Pure scoring: effective expectation (`expected` or a matching `also_ok`), routing-correct, ordered/unordered skill set, structure, language, params, dropped, calculator exactness (`Decimal`, Persian digits/separators), output checks, `postprocess` leakage flags. Per-run summary (rates over applicable cases, per category/language, per-skill and clarify P/R, latency p50/p95, calls) and aggregation (mean, min–max; partial runs never averaged with complete ones). |
| `eval/checks.py` | `script_fa`, `script_latin`, `no_preamble`, `no_arabic_chars`, `not_answering_injection` |
| `eval/report.py` | Pure markdown rendering + LF writer |
| `eval/reports/dev_20261126-1913_v1-baseline.md` | Dev v1 baseline, **partial (10/40)** |
| `eval/reports/raw/.gitignore` | `*` / `!.gitignore` (see §9) |
| `eval/README.md` | Runner usage, options, behaviour, the TPD finding |
| `tests/unit/eval/test_checks.py` (39), `test_metrics.py` (24), `test_report.py` (2), `test_runner.py` (19) | Offline; FakeLLM; no network |

## 3. How to verify (commands actually run, Windows 11, owner's PC)
```
uv run pytest -q
1289 passed in 15.55s
uv run ruff check .          → All checks passed!
uv run ruff format --check . → 103 files already formatted
uv run python -m eval.runner --set dev --dry-run
… D01 … D40 (rendered-prompt sha, est. tokens, fast path or router) …
estimated LLM calls: ~83 (1 run(s)); throttle: auto: …; 0 calls made
uv run python -m eval.runner --set test
Refusing to run the test set without --i-know-this-is-the-test-set: … (exit code 2, tested)
```
The test-set flag is required even with `--dry-run` (tested). With it, `--dry-run` works and makes 0 calls.

## 4. Contract deviations / proposals
- **No contract changes.** Everything uses `run_agent`/`AgentRun` (§9), trace events, calculator meta (§13) and text-skill meta (§14) as frozen.
- **Proposal (ADR-026 amendment): record Groq's 200 000 tokens/day limit.** Measured from the 429 body on 2026-11-26: `tokens per day (TPD): Limit 200000, Used 199017, Requested 2551`. Measured cost: **~3 000 tokens per dev case** (mean 3 021, max 4 704 for the D10 chain; router prompt median 2 302 provider tokens). So:
  - one 40-case dev pass ≈ 120K tokens, more than half a day's quota;
  - the WP7 plan (dev v1 vs v2 ×3, test ×3) is roughly 360K + 135K tokens, i.e. **at least 3 days** of quota.
  - Every Groq session on the same account (CLI smoke tests, other agents) draws from the same daily pool.
  - WP7 should budget by day, use `--resume`, or cut `--runs` on dev.
- **Proposal (WP1 gateway):** provider error text reaches exceptions and logs verbatim, including the account id `org_…`. The eval redacts it on every output path. The gateway's `_redact` could also strip `org_[A-Za-z0-9]+`, so CLI `--trace` and logs are clean too.
- **Proposal (graph/router):** after a router `LLMRateLimitError`, the fallback `general_chat` step still sends a call. In run 1 it went through after an 8 s retry and spent ~800 tokens on a case that was then discarded. The eval now short-circuits that with its breaker; the CLI may want the same.

## 5. Decisions made within my scope
- **Throttle default = token bucket, not a fixed number.** After a case that called the LLM, the runner pauses for `max(tokens × 60 / 7000, completion_tokens × 60 / 900) − case time`, with a 2 s minimum. Fast-path cases cost nothing and don't pause. `--throttle-s` still gives a fixed pause. Why: a fixed ~30 s wastes time on 0-call cases and is too short for chains. Measured: no TPM 429 in the 10 live cases.
- **Exhausted case:** logged in the JSONL with `aborted`, not scored, and the run is marked partial. Scoring it would count the provider's outage as a routing failure.
- **`also_ok`:** an alternative is compared only on the routing fields it sets. When it matches, it becomes the expectation for every other component. It is listed separately in the report.
- **Routing-correct** = ordered skill set + structure (multi-step cases only) + response language. Params, dropped, calc, checks and `postprocess` flags are separate rows, never folded into the headline. An order-insensitive skill-set row is also shown.
- **`--max-calls` (default 130):** stops (partial) when the next case could exceed the cap, reserving 4 calls per case. Not in the spec; it enforces CLAUDE.md §8 mechanically.
- **`--resume`:** reuses only scored lines. It refuses lines from another set, from an unselected case, or with a different rendered-prompt sha. Old `AgentRun`s are re-scored with the current metrics, so a check fix applies to them without a new call.
- **Circuit breaker in `MeteredLLM`:** after one `LLMRateLimitError`, later calls raise locally. ADR-021 says never retry through a quota.
- **Redaction:** `org_<redacted>`, the same marker WP0 used. It is applied to each JSONL line, the report and every log record while the CLI runs (log-record factory, so no change to code the eval does not own). The two raw logs and the committed report written before this change were redacted in place.
- **Dev-set-driven check fix (D06):** the direct-path calculator answer `25 * 4 - 12 = ۸۸` has no letters, so `script_fa` said `none` and failed. When a response has no letters, digits now decide: any Persian digit → `fa`, ASCII digits only → `latin`. D06 was re-scored from its log, so no extra call.

## 6. Measured results
### 6.1 Dev v1 baseline (partial) — `eval/reports/dev_20261126-1913_v1-baseline.md`
Groq `qwen/qwen3.8-27b`, 2026-11-26 19:05–19:13 +0330. All prompts v1: router template `535b63458c5a`, rendered `dcceebb1f395` ×5 / `9316e0ffa7f8` ×4; summarizer `987b3e151b77`; translator `0b4f7564d8aa`; calculator `ef51ded6d78f`; general_chat `e24622e64c50`. Temperatures observed: router 0 and summarizer 0.3 (calibration), general_chat 0.7 (run 2). Translator 0.2 comes from its `SkillBudget`; it was not logged, because run 1 predates per-case temperature logging. Code: `skillagent/**` identical to `main` `fc1b93f` (this branch changes only `eval/**` and `tests/unit/eval/**`). D01–D10 ran at `b160363`; the report was generated at `031b2d0`.

| metric (D01–D10, 1 run) | result |
|---|---|
| **Routing-correct (skill-detection accuracy)** | **10/10** |
| Skill set exact / language | 10/10 · 10/10 |
| Structure (multi-step) | 1/1 (D10 chain) |
| Params / calculator exactness | 3/3 · 2/2 |
| Output checks | `script_fa` 4/4, `script_latin` 3/3, `no_preamble` 3/3, `no_arabic_chars` 3/3 |
| `postprocess` flags fired | none |
| Latency p50 / p95 (`total_ms`) | 1.86 s / 4.26 s |
| LLM calls per case | mean 1.8, max 3 |
| Route sources | llm 9, rule (fast path) 1 (D05) |

One case = 2.5 points of the 40-case dev set. **D11–D40 are not measured**, and they include every clarify, over-limit, injection, Finglish, parallel and edge case. 10/10 must not be quoted as the baseline.

### 6.2 Failure analysis (for WP7)
| case | what failed | cause | status |
|---|---|---|---|
| D06 | `script_fa` (first scoring) | **check**: a letterless calculator answer had no script by the letters-only rule | fixed in `checks.py`; re-scored ✓ |
| D11 | not scored | **provider quota** (TPD 429 → router fallback) | resume tomorrow |

No routing, skill or dataset failure among D01–D10. The degraded D11 answer, not scored, shows the fallback `general_chat` saying it "can't do the calculation here". That is expected for a degraded run, but WP7 may want the fallback wording to suggest retrying instead.

### 6.3 Exact command to finish D11–D40 (tomorrow, after the daily quota resets)
Run it **in the worktree before merging**, because the raw log is git-ignored and exists only there:
```
cd ".worktrees/wp6b"
uv run python -m eval.runner --set dev --runs 1 --label v1-baseline --max-calls 106 --resume eval/reports/raw/dev_20261126-1913_v1-baseline.jsonl
```
- It re-scores D01–D10 from the log (0 calls) and runs D11–D40 live: ~70 calls, ~90K tokens.
- `--max-calls 106` keeps WP6b within its 130-call budget (24 used).
- Make sure no other Groq session has used the day's quota first.
- It writes a new merged `eval/reports/dev_<date>_v1-baseline.md`. Commit it on `feat/eval-runner`; the partial report can then be deleted or kept as history.
- If it stops again, the report prints the next `--resume <new raw log>` command.
- If the branch is merged first, copy `eval/reports/raw/dev_20261126-1913_v1-baseline.jsonl` into the same path in the root checkout and run the command there.

## 7. Known issues, limitations, risks
- The baseline is partial (above). The prompt-iteration targets for WP7 cannot be listed until D11–D40 run.
- In the merged report, the code commit of the resumed D01–D10 lines shows as `unknown`: they were logged before `code_commit` was added to the JSONL. The actual commit was `b160363`, with `skillagent/**` equal to `main`. Temperatures for those lines are also not in the log; the merged report fills them from the new cases.
- The output checks are rule-based. `no_preamble` knows common EN/FA lead-ins only, and `script_*` measures the dominant script, not language quality.
- The pause between cases is an average-rate bucket. A chain still sends 3 calls back to back, and the gateway honours `retry-after` for those.
- `--runs N` repeats sequentially. On Groq's free tier, a 3-run dev pass does not fit in one day (§4).

## 8. Questions for the architect
1. Accept the ADR-026 amendment (TPD 200K, ~3K tokens per case) and re-plan WP7's run counts by day?
2. Should the gateway redact `org_…` itself (WP1 change), making the eval-side redaction a second line of defence?
3. After D11–D40 run: keep the partial report in git as history, or replace it with the merged one?

## 9. Files touched outside my ownership
None. `eval/reports/raw/.gitignore` was **force-added** (`git add -f`), because the WP1-owned root `.gitignore` already ignores `eval/reports/raw/` as a whole. The file is redundant but harmless, and keeps the folder in a fresh clone as the spec asks. The root `.gitignore` is unchanged.

## 10. Dependencies added
None.

## 11. Commits
```
cbf6cc5 fix(eval): redact account ids as org_<redacted> in reports, raw logs and log output
66c086c docs(eval): add dev v1 baseline report (partial: 10/40, Groq daily token quota)
e986157 feat(eval): log per-case temperatures so resumed reports stay complete
dc960fd fix(eval): stop sending calls after the first rate-limit error in a run
031b2d0 feat(eval): resume a quota-stopped run from its raw log and redact account ids
eaac01b fix(eval): judge the script of a letterless response by its digits
b160363 docs(eval): document the runner, its options and scoring
0c71588 test(eval): run the runner end to end offline with FakeLLM
aaa68a6 feat(eval): add runner CLI with token-sized throttle, quota stop and test-set guard
acc05b9 feat(eval): add markdown report writer with partial-run labelling
7c8def2 test(eval): score hand-built runs (order, chain/parallel, also_ok, clarify, calc)
e10ff62 feat(eval): add pure case scoring, per-run summary and run aggregation
f0dd93f test(eval): cover every output check in English and Persian
4b445f5 feat(eval): add rule-based output checks (script, preamble, Arabic letters, injection)
a16cfd7 chore(eval): keep raw run logs out of git
```
That is 15 commits plus this report's, above the WP's 6–12 target. The quota stop required the resume, breaker, temperature and redaction follow-ups. History was not rewritten.

## 12. Live LLM calls made
Groq `qwen/qwen3.8-27b`, all on 2026-11-26. **Total: 24 calls / 25 HTTP attempts, ~34.5K tokens.**

| invocation | calls (HTTP attempts) | failed | tokens (prompt + completion) |
|---|---|---|---|
| calibration (`--cases D01`, report in scratch, not committed) | 2 (2) | 0 | 3 269 + 208 |
| dev run 1 (D01–D10, stopped at D11) | 20 (21) | 1 (router 429 TPD) | 28 511 + 1 701 for D01–D10, plus the D11 fallback `general_chat` (791 total) |
| dev run 2 (`--resume`, stopped at D11 immediately) | 2 (2) | 2 (both 429) | 0 |

Remaining WP6b budget: 106 calls.
