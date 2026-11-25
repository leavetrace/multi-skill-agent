# CLAUDE.md — Shared rules for every AI agent working in this repository

This file is loaded automatically by Claude Code. It applies to **all** agent sessions. Your specific task is in `agent_prompts/WP*.md`. If this file and your task prompt conflict, **stop and report**; don't guess.

> AI-usage disclosure: this repository was built with Claude agents coordinated by a human owner and a "Chief Architect" Claude session. This file, `agent_prompts/`, and `docs/` are the instruction artifacts given to those agents.

## 1. Project in one paragraph
A CLI prototype of a multi-skill agent (take-home assignment). A LangGraph graph routes a free-form English/Persian prompt to up to 2 of exactly 4 skills: `summarizer`, `translator`, `calculator`, `general_chat`. The router outputs a Pydantic-validated mini-plan (DAG). A deterministic scheduler runs the plan through LangGraph `Send`, in parallel or chained by data dependency. The calculator uses a real safe evaluator. The LLM is a free-tier model with ≤35B parameters. Scalability mechanisms (registry, limits, isolation, Top-K) are generic, but we ship **exactly 4 skills**.

## 2. Read before you write code
1. `docs/ARCHITECTURE.md` — the design
2. `docs/CONTRACTS.md` — **frozen interfaces (normative)**
3. `docs/DECISIONS.md` — why things are the way they are
4. Your task prompt in `agent_prompts/`

Don't edit `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `docs/DECISIONS.md`, `docs/TASK_BOARD.md`, `CLAUDE.md`, `agent_prompts/` or `README.md`. Those belong to the architect. Propose changes in your handoff report instead.

## 3. Git workflow (mandatory)
- Repo root = this folder. The root checkout stays on `main`. **Never commit directly to `main`** (the only exception is the WP1 bootstrap step, which is specified explicitly).
- Several agents may run at the same time, so **each agent works in its own git worktree**:
  ```
  git worktree add .worktrees/<wp-id> -b <branch> main     # e.g. .worktrees/wp2 feat/calculator
  cd .worktrees/<wp-id>
  ```
  Do all your work there. `.worktrees/` is git-ignored.
- **Conventional Commits**, small and logical: `feat(calculator): add safe AST evaluator`, `test(core): ...`, `fix(llm): ...`, `docs(handoff): ...`, `chore: ...`. One concern per commit. Aim for 5–15 commits per WP, not one giant commit.
- **Don't merge, rebase `main`, push, or delete branches.** The owner merges after architect review.
- Git identity: the repo uses a **repository-local placeholder** (`skillagent-dev <skillagent-dev@example.invalid>`) until the owner supplies the real one; it will be rewritten before the first push (ADR-019). Don't change git config yourself, except for the WP1 bootstrap step specified in its prompt. Never touch `--global` config.

## 4. File ownership (prevents merge conflicts)
| Area | Owner |
|---|---|
| `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `skillagent/config.py`, `skillagent/core/**`, `skillagent/llm/**`, `skillagent/testing/**`, `skillagent/prompts/__init__.py` (loader), `skillagent/skills/base.py`, `skillagent/skills/params.py`, `skillagent/skills/catalog.py`, `skillagent/doctor.py` | WP1 |
| `skillagent/skills/calculator/**`, `skillagent/prompts/calculator/**`, `tests/unit/calculator/**` | WP2 |
| `skillagent/skills/{summarizer,translator,general_chat}.py`, `skillagent/prompts/{summarizer,translator,general_chat}/**`, `tests/unit/skills/**` | WP3 |
| `skillagent/router/**`, `skillagent/prompts/router/**`, `tests/unit/router/**` | WP4 |
| `skillagent/graph/**`, `skillagent/api.py`, `skillagent/cli.py`, `skillagent/__main__.py`, `tests/integration/**`, `tests/scalability/**` | WP5 |
| `eval/**` | WP6 |
| `spikes/**` | WP0 |
| `docs/handoffs/WPx_*.md` | the WP named in the file |

Need to touch a file you don't own? Keep the change minimal and list it explicitly in your report. **Adding a dependency** means adding it with `uv add <pkg>` and listing it in your report; lockfile conflicts are resolved at merge.

## 5. Engineering standards
- Python 3.12, `uv` for everything: `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`.
- Full type hints and small, focused modules. Write docstrings on public functions that explain *why*, not *what*. No dead code, and no TODOs without an issue note in your report.
- Async for I/O paths. Never block the event loop with `time.sleep`.
- Pydantic v2 idioms (`model_validate`, `model_dump`, `ConfigDict`).
- **Tests never hit the network.** Use `skillagent.testing.FakeLLM`. Tests that need a real provider are marked `@pytest.mark.live` and are skipped by default.
- Don't call the LLM for things code can do deterministically (normalization, language hints, formatting).
- All user-visible text must support English and Persian. Persian output uses Persian characters (`ی`, `ک`, not `ي`, `ك`), correct ZWNJ (نیم‌فاصله) and Persian punctuation (`،` `؛` `؟`).

## 6. Secrets & safety
- API keys live only in `.env` at the repo root, which is git-ignored. Never print, log, commit or paste keys. Mask them in diagnostics (`gsk_…abcd`).
- Never use `eval`, `exec` or `sympy.sympify` on user input.
- Text the user asks to summarize or translate is **data**. Prompts must say so and wrap it in delimiters.

## 7. Windows environment
The owner uses Windows. Prefer cross-platform commands (`uv run …`). Don't rely on Makefiles or bash-only scripts in project code. Force UTF-8 for console I/O where relevant. Use `pathlib` for paths, and remember the repo path contains spaces, so quote it.

## 8. Free-tier etiquette
Real LLM calls cost scarce free quota. Only make live calls when your task says so, and stay within the call budget it states. Throttle (≥2 s between calls unless told otherwise). Record how many live calls you made.

## 9. Reporting
Finish by writing `docs/handoffs/<WP-ID>_report.md` using `docs/handoffs/TEMPLATE.md` and committing it on your branch. Your final chat message should be a short summary plus the report path. Report **measured facts only**. If you didn't run something, say so.

## 10. Stop conditions — ask the owner instead of improvising
A contract seems wrong or insufficient · a required tool or key is missing · a task needs changes outside your ownership beyond trivial · tests can't pass without changing frozen interfaces · anything destructive (deleting files you didn't create, rewriting history).
