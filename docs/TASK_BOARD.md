# TASK BOARD

> Updated by the Chief Architect after every agent report. Agents do **not** edit this file; they report in `docs/handoffs/WPx_report.md`.
> Last update: 2026-11-26 20:00 — WP4b, WP5, architect fixes merged. WP6b accepted (ADR-029); dev baseline partial (D01–D10 10/10) because of Groq's 200K tokens/day limit. D11–D40 resume next day.

## Status legend
⬜ not started · 🟦 prompt ready · 🟨 in progress · 🟪 in review (architect) · ✅ accepted/merged · ⛔ blocked

## Phase 0 — Architecture (coordinator)
| Item | Status | Notes |
|---|---|---|
| Read brief, classify requirements | ✅ | docs/REQUIREMENTS.md |
| Architecture v1.0 | ✅ | accepted by owner 2026-11-25 |
| Contracts v1.0 frozen | ✅ | docs/CONTRACTS.md |
| CLAUDE.md, handoff template, launch guide | ✅ | |
| Owner decisions | ✅ | provider approved; public GitHub (name later); Claude Code agents; owner reviews Persian |

## Work packages
| WP | Title | Depends on | Branch | Status |
|---|---|---|---|---|
| WP1 | Foundation + git bootstrap | — | `feat/foundation` | ✅ accepted & merged |
| WP0 | Provider/model bake-off spike | WP1 bootstrap commit, `.env` keys | `spike/model-bakeoff` | ✅ accepted & merged |
| WP2 | Calculator (safe evaluator, tool call, fast path) | WP1 merged | `feat/calculator` | ✅ accepted & merged |
| WP3 | Text skills (Summarizer, Translator, General Chat) | WP1 merged (WP0 helpful) | `feat/text-skills` | ✅ accepted & merged |
| WP4 | Router (+ fallback policy, Top-K selector) | WP1 merged (WP0 helpful) | `feat/router` | ✅ accepted & merged |
| WP4b | Compact router prompt for Groq TPM (≤ 2.5K tokens) | WP4, groq default | `feat/router-compact` | ✅ accepted & merged |
| WP6a | Eval datasets (test 15 + dev 40) | contracts | `feat/eval-data` | ✅ accepted & merged (ADR-023) |
| WP5 | Graph, scheduler, composer, CLI, scalability tests | WP1, WP4, groq default | `feat/graph-cli` | ✅ accepted & merged |
| WP6b | Eval runner, metrics, dev baseline | WP5, WP6a | `feat/eval-runner` | 🟪 accepted (ADR-029); merge; dev D11–D40 next day |
| WP7a | Prompt iteration v1 → v2 (dev + owner blind review) | dev v1 baseline | `feat/prompts-v2` | 🟦 prompt ready |
| WP7b | Test set ×3, README, optional Docker, release | WP7a | `docs/readme` | ⬜ |

Critical path: WP1 → WP4 → WP5 → WP6b → WP7.

## Architect follow-ups
- [x] V8 owns `dropped_intents` (`chore/groq-default`).
- [x] WP4 live smoke on dev D01–D20 (Groq): 19/20 plans, 20/20 language, router prompt 4 732 provider tokens.
- [x] Router prompt trimmed to ~2.3K provider tokens (WP4b).
- [x] Payload fix for Persian parallel prompts; calculator trailing period (`fix/review-followups`).
- [x] CLI hides retry warnings unless `--trace`; gateway redacts `org_…`; no fallback call after a router quota error (`fix/runtime-polish`).
- [ ] Resume dev v1 baseline D11–D40 on a fresh daily quota (raw log copied to root `eval/reports/raw/`).
- [x] WP7a prompt written. WP7b (test ×3 on its own quota day, README, identity rewrite, push) after WP7a.
- [x] `strip_think` handles `<thought>` and a lone `<message>` (`chore/groq-default`).
- [x] WP3 live samples on Groq: 13/13 OK (`docs/handoffs/WP3_samples_groq.md`).
- [x] CONTRACTS v1.4.
- [x] Groq default provider and measured profile (`chore/groq-default`).

## Owner action items
- [x] On the new computer: start the architect session (`agent_prompts/ARCHITECT_RESUME.md`); install uv.
- [x] Launch WP3, WP4, WP6a (three PowerShell windows, Mode A).
- [x] API keys in `.env` (rotated after an accidental paste in chat; verified 2026-11-26).
- [x] Native review of the Persian test-set prompts (all OK, 2026-11-26).
- [x] ADR-026 decided (Groq) and WP0 Persian items scored.
- [x] Merge `chore/groq-default`; WP4b and WP5 done.
- [x] Merged `feat/router-compact`, `feat/graph-cli`, `fix/review-followups`; WP6b done.
- [ ] Merge `feat/eval-runner` and `fix/runtime-polish`.
- [x] Native review of the WP3 samples on Groq (4.62 / 4.69 / 4.15, `WP3_samples_groq_scores.md`).
- [ ] Later (before first push): GitHub account + git name/email → architect gives history-rewrite commands (ADR-019).

## Risks
| Risk | Impact | Mitigation | Owner |
|---|---|---|---|
| Free model deprecation / quota change | High | config-driven model id, alternate provider, WP0 | Arch |
| Gemma via the OpenAI-compatible endpoint lacks system role / JSON mode | Medium | ProviderProfile flags + gateway fallbacks; WP0 measures | WP0/WP1 |
| Router JSON unreliability on chosen model | High | JSON mode + validation + repair; bake-off metric | WP4 |
| Windows console RTL/encoding issues | Medium | UTF-8 forcing, --file/--out, manual test | WP5 |
| Eval overfitting | Medium | dev/test split, freeze test set | WP6 |
| Parallel agents colliding | Medium | worktree per agent, ownership map, stubs in WP1 | Arch |