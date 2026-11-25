# Agent prompts — how to launch

Each `WP*.md` file is a self-contained task for a separate Claude Code session. Agents share no memory. They coordinate only through the repository: `CLAUDE.md`, `docs/`, their own branch and worktree, and the handoff report.

## Delivery modes (ADR-020)
- **Mode A (preferred):** Claude Code running **locally** in this folder (PowerShell → `claude`). The agent uses a git worktree, and tests run on Windows.
- **Mode B:** a cloud session that can only copy files. Before launching it, run `git bundle create .worktrees/main.bundle main` in the project root. When it finishes, import its work with `git fetch .worktrees/<wp>.bundle <branch>:<branch>`.

## Launch procedure (owner)
1. Open a terminal in the project root: `cd "C:\Users\ai\Desktop\multi-skill AI agent"`
2. Start Claude Code: `claude`
3. Send exactly: `Read agent_prompts/<FILE>.md and execute it fully. Follow CLAUDE.md.`
4. When it finishes, tell the architect session "WPx done". The architect reads `.worktrees/<wp>/docs/handoffs/WPx_report.md` directly, or you can paste the report.
5. Merge **only** after the architect approves, using the commands the architect gives you (normally `git merge --no-ff <branch>` from the root checkout on `main`).

## Order
| Wave | Prompts | Can run in parallel? |
|---|---|---|
| 1 | WP1_foundation | first (it bootstraps git) |
| 1b | WP0_model_bakeoff | once WP1 has made the first commit on `main` and `.env` exists |
| 2 | WP2, WP3, WP4, WP6a | yes, after WP1 is merged (prompts written after the WP1 review) |
| 3 | WP5 → WP6b → WP7 | sequential |

## Files
| File | Status |
|---|---|
| WP1_foundation.md | done, merged |
| WP0_model_bakeoff.md | ready (needs `.env` keys) |
| WP2_calculator.md | ready |
| WP3_text_skills.md | ready |
| WP4_router.md | ready |
| WP6a_eval_datasets.md | ready |
| WP5, WP6b, WP7 | written by the architect after the WP2–WP4 reviews |
| ARCHITECT_RESUME.md | prompt that starts a new coordinator session (used when moving computers) |

WP0, WP2, WP3, WP4 and WP6a can run **in parallel** (separate terminals, each `claude` in the project root). Each agent creates its own worktree.
