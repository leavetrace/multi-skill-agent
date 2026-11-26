# TASK BOARD

> Updated by the Chief Architect after every agent report. Agents do **not** edit this file; they report in `docs/handoffs/WPx_report.md`.
> Last update: 2026-11-26 07:25 — architect resumed on the owner's computer. `main` verified on Windows: 852 tests passed, ruff check and format clean (uv 0.13.10). Next: WP3, WP4, WP6a in parallel; WP0 when `.env` keys exist.

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
| WP0 | Provider/model bake-off spike | WP1 bootstrap commit, `.env` keys | `spike/model-bakeoff` | 🟦 launch when keys exist |
| WP2 | Calculator (safe evaluator, tool call, fast path) | WP1 merged | `feat/calculator` | ✅ accepted & merged |
| WP3 | Text skills (Summarizer, Translator, General Chat) | WP1 merged (WP0 helpful) | `feat/text-skills` | 🟦 prompt ready |
| WP4 | Router (+ fallback policy, Top-K selector) | WP1 merged (WP0 helpful) | `feat/router` | 🟦 prompt ready |
| WP6a | Eval datasets (test 15 + dev ~35) | contracts | `feat/eval-data` | 🟦 prompt ready |
| WP5 | Graph, scheduler, composer, CLI, scalability tests | WP1, WP4 | `feat/graph-cli` | ⬜ |
| WP6b | Eval runner, metrics, baseline + iteration runs | WP5, WP6a | `feat/eval-runner` | ⬜ |
| WP7 | Prompt iteration, README, final measured results, optional Docker | all | `docs/readme` | ⬜ |

Critical path: WP1 → WP4 → WP5 → WP6b → WP7.

## Owner action items
- [x] On the new computer: start the architect session (`agent_prompts/ARCHITECT_RESUME.md`); install uv.
- [ ] Launch WP3, WP4, WP6a (three PowerShell windows, Mode A).
- [ ] Create free API keys (Google AI Studio, Groq) → root `.env` (never in chat) → enables WP0.
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
