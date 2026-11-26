# WP5 — LangGraph graph, scheduler, composer, public API and CLI (+ scalability tests)

You are a **senior Python/LangGraph engineer**. Every component exists: preprocessing and the router (WP4), four skills (WP2, WP3), the LLM gateway and settings (WP1), eval data (WP6a). You wire them into the graph the brief requires ("raw prompt → routing node → skill node(s) → final response"), build `run_agent()` and the CLI, and prove the scalability story with synthetic skills. This is the component the interviewer will read first for "graph design and code readability". No prior conversation context exists; everything you need is here and in the repo.

## 0. Read first
`CLAUDE.md` · `docs/CONTRACTS.md` **v1.4** (§1.2 `SkillInput`/`SkillResult`/`StepTask`/`TraceEvent`, §2, §8, **§9 your public API**, **§10 your state**, §11 router, §13–§15) · `docs/ARCHITECTURE.md` §2, §4.3–4.7, §5 (fallback matrix), §7 (scalability), §8 (Persian/CLI) · `docs/DECISIONS.md` ADR-001, 003, 007, 008, 009, 021 (carry-overs), 025 · `docs/REQUIREMENTS.md` (A2, A6, A7) · existing code: `skillagent/router/`, `skillagent/skills/`, `skillagent/llm/`, `skillagent/config.py`, `skillagent/doctor.py`, `skillagent/testing/`

Branch `feat/graph-cli`, worktree `.worktrees/wp5`, from `main` after `chore/groq-default` is merged.
**You own:** `skillagent/graph/**`, `skillagent/api.py`, `skillagent/cli.py`, `skillagent/__main__.py`, `tests/integration/**`, `tests/scalability/**`. A `[project.scripts]` entry or a dependency change in `pyproject.toml` is allowed if you need it; list it in the report.
WP4b may be shrinking the router prompt in parallel. Use only `Router`'s public interface (CONTRACTS §11), so the two branches don't touch the same files.

## 1. Modules
```
skillagent/graph/
  __init__.py     # re-exports build_graph, AgentState
  state.py        # AgentState (CONTRACTS §10), merge_results reducer
  nodes.py        # preprocess, router, clarify, skill-node wrapper factory
  scheduler.py    # pure functions: ready_steps(), dispatch() -> list[Send] | "composer", skip propagation
  composer.py     # deterministic EN/FA response assembly (no LLM)
  builder.py      # build_graph(registry, settings, llm, prompts) -> compiled graph; mermaid()
skillagent/api.py       # AgentRun, run_agent()  (CONTRACTS §9)
skillagent/cli.py       # typer app
skillagent/__main__.py  # python -m skillagent
```
Keep scheduler and composer pure and unit-testable without LangGraph.

## 2. Graph (ADR-001)
`START → preprocess → router → route_after_router → (clarify | scheduler) ; scheduler ⇄ skill nodes ; → composer → END`.
- **preprocess:** `build_user_request(raw)`. If `approx_tokens > settings.max_request_tokens`, answer with a localized limit message and **no LLM call** (go straight to composer with that response).
- **router:** `Router.route(request, llm, elapsed_ms=…)`. Copy its events into `trace`; count its `llm_calls`.
- **route_after_router:** clarification → `clarify`; otherwise → `scheduler`. A `route_source="fallback"` decision is a normal `[general_chat]` plan: mark that step's `SkillInput.params["degraded"] = True` (general chat then answers without mentioning internals).
- **Skill nodes:** one node per registered skill, **generated from the registry** (no skill names in graph code). Each receives only a `StepTask` through `Send` (context isolation, ADR-009).
- **scheduler / dispatch:** READY = not done and (`input_from == "user"` or the dependency's result is `ok`). Dispatch up to `settings.max_parallel_steps` READY steps per wave as `Send(<skill node>, StepTask)`. A step whose dependency ended in anything but `ok` becomes `skipped` and never runs. Stop at `settings.max_waves`; any step still pending is `skipped` with reason `max_waves`. Set LangGraph's `recursion_limit` from these caps as a backstop.
- **clarify:** the router's question plus a localized line asking the user to resend the **full** request with the missing detail (no memory across requests, A6).
- **composer** (ADR-003, deterministic, language = `decision.response_language`, Persian when `fa`, English otherwise):
  - one step → its output
  - chain → the final step's output (intermediate outputs only in the trace)
  - parallel → one labelled section per step in plan order, with localized skill labels («ترجمه», «محاسبه», …; derive labels from a small map keyed by skill name with the skill name as fallback, so synthetic skills still render)
  - `rejected` outputs are already user-facing: show them as the step's output
  - `error` / `timeout` / `skipped` → a short localized note per failed step; the successful outputs are still shown (partial failure)
  - `dropped_intents` → a localized notice: "I handle up to 2 tasks per request; skipped: …" (A7)
  - if nothing succeeded, a static bilingual apology
  - Persian text follows the CLAUDE.md §5 rules (ی/ک, ZWNJ, «،»).

## 3. Skill-node wrapper (ARCHITECTURE §4.5, CONTRACTS §15, ADR-021)
1. Resolve `SkillInput`: `text` = the user's **raw** prompt for `input_from == "user"`, or the dependency's `output` with `is_chained=True`; `instruction`, `params` and `response_language` come from the plan.
2. Input budget: **don't truncate** for `requires_payload` skills (they own their budgets). For others, truncate to `budget.max_input_tokens` with `truncate_to_tokens` and set `meta["input_truncated"]`.
3. Run `spec.run(skill_input, SkillContext(llm, settings, prompts))` under `asyncio.wait_for(min(budget.timeout_s, remaining request deadline))`. The gateway has no overall deadline, so this is the only one (ADR-021).
4. Map outcomes to `SkillResult`: `ok`/`rejected` from `SkillOutput`; `asyncio.TimeoutError` → `timeout`; any `Exception` → `error` with `error=f"{type}: {msg}"`. Never let a skill exception escape the node.
5. Record `latency_ms` and `llm_calls` (from `meta`, default 1 if the skill made a call and didn't say) in `meta`; emit `TraceEvent`s `skill:<name>` start/end.

## 4. Public API (CONTRACTS §9)
`run_agent(prompt, *, settings=None, llm=None, registry=None) -> AgentRun`.
- Defaults: `Settings()`, `build_default_registry()`, and an `OpenAICompatGateway(settings, resolve_profile(settings))` created **inside** the running event loop (one gateway per loop, ADR-021). Accept an injected `llm` so the CLI REPL and eval reuse one gateway.
- `llm_calls` = router calls + the sum of skill `meta["llm_calls"]`. `total_ms` from a monotonic clock.
- **Never raises** for model/provider failures: anything that escapes the graph becomes a degraded `AgentRun` with the bilingual apology and the exception in the trace. It **does** raise `ConfigError` (missing key, bad provider) so the CLI can print an actionable message.

## 5. CLI (typer + rich; Windows first)
- `python -m skillagent` (no args) → REPL. Multi-line input: an empty line submits; `:paste` mode reads until a line with `:end`; `:quit`/`:q` exits. **One `asyncio.run` for the whole REPL session**, one gateway reused for every turn (ADR-021).
- `python -m skillagent ask "<prompt>"` one-shot; `--file input.txt` (UTF-8) instead of the argument; `--out answer.md` writes the response as UTF-8 (the documented workaround for RTL rendering in Windows terminals); `--trace` prints the routing decision, per-step status/latency/llm_calls and trace events as a rich table; `--json` prints `AgentRun` as JSON (UTF-8, `ensure_ascii=False`).
- `python -m skillagent graph --mermaid` prints the Mermaid diagram from `builder.mermaid()` (LangGraph's drawer). The README embeds it.
- `python -m skillagent doctor [--live]` delegates to `skillagent.doctor.run_doctor`.
- Force UTF-8 on Windows: `sys.stdout/stderr.reconfigure(encoding="utf-8")` at startup.
- `ConfigError` → one clear red line naming the missing `.env` entry and exit code 2; never a traceback. Never print key values.

## 6. Tests (offline, `FakeLLM`; no network)
**Integration (`tests/integration/`)** through `run_agent` with the real registry and `FakeLLM` rules keyed by `purpose` (`router`, `skill:<name>`, …). At least one test per route type:
single step; chain (assert the translator receives the summarizer's output with `is_chained=True`, and **not** the original prompt); parallel (both run in one wave, assert concurrency with a fake that awaits a shared event); clarify (no skill called); router fallback (garbage JSON twice → degraded general chat, `params["degraded"]`); over-limit (3 steps → 2 run + dropped notice); timeout (a skill that sleeps past its budget → `timeout` + note, the other parallel step still shown); partial failure (one skill raises); skipped dependent (chain whose first step errors → second `skipped`); pure arithmetic fast path (0 LLM calls, calculator direct path); request over `max_request_tokens` (0 LLM calls); Persian end-to-end (composer labels and notices in Persian, no Arabic ي/ك); `run_agent` never raises on `LLMProviderError`/`LLMRateLimitError`; context isolation (a spy skill asserts its `SkillInput` holds only its own text/instruction/params, never the router rationale or the other step's data).
**CLI:** typer `CliRunner` for `ask`, `--file`, `--out` (file is UTF-8 with Persian intact), `--json`, `graph --mermaid`, and the `ConfigError` path (exit 2, no traceback).
**Scalability (`tests/scalability/`)** with 20 synthetic skills (`skillagent.testing.make_skill_spec`) + the 4 real ones:
- the graph builds with **no code change**; node count = fixed nodes + N skills (record the numbers for N = 4, 10, 20);
- limits hold under a router that asks for 6 steps (max 2 run, rest dropped), and under a 10-wave chain (stops at `max_waves`);
- every skill node receives only `SkillInput` (isolation);
- BM25 Top-K is used above the threshold (assert the selector type and that `general_chat` is a candidate);
- record router-prompt estimated tokens for N = 4/10/20 via `Router.build_messages` for the README table.
Print the measured numbers (`-s`) and put them in the report.

## 7. Live smoke (Groq, key in root `.env`; ≤ 15 calls)
Run 5 prompts through `python -m skillagent ask … --trace`: one EN single, one FA single, one chain, one parallel, one Persian calculator word problem. Throttle (Groq free tier: 8K tokens/min; expect `retry-after` waits). Paste outputs and traces in the report. Use **dev**-style prompts only; never `eval/test_set.yaml`. Note: you can't see how the Windows terminal renders Persian; write each Persian output with `--out` too and say the owner should check the console rendering.

## 8. Acceptance
- [ ] CONTRACTS §9 and §10 implemented exactly; graph nodes generated from the registry; no skill names in `graph/` except the composer's label map (with fallback).
- [ ] Every route type in §6 covered by an offline integration test; `run_agent` never raises on provider failure (tests prove it).
- [ ] Scalability numbers (node count, router prompt tokens for 4/10/20, limits) measured and in the report.
- [ ] `python -m skillagent graph --mermaid` output pasted in the report.
- [ ] Whole-repo `uv run pytest -q` green on Windows; ruff check and format clean.
- [ ] 8–15 Conventional Commits on `feat/graph-cli`; `docs/handoffs/WP5_report.md` from the template, with live call count.
