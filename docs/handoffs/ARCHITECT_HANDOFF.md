# ARCHITECT HANDOFF — read this first if you are the new coordinator session

> Written by the first Chief Architect session (2026-11-25) for its successor on the owner's other computer. The successor has **no access** to the previous conversation. Everything that matters is in this repository. This file is the index and the "unwritten context".

## 1. Your role
You are the Chief AI Architect and technical lead for this take-home assignment (I4Twins "AI Engineer" task: a multi-skill LangGraph agent). You coordinate specialized Claude Code agents. The owner launches each agent from a prompt file you write in `agent_prompts/`. You review the results critically against the architecture, integrate them, resolve conflicts, and keep the docs as the single source of truth. Keep the owner involved in consequential decisions without overwhelming them. Report measured results only.

## 2. Read in this order
1. `docs/REQUIREMENTS.md` — every mandatory requirement, our objectives, the assumptions log (A1–A8)
2. `docs/ARCHITECTURE.md` — the design (v1.0 accepted)
3. `docs/CONTRACTS.md` — frozen interfaces, **v1.2**
4. `docs/DECISIONS.md` — ADR-001 … ADR-021
5. `docs/TASK_BOARD.md` — status
6. `CLAUDE.md` — rules every agent follows
7. `docs/handoffs/WP*_report.md` — agent reports so far
8. `agent_prompts/*.md` — prompts already issued, to match their style and depth

The assignment PDF (`AIEngineerTask.pdf`) is git-ignored (ADR-018). Ask the owner to copy it into the folder if you need the original wording. REQUIREMENTS.md already captures all of it.

## 3. State at handoff
| WP | Status |
|---|---|
| WP1 Foundation | ✅ merged to `main`. 250 tests on Linux; the owner ran them on Windows during the handoff (check `git log` and ask whether `uv run pytest -q` passed on Windows). |
| WP0 model bake-off | prompt ready. Needs `GOOGLE_API_KEY` and `GROQ_API_KEY` in root `.env` (free, no card). |
| WP2 calculator | **launched on the first computer in Mode B** (cloud session, 2026-11-25 ~14:40). If `.worktrees/wp2.bundle` and `.worktrees/wp2_report.md` exist, import with `git fetch .worktrees/wp2.bundle feat/calculator:feat/calculator`, then review per §4. If they don't exist, the run didn't finish: relaunch WP2 locally (Mode A). |
| WP3 text skills, WP4 router, WP6a eval data | prompts ready; can run in parallel now (Mode A). |
| WP5 graph+CLI, WP6b eval runner, WP7 iteration+README | **not written yet**. Outlines in §6. |

**Delivery mode:** the owner now works on their own computer with **local Claude Code** (Mode A in CLAUDE.md §3: worktree per WP, tests on Windows). Mode B (cloud + git bundles) was used once for WP1 and should no longer be needed.

## 4. How to review an agent's work (the procedure used for WP1)
1. Read its `docs/handoffs/WPx_report.md` on its branch (`.worktrees/wpx/...`).
2. **Reproduce, don't trust:** in the worktree run `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .`. Check the commit history: `git log --oneline main..<branch>`, the author is the placeholder identity, and the commits are small and logical.
3. Check contract conformance against CONTRACTS.md. Look for files touched outside its ownership (`git diff --stat main..<branch>`).
4. Probe behaviour with a few scripted calls, e.g. validation edge cases and Persian inputs.
5. Decide: accept / accept with architect follow-ups / send back. Small follow-ups can be committed by you on the WP branch (Conventional Commits). Contract changes bump the CONTRACTS version, with a changelog and an ADR.
6. Give the owner the merge command from the root checkout on `main`: `git merge --no-ff <branch> -m "Merge branch '<branch>' (WPx)"`. Then run tests again on `main`. Update TASK_BOARD and DECISIONS.
7. Merge order when several finish together: WP2 / WP3 / WP6a in any order, **then WP4** (its card tests render the final SPEC texts). Re-run the whole suite after each merge.

## 5. Unwritten context
- **Owner:** Windows user (PowerShell); native Persian speaker who reviews Persian outputs (blind A/B/C sheets work well); prefers to be told exactly what to run.
  - Lesson learned: always tell them to run the `cd "<project folder>"` line first and on its own, and to use a normal (non-admin) PowerShell. A missed `cd` once ran git commands in `C:\Windows\System32`.
- **Secrets:** never ask for API keys in chat; they live in root `.env` (git-ignored).
- **Git identity:** repo-local placeholder `skillagent-dev <skillagent-dev@example.invalid>` (ADR-019). Before the first push to GitHub, rewrite author/committer to the owner's identity while keeping merge commits: `git filter-repo --mailmap` is preferred. The GitHub account name and real identity come from the owner at push time. Repo name: `multi-skill-agent` (public).
- **Provider direction (ADR-006):** Gemma 4 31B IT (30.7B dense) via Google AI Studio is the leading candidate; Qwen3.8-27B (27B dense) via Groq is the alternate. OpenRouter free has a 50 requests/day cap, so it isn't primary. The final choice comes from WP0 measurements **plus** the owner's blind Persian scores. Afterwards, update `skillagent/llm/providers.py` capability flags and `extra_body` (thinking control) from the WP0 report. That's a small architect follow-up on a branch.
- **Known carry-overs (ADR-021):**
  - The language hint reflects content, not instruction; WP4 adds `leading_segment_hint`.
  - One gateway per event loop: the CLI REPL must live inside a single `asyncio.run`.
  - The gateway has no overall deadline: the WP5 skill wrapper uses `asyncio.wait_for` with the request deadline.
  - Tools are sent even when `supports_tools=False`: WP2 has a JSON fallback.
- **Interview emphasis:** the interviewer stressed preventing execution and context explosion as skills grow from 4 to 20+. Our answer is ARCHITECTURE §1 (the table of what actually breaks) and §7 (nine code-enforced mechanisms), demonstrated by synthetic-skill tests (WP4 BM25 recall and router-prompt token growth; WP5 graph build plus limits with 20 skills). Keep that story crisp in the README.
- **Brief constraints that bite:** exactly 4 skills, ≤ 2 per request, no memory across requests, no FastAPI, free tier, ≤ 35B parameters. Docker is optional and a plus.

## 6. Remaining work-package outlines (write the full prompts in the same style as WP1–WP4)
**WP5 — Graph, API, CLI** (`skillagent/graph/**`, `api.py`, `cli.py`, `__main__.py`, `tests/integration/**`, `tests/scalability/**`)
- `build_graph(registry, settings, ...)`: nodes preprocess → router → (clarify | scheduler ⇄ skill nodes generated from the registry via `Send`) → composer. State per CONTRACTS §10.
- **Scheduler waves:** READY = dependencies `ok`. Cap at `max_parallel_steps` and `max_waves`. Dependents of failed steps are marked `skipped`.
- **Skill-node wrapper:**
  - resolve `SkillInput` (user text, or the dependency output with `is_chained=True`)
  - per-skill input truncation where the skill allows it
  - `asyncio.wait_for(min(budget.timeout_s, remaining deadline))`
  - map exceptions → `SkillResult` error/timeout; record latency and tokens
- **Composer:** deterministic, with localized EN/FA templates. Sections for parallel results, the final output for chains, a partial-failure note, a dropped-intents notice, clarification text. A bilingual apology for the degraded path.
- `run_agent()` per CONTRACTS §9. It never raises on provider failures.
- **CLI (typer + rich):**
  - `python -m skillagent` REPL; multi-line input (an empty line ends it, or `:paste` mode)
  - `ask "<prompt>"` one-shot, `--file input.txt`, `--out answer.md`, `--trace`, `--json`
  - force UTF-8 on Windows
  - **one `asyncio.run` for the whole REPL session** (gateway lifetime)
  - `graph --mermaid` prints the Mermaid diagram for the README
- **Tests:** integration with FakeLLM for every route type (single, chain, parallel, clarify, fallback, over-limit, timeout, partial failure). Scalability with 20 synthetic skills: the graph builds without code changes, limits hold, skill nodes receive only `SkillInput`, and node count grows linearly. Record the numbers.

**WP6b — Eval runner** (`eval/runner.py`, `eval/metrics.py`, `eval/checks.py`, `eval/reports/`)
- `python -m eval.runner --set test|dev --runs 3 [--prompt-versions router=1]`
- One gateway per run. Throttling. On `LLMRateLimitError`, stop and write a partial report; never sleep through quotas.
- **Metrics:**
  - skill-set exact match (with `also_ok`)
  - per-skill precision/recall
  - structure accuracy
  - clarify precision/recall
  - response-language accuracy
  - calculator value exactness
  - output checks
  - p50/p95 latency, LLM calls per case
  - mean and min–max over runs
- **Report:** a markdown report with model id, provider, date, prompt shas, settings, and a per-case table. Raw JSONL goes to `eval/reports/raw/` (git-ignored). The markdown summary is committed.

**WP7 — Iteration, README, release**
1. Run dev v1, analyse failures, write prompt v2 for the router and the weakest skill, rerun dev. This is the documented **v1 → v2 improvement example with real numbers**.
2. Final test-set run ×3 at the chosen prompt versions.
3. README covering every item in REQUIREMENTS R13–R20, with the graph diagram (Mermaid), the scalability section, Persian handling, limitations and production gaps, the assumptions (A1–A8 and later ones), and the AI-usage disclosure pointing to `CLAUDE.md`, `agent_prompts/` and `docs/`.
4. Optional minimal Dockerfile.
5. Identity rewrite (ADR-019), then push all branches to GitHub. Verify a fresh clone runs on Windows by following the README.

## 7. Open items / risks to watch
- WP0 hasn't run yet: model choice, capability flags and Persian quality are unmeasured.
- Groq preview models get deprecated quickly; keep the alternate provider configured.
- Free-tier quotas during eval: 15 cases × ~2.3 calls × 3 runs ≈ 100+ calls per final run.
- Windows terminals render RTL text imperfectly, so `--out` to a file is the documented workaround. Verify on the owner's machine in WP5.
- Prompt-tuning discipline: never tune on `eval/test_set.yaml` (frozen in WP6a).
