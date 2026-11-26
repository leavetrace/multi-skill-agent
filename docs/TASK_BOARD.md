# TASK BOARD

> Updated by the Chief Architect after every agent report. Agents do **not** edit this file; they report in `docs/handoffs/WPx_report.md`.
> Last update: 2026-11-26 09:05 — WP3, WP4, WP0 accepted (trial merge: 1 130 tests). Merge order WP3 → WP4 → WP0. Provider decision pending (ADR-026). Router prompt must shrink for Groq TPM.

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
| WP0 | Provider/model bake-off spike | WP1 bootstrap commit, `.env` keys | `spike/model-bakeoff` | 🟪 accepted (ADR-026); merge after WP4 |
| WP2 | Calculator (safe evaluator, tool call, fast path) | WP1 merged | `feat/calculator` | ✅ accepted & merged |
| WP3 | Text skills (Summarizer, Translator, General Chat) | WP1 merged (WP0 helpful) | `feat/text-skills` | 🟪 accepted (ADR-025); merge first |
| WP4 | Router (+ fallback policy, Top-K selector) | WP1 merged (WP0 helpful) | `feat/router` | 🟪 accepted (ADR-024); merge after WP3; live smoke done (19/20) |
| WP6a | Eval datasets (test 15 + dev 40) | contracts | `feat/eval-data` | ✅ accepted & merged (ADR-023) |
| WP5 | Graph, scheduler, composer, CLI, scalability tests | WP1, WP4 | `feat/graph-cli` | ⬜ |
| WP6b | Eval runner, metrics, baseline + iteration runs | WP5, WP6a | `feat/eval-runner` | ⬜ |
| WP7 | Prompt iteration, README, final measured results, optional Docker | all | `docs/readme` | ⬜ |

Critical path: WP1 → WP4 → WP5 → WP6b → WP7.

## Architect follow-ups
- [ ] V8: reset model-written `dropped_intents` before applying the limit (`core/types.py`, ADR-024).
- [x] WP4 live smoke on dev D01–D20 (Groq): 19/20 plans, 20/20 language, router prompt 4 732 provider tokens.
- [ ] Trim the router prompt to ≤ 2.5K provider tokens for Groq TPM (ADR-026).
- [ ] Gateway `strip_think`: also strip `<thought>` blocks and unwrap a lone `<message>` (ADR-025).
- [ ] Rerun the WP3 live samples (13 calls) on the chosen provider.
- [ ] CONTRACTS v1.4: ` + ` parallel notation, §14 text-skill `meta.postprocess`, wrapper no-truncation for payload skills.
- [ ] Update `ProviderProfile` flags, `extra_body` and the default provider from the WP0 report (after the owner decides ADR-026).

## Owner action items
- [x] On the new computer: start the architect session (`agent_prompts/ARCHITECT_RESUME.md`); install uv.
- [x] Launch WP3, WP4, WP6a (three PowerShell windows, Mode A).
- [x] API keys in `.env` (rotated after an accidental paste in chat; verified 2026-11-26).
- [x] Native review of the Persian test-set prompts (all OK, 2026-11-26).
- [ ] Decide ADR-026 (primary provider) and score `docs/handoffs/WP0_persian_review.md` + `WP3_samples.md`.
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