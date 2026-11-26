# WP7a — Prompt iteration v1 → v2, measured on the dev set and by the owner's Persian review

You are a **senior prompt engineer, fluent in English and Persian**. The brief asks the README to show "at least one example of how you improved a prompt and why", and grades Summarizer/Translator quality and Persian handling heavily. Every component works and is measured; your job is to write **v2 prompts that fix measured weaknesses**, prove the change with numbers on the **dev** set and with the owner's blind native-speaker review, and document each change so the README can quote it. No prior conversation context exists; everything you need is here and in the repo.

## 0. Read first
`CLAUDE.md` · `docs/DECISIONS.md` ADR-011, ADR-025 … ADR-029 · `docs/CONTRACTS.md` v1.4 §7 (versioned prompts, pinning), §14 · **the evidence:** `eval/reports/dev_*_v1-baseline.md` (the merged D01–D40 report; the raw JSONL is in `eval/reports/raw/`), `docs/handoffs/WP3_samples_groq.md` + `docs/handoffs/WP3_samples_groq_scores.md` (owner's scores and notes), `docs/handoffs/WP0_persian_scores.md`, `docs/handoffs/WP3_report.md` ("Anticipated failure modes"), `docs/handoffs/WP4b_report.md` §4 (cue order) · the v1 prompts in `skillagent/prompts/*/v1.md` and the skill code that renders them · `eval/README.md` (runner usage, `--prompt-versions`, `--resume`)

Branch `feat/prompts-v2`, worktree `.worktrees/wp7a`, from `main`.
**You own:** new `skillagent/prompts/*/v2.md` files, `tests/live/**`, `docs/handoffs/WP7a_*.md`. **Allowed with a note in the report:** reordering or tightening cues in the four `SPEC`s (decisive cue first; WP4b renders only the first 3 Use + 2 Don't-use), and the minimum skill-code change needed if a v2 template needs a new variable (keep v1 rendering unchanged and tested). **Never** edit `v1.md` files: v1 is the measured baseline.

## 1. Targets (from measurements, in priority order)
1. **Summarizer, cross-language summary into Persian** (owner score 3/3/2 on WP3 sample s4): «مخالفان به‌سرماریا لوپس هشدار می‌دهند» — broken sentence construction and a lost entity role when summarizing an English text in Persian. v2 must make the model write *natural Persian sentences* (restructure, don't calque; keep who-did-what explicit; full grammatical sentences) — consider a short Persian-output example for an English source.
2. **Translator into Persian: calques and collocations** (t1 3/5 naturalness; WP0 items 1, 2, 5): prefer idiomatic Persian collocations («افزایش ۱۲ درصدی فروش»), established Persian technical terms («رایانش ابری»), match the source register (colloquial ↔ colloquial), translate colloquial interjections and idioms by intended meaning («بابا ول کن دیگه» ≠ "Dad").
3. **General chat register** (c2, c5 naturalness 3): casual Persian input → casual, complete, natural Persian («با خودت مهربون باش»), no clichés; unsupported-action declines offer alternatives *relevant to the request* (c3); the degraded-fallback reply should suggest trying again (WP6b D11).
4. **Summaries keep actionable advice and the source's attribution verbs** (s2: «اعلام کرد» became «پیش‌بینی کرد»; advice to farmers/drivers dropped).
5. **Whatever the full dev v1 report shows** (router misses, output-check failures, preamble leakage via `meta.postprocess`). Read every ✗ in the dev report and classify it: router / skill prompt / skill code / check / dataset. Fix prompt-shaped problems in v2; list code or dataset problems in the report for the architect instead of patching them.
Change only what a measurement points at. Every v2 edit needs a one-line "because" tied to a case id or sample id.

## 2. Measuring (Groq free tier: 200K tokens/day, shared by everything on the account — ADR-029)
- **Dev set, pinned versions:** `uv run python -m eval.runner --set dev --runs 1 --label v2 --prompt-versions router=<n>,summarizer=2,translator=2,general_chat=2`. One full dev pass ≈ 120K tokens, so plan **at most one full v2 dev pass per day**; use `--cases` for quick checks of the cases you targeted and `--resume` if the quota stops a run. Compare against the v1 baseline report case by case.
- **Persian quality, blind:** rerun the WP3 samples with v2 (`tests/live/run_text_samples.py`, pin v2 via `SKILLAGENT_PROMPT_VERSIONS`), add 3–4 new samples that stress targets 1–3 (an English news paragraph summarized into Persian, a colloquial Persian chat line, a technical EN→FA sentence), and generate the same new samples with v1. Write `docs/handoffs/WP7a_persian_review.md`: for each sample, the input and two outputs labelled **A/B in random order** (key in `WP7a_persian_review_key.md`), with F/A/N 1–5 columns for the owner. The owner's scores decide whether v2 ships.
- **Never open or run `eval/test_set.yaml`.** The final test run is WP7b.
- **Budget:** ≤ 160 live calls in total for this WP, and stop at the day's quota rather than retrying. Record calls per day.

## 3. Deliverables
- `skillagent/prompts/{summarizer,translator,general_chat}/v2.md` (and `router/v2.md` only if dev v1 shows router prompt failures), each starting with the same comment-block format as v1 (purpose, variables, rationale) plus a **"Changes from v1"** list: change → because (case/sample id).
- Offline tests: v2 templates render with the same variables (or the new ones), Persian rules still present, v1 still loads and renders unchanged, pinning selects v1 or v2.
- `docs/handoffs/WP7a_report.md` (template), including:
  - a dev v1 vs v2 table (headline metrics, per category, output checks, `postprocess` flags) with per-case changes (fixed / regressed / unchanged);
  - **one fully worked "before → after → why" example** suitable for the README (prompt excerpt, input, v1 output, v2 output, measured effect);
  - the list of non-prompt issues for the architect;
  - live calls per day.
- 5–10 Conventional Commits on `feat/prompts-v2`.

## 4. Acceptance
- [ ] Whole-repo `uv run pytest -q` green on Windows; ruff clean; v1 files untouched (`git diff main -- 'skillagent/prompts/*/v1.md'` empty).
- [ ] Dev v2 routing-correct ≥ dev v1, or every regression explained and accepted in the report.
- [ ] Blind A/B review sheet ready for the owner; the report says which v2 prompts you recommend as default, pending the owner's scores. Note: `PromptLoader` uses the highest version when unpinned, so **merging a `v2.md` makes it the default**; a v2 the owner rejects must not be merged.
