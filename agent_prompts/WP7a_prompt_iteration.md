# WP7a — Prompt iteration v1 → v2 (deadline day: targeted, timeboxed, measured)

You are a **senior prompt engineer, fluent in English and Persian**. The brief asks the README to show "at least one example of how you improved a prompt and why", and grades Summarizer/Translator quality and Persian handling heavily. Everything works and is measured. Your job: write **targeted v2 prompts** for the text skills that fix the weaknesses the owner measured, prove them with a **blind A/B Persian review** and a small dev-set check, and document one before/after example for the README. **Today is the delivery deadline: timebox the whole WP to about 75 minutes.** No prior conversation context exists; everything you need is here and in the repo.

## 0. Read first
`CLAUDE.md` · `docs/DECISIONS.md` ADR-011, ADR-025, ADR-026, ADR-029 · `docs/CONTRACTS.md` v1.4 §7 (versioned prompts, pinning via `SKILLAGENT_PROMPT_VERSIONS`), §14 · **the evidence:** `docs/handoffs/WP3_samples_groq.md` + `docs/handoffs/WP3_samples_groq_scores.md` (owner's scores and notes), `docs/handoffs/WP0_persian_scores.md` · the v1 prompts in `skillagent/prompts/{summarizer,translator,general_chat}/v1.md` and the skill code that renders them · `eval/README.md` (runner usage, `--cases`, `--prompt-versions`)

Branch `feat/prompts-v2`, worktree `.worktrees/wp7a`, from `main`.
**You own:** new `skillagent/prompts/{summarizer,translator,general_chat}/v2.md`, `tests/live/**`, tests for the new templates under `tests/unit/skills/`, `docs/handoffs/WP7a_*.md`. **Never** edit any `v1.md` (v1 is the measured baseline) and don't touch the router.

## 1. Targets (from measurements, in priority order)
1. **Summarizer, English text → Persian summary** (owner 3/3/2 on sample s4): «مخالفان به‌سرماریا لوپس هشدار می‌دهند» — broken sentence construction and a lost entity role. v2: write natural, complete Persian sentences; restructure instead of calquing English; keep who-did-what explicit (e.g. «مخالفان این طرح، به رهبری ماریا لوپس، هشدار داده‌اند که …»). Consider one short example of an English source summarized in Persian.
2. **Summaries keep actionable advice and the source's attribution verbs** (s2: «اعلام کرد» became «پیش‌بینی کرد»; advice to farmers/drivers dropped).
3. **Translator into Persian: calques and collocations** (t1 naturalness 3; WP0 items 1, 2, 5): idiomatic collocations («افزایش ۱۲ درصدی فروش»), established Persian technical terms («رایانش ابری»), match the source register, translate colloquial interjections and idioms by intended meaning («بابا ول کن دیگه» ≈ "come on, give it a rest").
4. **General chat register** (c2, c5 naturalness 3): casual Persian input → casual, complete, natural Persian («با خودت مهربون باش»), no clichés; declines of unsupported actions offer alternatives relevant to the request (c3); in degraded mode, suggest trying again.
Change only what a finding points at. Every v2 edit gets a one-line "because" tied to a sample id.

## 2. Measuring (Groq free tier: 200K tokens/day shared by everything on the account; the architect runs the test set today too)
- **Budget: ≤ 40 live calls total.** Stop at a 429 daily-quota error rather than retrying.
- **Blind A/B Persian review:** run 8 samples through both v1 and v2 (pin with `SKILLAGENT_PROMPT_VERSIONS=summarizer=1,translator=1,general_chat=1` vs `=2`): WP3 samples s4, s2, t1, c2, c5 plus three new ones you write that stress targets 1, 3 and 4 (an English news paragraph summarized into Persian, a technical EN→FA sentence, a colloquial Persian chat line). Write `docs/handoffs/WP7a_persian_review.md`: input, then outputs **A/B in random order** with empty F/A/N (1–5) columns for the owner; key in `WP7a_persian_review_key.md`. Keep it short enough to score in 10 minutes.
- **Dev check (no full dev pass):** `uv run python -m eval.runner --set dev --cases D01,D02,D04,D10,D12,D23,D24,D28 --label v2-targeted --prompt-versions summarizer=2,translator=2,general_chat=2` and the same cases at `=1` if not already cheap to compare; report output checks and `postprocess` flags side by side.
- **Never open or run `eval/test_set.yaml`.**

## 3. Deliverables
- `skillagent/prompts/{summarizer,translator,general_chat}/v2.md`, each with the v1 comment-block format plus a **"Changes from v1"** list (change → because, sample id).
- Offline tests: v2 renders with the same variables, Persian rules present, v1 still loads unchanged, pinning selects v1 or v2. Whole-repo `uv run pytest -q` green; ruff clean.
- `docs/handoffs/WP7a_report.md` with the A/B sheet location, the dev-check table, live call count, and **one fully worked "before → after → why" example** for the README (prompt excerpt, input, v1 output, v2 output).
- 3–6 Conventional Commits on `feat/prompts-v2`.

**Merge note:** `PromptLoader` uses the highest version when unpinned, so merging a `v2.md` makes it the default. The owner's A/B scores decide; a v2 the owner rejects is removed before merge.
