# WP4b — Compact router prompt for the Groq free tier (measured, no accuracy loss)

You are a **senior LLM systems engineer**. WP4 built the router (`skillagent/router/**`). It works: an architect live check on Groq `qwen/qwen3.8-27b` routed 19/20 dev probes correctly. But the rendered router system prompt measured **4 732 provider tokens** (`usage.prompt_tokens`), and Groq's free tier allows **8 000 tokens per minute**, so every request waited ~35 s on a 429 `retry-after`. Your job is to shrink the prompt to **≤ 2 500 provider tokens** for the 4 real skills without losing routing accuracy, and prove both with measurements. No prior conversation context exists; everything you need is here and in the repo.

## 0. Read first
`CLAUDE.md` · `docs/CONTRACTS.md` **v1.4** (§1.1, §2, §11) · `docs/DECISIONS.md` ADR-002, ADR-008, ADR-024, ADR-026 · `docs/handoffs/WP4_report.md` (§5, §6, §7) · `skillagent/router/{cards,examples,router}.py`, `skillagent/prompts/router/v1.md` · the SPECs in `skillagent/skills/{summarizer,translator,general_chat}.py` and `skillagent/skills/calculator/` (read only)

Branch `feat/router-compact`, worktree `.worktrees/wp4b`, created from `main` **after** `chore/groq-default` is merged (Groq must be the default provider).
**You own:** `skillagent/router/**`, `skillagent/prompts/router/**`, `tests/unit/router/**`, and a new `tests/live/router_dev_smoke.py`.
**You don't own the SPECs.** If a card is too long because of SPEC text (cues, examples), fix it in the *rendering* (e.g. render at most N cues per card, or don't render SPEC examples), not by editing another WP's file. Propose SPEC edits in your report instead.

## 1. Where the tokens go — measure first
Before changing anything, write down a breakdown of the current rendered prompt for the real registry: role + rules text, each skill card, SPEC examples, router-level examples (`examples.py`), output schema. Use `estimate_tokens` for the breakdown and **one** live call (§4) to calibrate estimate vs provider tokens. The WP4 report says the 12 router examples and the bilingual calculator card dominate; confirm or correct that with numbers.

## 2. Allowed levers (pick by measured gain; keep it explainable)
- Render each card compactly: description, then `Use:` / `Don't use:` cue lists capped at a fixed number per card (choose and justify, e.g. 4 + 3), keeping both EN and FA cues represented.
- Params summary in one line per skill.
- Few-shots: keep only examples that teach **policy** the rules can't (chain, parallel, over-limit, clarify, no-match, instruction-language, Finglish, injection, "answer in Persian" ≠ translation). Show them in compact plan notation (CONTRACTS §2: `a(user) -> b(s1, k=v)` for chains, `a(user) + b(user)` for parallel, `CLARIFY(lang)`), not full JSON. Keep **one** full JSON example so the output schema stays concrete.
- Don't render SPEC `examples` in the router prompt if router-level examples already cover the shapes; SPEC examples remain available to BM25 Top-K.
- Tighten rule wording. Every rule must still exist in some form (§3 of `agent_prompts/WP4_router.md`).

**Not allowed:** hardcoding skill names or descriptions in the router (the synthetic-5th-skill test must still pass); removing the injection, payload or language rules; anything that changes the public interface (CONTRACTS §11).

## 3. Versioning
No scored eval has used router v1 yet, so the compact prompt **replaces v1 in place** (it becomes the eval baseline). Record the old and new template `sha` and the old and new `rendered_sha` in the report. If a test pins rendered text, update it.

## 4. Live measurement (Groq; ≤ 45 calls total; key in root `.env`)
Write `tests/live/router_dev_smoke.py` (not collected by pytest, like `tests/live/run_text_samples.py`): it routes the **dev** cases `eval/dev_set.yaml` through `Router.route` with the real gateway and prints, per case, the plan signature, `response_language`, params, route_source and `usage.prompt_tokens`, then a summary (plan accuracy using `expected` + `also_ok`, language accuracy, fallbacks, p50 latency, median prompt tokens). Plan match = same ordered skills, same structure (single/chain/parallel), or clarify when expected.
- Throttle so you stay under 8K tokens/min (with ~2.5K-token prompts that is ~1 call per 20 s). Honour 429 `retry-after` (the gateway does).
- Run: 1 calibration call before changes, then the full dev set (40 cases; the fast path makes some free) on the compact prompt. **Never open or run `eval/test_set.yaml`.**
- Compare against the architect's v1 baseline on D01–D20: plan 19/20, language 20/20, 0 fallbacks, prompt 4 732 tokens. The only miss was D16.

## 5. Acceptance
- [ ] Rendered router system prompt for the 4 real skills **≤ 2 500 provider tokens** (measured), with the before/after breakdown table.
- [ ] Dev D01–D20: plan accuracy ≥ 19/20 and language 20/20; full dev set D01–D40 reported per case, with every miss explained. If accuracy drops, restore the lever that caused it and say so.
- [ ] Router-prompt token table for 4 / 10 / 20 synthetic skills re-measured (WP5's scalability section uses it).
- [ ] Whole-repo `uv run pytest -q` green on Windows; ruff check and format clean. The synthetic-5th-skill and "no hardcoded skills" tests still pass.
- [ ] 4–8 Conventional Commits on `feat/router-compact`; `docs/handoffs/WP4b_report.md` from `docs/handoffs/TEMPLATE.md`, with the live call count.
