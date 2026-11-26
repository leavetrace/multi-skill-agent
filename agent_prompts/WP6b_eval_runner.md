# WP6b — Evaluation runner, metrics and the dev-set baseline

You are an **ML evaluation engineer**. The brief requires "a small evaluation set of 10–15 sample prompts … and the skill-detection accuracy you achieved", and reviewers will judge whether the numbers are honest and reproducible. The datasets exist (WP6a), the agent runs end to end (`skillagent.api.run_agent`, WP5). You build the runner, the metrics and the report, and you produce the **dev-set baseline** for prompt v1. No prior conversation context exists; everything you need is here and in the repo.

## 0. Read first
`CLAUDE.md` · `docs/ARCHITECTURE.md` §9 · `docs/DECISIONS.md` ADR-011, ADR-021 (rate limits: never sleep through quotas), ADR-023, ADR-026 · `docs/CONTRACTS.md` v1.4 §1 (`RoutingDecision`), §7 (prompt pinning), §9 (`run_agent`, `AgentRun`), §13 (calculator meta), §14 (text-skill meta) · `eval/README.md`, `eval/schema.py` (case schema, `render_prompt`, output-check names) · `skillagent/api.py`, `skillagent/graph/` (trace events) · `docs/handoffs/WP5_report.md` §6

Branch `feat/eval-runner`, worktree `.worktrees/wp6b`, from `main` after WP4b, WP5 and `fix/review-followups` are merged.
**You own:** `eval/**` except `eval/test_set.yaml`, `eval/dev_set.yaml` and `eval/texts/**` (frozen data: read only), plus `tests/unit/eval/**`.

## 1. Files
```
eval/
  runner.py      # CLI entry: python -m eval.runner ...
  metrics.py     # pure functions: case scoring + aggregation (no I/O, no LLM)
  checks.py      # output checks: script_fa, script_latin, no_preamble, no_arabic_chars, not_answering_injection
  report.py      # markdown report writer
  reports/       # committed markdown summaries
  reports/raw/   # JSONL per run; add eval/reports/raw/.gitignore containing "*" and "!.gitignore"
tests/unit/eval/test_metrics.py, test_checks.py, test_runner.py   # offline, FakeLLM
```

## 2. Runner (`python -m eval.runner`)
`--set dev|test` · `--runs N` (default 1) · `--cases D01,D05` (subset) · `--prompt-versions router=1,translator=1` (passed to `Settings.prompt_versions`) · `--throttle-s` (seconds between cases, default sized for Groq: see below) · `--dry-run` (render prompts and print the plan of work, 0 calls).
- **Test-set guard:** `--set test` also requires `--i-know-this-is-the-test-set`. The test set is reported, never used for tuning (ADR-011, ADR-023). The flag makes accidental runs impossible.
- **One gateway per run** (ADR-021): create it inside the `asyncio.run` and pass it to every `run_agent(..., llm=gw)` call. Cases run **sequentially** (free tier).
- **Throttle:** Groq's free tier allows ~8K tokens/min and ~1K output tokens/min (ADR-026). A case costs about 2.3K router tokens plus a skill call. Default to a pause that keeps you under ~7K tokens/min; honour `retry-after` (the gateway does).
- **Quota exhaustion:** `run_agent` never raises on provider errors; it returns a degraded run. Detect exhaustion from the trace (a router `fallback` or skill `error` whose error names `LLMRateLimitError`). When it happens, **stop the run**, mark it partial, and still write the report for the cases completed. Never sleep and retry through a daily quota.
- **Raw log:** one JSONL line per case per run: case id, run index, rendered prompt sha, full `AgentRun` (`model_dump(mode="json")`), and the scored result.

## 3. Metrics (`metrics.py`, pure, unit-tested)
Per case, compare `AgentRun.decision` with `expected`, accepting any `also_ok` entry (an `also_ok` match counts as correct and is reported separately):
- **Skill-set exact match:** ordered list of planned skills (`[]` for clarify) equals `expected.skills`; for clarify cases, `needs_clarification`.
- **Structure:** single / chain (some step has `input_from` ≠ "user") / parallel; only for multi-step expectations.
- **Response language:** `decision.response_language == expected.response_language`.
- **Params:** only keys present in `expected.params` are checked.
- **Dropped:** `len(decision.dropped_intents) == expected.dropped` when set.
- **Calculator exactness:** every `calc_values` entry appears among the calculator result's `meta["calculations"][*]["value"]` (CONTRACTS §13); compare as `Decimal`.
- **Output checks** on `AgentRun.response` (definitions in `eval/README.md`).
- Per-skill **precision/recall** over the planned skill sets; **clarify precision/recall**.
- **Latency** p50/p95 of `total_ms`; **LLM calls** per case (mean, max).
- **Aggregation over runs:** mean and min–max for every rate. Never average a partial run with full runs without saying so.
A case is **routing-correct** when skill set, structure and language all pass (or an `also_ok` entry matches). Report that as the headline "skill-detection accuracy", and also each component on its own.

## 4. Report (`report.py` → `eval/reports/<set>_<YYYYMMDD-HHMM>_<label>.md`)
Header: date/time (local and UTC), set, runs, model id, provider, temperature, `Settings` limits, prompt versions **and shas** for router (template sha + rendered sha from the trace) and each skill, git commit of the code. Then: headline table (mean, min–max), per-category table, per-skill P/R, output-check pass rates, latency/calls, and a per-case table (id, lang, category, expected, got per run, ✓/✗, one-line reason). Measured numbers only. With 15 test cases one case = 6.7 points; say so in the test-set report.

## 5. Tests (offline)
Metrics with hand-built `AgentRun`s (correct, wrong skill, wrong order, chain vs parallel, also_ok match, clarify, dropped, calc exact/inexact, Persian decimals); every output check, EN/FA; runner end-to-end on 3 dev cases with `FakeLLM` (writes JSONL + report into a temp dir, no network); quota-exhaustion stop (a fake that raises `LLMRateLimitError`) → partial report; the test-set guard flag.

## 6. Live run (Groq; ≤ 130 LLM calls)
Run the **dev set once** with the default (v1) prompts: `python -m eval.runner --set dev --runs 1 --label v1-baseline`. Commit the markdown report. **Do not run the test set**; that happens in WP7 after prompt iteration. List every dev failure with its cause (router vs skill vs check vs dataset) so WP7 can target them.

## 7. Acceptance
- [ ] `python -m eval.runner --set dev --dry-run` works with 0 calls; the test-set guard works.
- [ ] Metrics and checks fully unit-tested; whole-repo `uv run pytest -q` green on Windows; ruff clean.
- [ ] Dev v1 baseline report committed under `eval/reports/`, with raw JSONL kept out of git.
- [ ] `docs/handoffs/WP6b_report.md` with the headline numbers, the failure analysis and the live call count; 6–12 Conventional Commits on `feat/eval-runner`.
