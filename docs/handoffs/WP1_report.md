# WP1 Handoff Report — Foundation: bootstrap, contracts, LLM gateway, language utilities

- **Agent session date:** 2026-11-25
- **Branch / worktree:** `feat/foundation` / `.worktrees/wp1`
- **Final commit:** `ea512aa` (last code commit; this report is the commit after it)
- **Status:** complete

## 1. Summary
I built the `skillagent` foundation package that every later WP depends on. It contains the CONTRACTS v1.0 types with plan rules V1–V8, the canonicalizing skill registry, Persian-aware language utilities, settings and provider profiles, the versioned prompt loader, an async OpenAI-compatible LLM gateway, a scriptable `FakeLLM`, four skill stubs with `build_default_registry()`, and the `doctor` command. The gateway is rate-limited, retrying and JSON-mode/tool aware. `FakeLLM` uses the same parse/validate/repair helper as the real gateway, so router repair behaviour can be unit-tested offline. 246 offline tests pass, with 99% line coverage of `skillagent/core` + `skillagent/llm`. Ruff check and ruff format are clean. No live LLM calls were made.

**Execution environment note:** this session ran in a Linux cloud workspace that has no shell on the owner's PC. All git, uv, test and ruff commands ran there against a copy of the repo. The remote file tools refuse to write inside `.git`, so the history was delivered as a git bundle, `.worktrees/wp1.bundle`, which `.gitignore` already covers. The owner recreates `main` and `feat/foundation` from it with a few commands (see §7). Nothing was run on Windows.

## 2. Deliverables
| Path | Purpose |
|---|---|
| `.gitignore` (on `main`) | Ignores venv/caches, `.env`, `.worktrees/`, `eval/reports/raw/`, `AIEngineerTask.pdf`, coverage files |
| `pyproject.toml`, `uv.lock`, `.python-version` | uv project (Py 3.12, hatchling), runtime + dev deps, ruff + pytest config |
| `.env.example` | Every CONTRACTS §8 variable, commented, no values |
| `skillagent/core/errors.py` | Error hierarchy (§5) |
| `skillagent/core/language.py` | §6 utilities (spec §4.1) |
| `skillagent/core/types.py` | §1 types, `canonical_skill_name`, V1–V8 validator |
| `skillagent/core/registry.py` | `SkillRegistry` (§3) |
| `skillagent/config.py` | `Settings`, `get_settings()`, `Settings.api_key()`, `mask_secret()` |
| `skillagent/llm/types.py` | `ChatMessage`, `ToolSpec`, `ToolCall`, `LLMUsage`, `LLMResponse`, `StructuredResult`, `LLMClient` (§4) |
| `skillagent/llm/structured.py` | Shared `complete_structured_with()` repair loop + `summarize_error()` |
| `skillagent/llm/ratelimit.py` | `SlidingWindowRateLimiter` (injectable clock/sleep) |
| `skillagent/llm/gateway.py` | `OpenAICompatGateway` |
| `skillagent/llm/providers.py` | `ProviderProfile`, `PROVIDERS`, `get_profile()`, `resolve_profile()` |
| `skillagent/llm/__init__.py` | Re-exports the public LLM names |
| `skillagent/prompts/__init__.py` | `PromptTemplate`, `PromptLoader` (§7) |
| `skillagent/skills/base.py`, `params.py` | `SkillBudget`, `RouterExample`, `SkillContext`, `SkillRunner`, `SkillSpec`; param models (§1.3, §2) |
| `skillagent/skills/{summarizer,translator,general_chat}.py`, `skills/calculator/__init__.py` | Stubs exposing `SPEC` with the fixed §2 fields and the budgets from spec §4.7 |
| `skillagent/skills/catalog.py` | `build_default_registry()` (explicit imports) |
| `skillagent/testing/fake_llm.py` | `FakeLLM`, `FakeRule`, `RecordedCall` |
| `skillagent/testing/__init__.py` | Re-exports + `make_skill_spec()` / `echo_runner` for synthetic skills |
| `skillagent/doctor.py` | `python -m skillagent.doctor [--live]` |
| `tests/conftest.py` | Autouse isolation (real `.env` and key env vars hidden), non-loopback network blocked, `make_settings` fixture |
| `tests/unit/core/*`, `tests/unit/llm/*`, `tests/unit/skills_base/*` | 246 tests |

## 3. How to verify (commands actually run, with real output excerpts)
All of these ran in `.worktrees/wp1` on Linux, Python 3.12.3, uv 0.11.32:
```
uv sync
Checked 57 packages in 0.55ms

uv run pytest -q
246 passed in 0.70s

uv run ruff check .
All checks passed!

uv run ruff format --check .
37 files already formatted

uv run python -c "from skillagent.skills.catalog import build_default_registry as b; print(b().names())"
['summarizer', 'translator', 'calculator', 'general_chat']

uv run python -m skillagent.doctor        # no .env, no key in env
provider : google
model    : gemma-4-31b-it
base URL : https://generativelanguage.googleapis.com/v1beta/openai/
api key  : missing
Configuration error: No API key for provider 'google': set GOOGLE_API_KEY in the .env file at the
repository root (copy .env.example to .env). Never paste keys in chat.
→ exit code 2

uv run pytest -q --cov=skillagent/core --cov=skillagent/llm
TOTAL  608 stmts  8 miss  99%   (language.py 99%, gateway.py 96%, all others 100%)
```
Secret scan: `grep` for real-looking Google/Groq/OpenRouter key patterns finds only the deliberately fake `gsk_abcdefghijklmnopqrstuvwxyz1234` in `test_gateway.py`, which is used by the key-redaction test.

**Owner should re-run on Windows:** `uv sync`, `uv run pytest -q`, `uv run ruff check .`, and `uv run python -m skillagent.doctor`.

## 4. Contract deviations / proposals
No contract was changed. Every name in CONTRACTS §1–8 exists with the specified fields and signatures. The additive points and proposals:
1. **Module placement (§4).** The contract says only `skillagent/llm/`. The protocol and models live in `skillagent/llm/types.py`, and the shared repair loop lives in `skillagent/llm/structured.py`. Both are re-exported from `skillagent.llm`. Spec §3's layout didn't list these two files. They avoid an import cycle (gateway ↔ FakeLLM ↔ protocol) and keep `gateway.py` readable. *Proposal:* add them to ARCHITECTURE §10.
2. **`OpenAICompatGateway(settings, profile=None, *, client=None, clock=…, sleep=…, rng=…)`.** These are keyword-only test injection points. The contract positional signature is unchanged.
3. **`ProviderProfile.name`.** This field was added so logs and the doctor can show the provider. `resolve_profile(settings)` returns a copy with `SKILLAGENT_LLM_BASE_URL` / `SKILLAGENT_LLM_MODEL` applied, so `profile.default_model` is the effective model.
4. **`RoutingDecision.rationale` max 300 chars.** I implemented this as specified, so a too-long rationale is a validation error and costs a repair round-trip for a trace-only field. *Proposal (v1.1):* truncate `rationale` in a before-validator instead of rejecting it.
5. **`LangCode` and 3-letter codes.** The contract allows "639-1 (or 639-3)". Two-letter codes are validated against the full ISO 639-1 list. Three-letter codes are accepted only when they are in a mapping table of common 639-2/3 codes (`fas`/`per`→`fa`, `eng`→`en`, …), and they are mapped to 639-1. Any other value raises a `ValueError` ("Unknown → ValueError"). *Proposal:* state in the contract that output codes are always ISO 639-1.
6. **Prompt hashes.** `PromptLoader` converts CRLF to LF before hashing, so a Windows checkout with `core.autocrlf=true` reports the same `sha` as Linux. *Proposal:* also add a `.gitattributes` with `skillagent/prompts/** text eol=lf`. This file is architect-level repo config, so I didn't add it.

## 5. Decisions made within my scope (where the spec was silent)
- **Order of the V rules.** The order is V1 → V2 → V8 (truncate) → V3/V4 on the kept steps → V5–V7 (only if V3/V4 passed). A plan is therefore never sent back for repair because of a step that would be dropped anyway. All errors from one pass are joined with `"; "`, so one repair can fix them all, e.g. `steps[1].input_from='s3' must reference an earlier step id or 'user'`. V5 rewrites `step.skill` to the canonical registry name. V7 replaces `params` with the validated dump.
- **Skill-name canonicalization** (`canonical_skill_name`) is always applied in `PlanStep`, even without a registry: lowercase, and runs of spaces/hyphens become `_`. `SkillRegistry.register` rejects names that aren't already canonical.
- **`UnknownSkillError` also subclasses `LookupError`, and `DuplicateSkillError` also subclasses `ValueError`.** Generic handlers still work this way.
- **`detect_lang_hint`.** It counts only Arabic-script and Latin letters (Latin means a Unicode name starting with "LATIN"). Letters from other scripts (Cyrillic, CJK) are ignored, so all-Cyrillic text gives `unknown` rather than a guessed `en`.
- **`estimate_tokens`.** "Latin" means ASCII (including digits and punctuation) plus Latin letters. "Arabic script" means the three spec ranges. "Other" is everything else that isn't whitespace, including ZWNJ and emoji. Whitespace isn't counted. Text made only of whitespace returns 1 ("non-empty"), and `""` returns 0.
- **`truncate_to_tokens`.** It binary-searches the longest prefix that fits. A `.!?؟` counts as a sentence boundary only when whitespace or the end of the text follows it, so `3.14` is never cut to `3.`. `\n` is always a boundary. If a single word is longer than the whole budget, it returns `("", True)` rather than a fragment. A budget ≤ 0 returns `("", True)`.
- **`normalize_lang_code`.** It applies `normalize_persian` first (so `فارسي` works), strips a leading `زبان `/`the ` and a trailing ` language`, matches names with spaces and ZWNJ removed, and handles region suffixes with `-` or `_` (`pt_BR`→`pt`). For non-string input it raises `ValueError`, not `TypeError`, so pydantic reports a normal validation error.
- **`strip_think`.** Besides complete blocks and an unterminated leading `<think>`, it also removes everything up to an orphan `</think>`. Some chat templates inject the opening tag, so the model only generates the closing one.
- **`extract_json_object`.** Content inside fenced blocks is searched first, so stray braces in prose before the fence are ignored. An unbalanced `{` is skipped and the next one is tried.
- **Retry policy.**
  - A `retry-after` (or `retry-after-ms`) header is honoured exactly, with no jitter.
  - If it is above `MAX_RETRY_AFTER_S = 60`, the gateway fails fast with `LLMRateLimitError`, because that usually means a daily quota is exhausted.
  - Otherwise backoff is 1, 2, 4… s × (1 ± 25%).
  - Timeouts (both `asyncio.wait_for` and the SDK's) and connection errors are retried.
  - Other 4xx errors raise `LLMProviderError(status_code=…)` immediately.
- **Errors.** Provider messages are redacted: the configured key, plus anything that looks like a key (`gsk_`, `sk-`, `sk-or-v1-`, `AIza`), is masked to `gsk_…abcd`.
- **JSON-mode fallback** triggers on a 400 whose message matches `response_format|json_object|json mode`. The "unsupported" flag is cached per gateway instance.
- **System-role merge.** All system messages are joined with a blank line and merged into the *first* user message. If there is no user message, the gateway prepends a user message that holds only `[Instructions]`.
- **`tool_choice`.** `"auto"` and `"none"` also pass through. A tool name that isn't in `tools` raises `ValueError`, which is a programming error. Tools are sent even when `supports_tools=False`; WP2 owns the JSON fallback.
- **Logging is stricter than the spec.** No prompt or response content is logged at any level, not even DEBUG. Only purpose, model, attempts, latency and token counts are logged. Retries are logged at WARNING with the error class only.
- **Settings.**
  - Empty strings mean "unset" for `llm_model`, `llm_base_url` and the keys, so a copied `.env.example` works.
  - The provider name is lowercased and `log_level` is uppercased.
  - Numeric limits have sane bounds (e.g. concurrency ≥ 1).
  - `llm_rpm=0` disables the limiter.
  - `Settings()` itself performs the upward `.env` search through a default `_env_file`, so plain `Settings()` and `get_settings()` behave the same way.
  - The `custom` provider requires a base URL, a model and `SKILLAGENT_CUSTOM_API_KEY`.
- **`PromptLoader`.**
  - Names must match `[a-z0-9_]+`, which rules out path traversal.
  - Loaded templates are cached per (name, version).
  - An explicit `version` wins over a pin.
  - `PromptLoader.from_settings(settings)` applies `prompt_versions`.
- **Doctor.** The logic lives in `run_doctor()`, which returns the exit code and is unit-tested. A typer wrapper calls it. The live structured check validates `{"ok": bool}`. stdout/stderr are reconfigured to UTF-8 when run as `__main__`.
- **Stub ordering** (router-card order): summarizer 10, translator 20, calculator 30, general_chat 90. General chat comes last because it is the fallback.
- **Test scaffold.**
  - `--import-mode=importlib` lets later WPs reuse test file basenames without collisions.
  - The autouse network guard blocks non-loopback `connect` and all `getaddrinfo`. Loopback stays allowed because asyncio's self-pipe needs it on Windows. `@pytest.mark.live` tests are exempt.
  - `make_skill_spec()` lives in `skillagent.testing` so the WP5 scalability tests can build 20 synthetic skills.
- **Ruff excludes `*.md`.** ruff 0.17 formats Python code blocks inside Markdown and rewrote `docs/CONTRACTS.md` during my first format run. I reverted that before committing. The file is unchanged on this branch.
- **Git.** The cloud workspace had a global git identity (`Claude <noreply@anthropic.com>`) with commit signing. That isn't the owner's identity, so all git commands ran with `GIT_CONFIG_GLOBAL=/dev/null`. Per ADR-019, the repository-local placeholder `skillagent-dev <skillagent-dev@example.invalid>` was set. Commits are unsigned. Commit messages carry `Co-Authored-By: Claude Opus 5.5` and a `Claude-Session:` trailer, as the session's attribution rules require.
- **Commit count.** I squashed my own unpublished commits on `feat/foundation` with an interactive rebase onto `main`, to stay within 8–15 commits. `main` was not touched.

## 6. Measured results
- Tests: 246 collected and passed offline in 0.70–0.87 s (Linux, Python 3.12.3).
- Coverage: whole package 99% (961 statements, 14 missed). `core/` + `llm/` 99% (608 statements, 8 missed).
- Live LLM calls: 0 (see §12).

## 7. Known issues, limitations, risks
- **Not run on Windows.** Everything was verified on Linux only. Risks I considered:
  - The asyncio self-pipe needs loopback; the network guard allows it.
  - Temp-dir `.env` discovery: the test writes its own `.env` in `tmp_path`.
  - Console UTF-8.
  - CRLF in prompt files: handled in the loader.
- **Gateway lifetime.** The gateway's `asyncio.Semaphore`/`Lock` bind to the first event loop that waits on them. Use one gateway per event loop (create it inside the `asyncio.run` it serves). Reusing one instance across separate `asyncio.run()` calls can raise "bound to a different event loop". WP5 and WP6 should construct the gateway once per run.
- **The rate limiter is per process.** Concurrent processes (e.g. two eval runs) don't share a quota window.
- **Provider capability flags are provisional** (all True, `extra_body={}`) until WP0 measures them.
- **openai SDK v3.59** is a new major version and uses `httpx2`. Tests construct its real error classes and run one request through the real SDK with `httpx2.MockTransport`.
- **Delivery via bundle.** The owner's folder already has `CLAUDE.md`, `docs/` and `agent_prompts/`, and I added `.gitignore`. These are identical to `main`'s tree. To restore the repository, run from the repo root (PowerShell):
  ```
  git init -b main
  git config --local user.name "skillagent-dev"; git config --local user.email "skillagent-dev@example.invalid"
  git fetch --update-head-ok .worktrees/wp1.bundle main:main feat/foundation:feat/foundation
  git reset
  Remove-Item -Recurse -Force .worktrees\wp1      # plain file preview of the branch, not a worktree
  git worktree add .worktrees/wp1 feat/foundation
  ```
  I rehearsed this sequence on Linux in a copy of the folder. `git status` was clean on `main`, the worktree was on `feat/foundation`, and `main..HEAD` held 15 commits. Skip the `git config` line if you already have a real identity configured (ADR-019).

## 8. Questions for the architect
1. Accept `llm/types.py` and `llm/structured.py` as permanent module names (§4.1)?
2. Approve the v1.1 proposals in §4: truncate `rationale`, state that output codes are always ISO 639-1, and add `.gitattributes` for prompt files?
3. Should `provider=custom` allow keyless local endpoints (e.g. Ollama)? It currently requires `SKILLAGENT_CUSTOM_API_KEY`.
4. Is the 60 s fail-fast threshold for `retry-after` right for the eval runner, or should it be a setting?

## 9. Files touched outside my ownership
- `.python-version` (repo root): pins Python 3.12 for `uv`. It is tooling config next to `pyproject.toml`.
- `tests/conftest.py`, `tests/unit/core/**`, `tests/unit/llm/**`, `tests/unit/skills_base/**`: the test scaffold that spec §3 and §5 assign to WP1. They aren't listed in the CLAUDE.md §4 table. *Proposal:* add `tests/conftest.py` and these three `tests/unit/` folders to WP1's row.
- `.gitignore` was committed on `main` in the bootstrap step, as specified. `CLAUDE.md`, `docs/` and `agent_prompts/` were committed unchanged in that step.

## 10. Dependencies added
Runtime (exact versions in `uv.lock`): `langgraph` 1.2.24, `openai` 3.59.0, `pydantic` 2.14.4, `pydantic-settings` 2.16.3, `python-dotenv` 1.2.4, `typer` 0.29.2, `rich` 15.0.0, `pyyaml` 6.0.4.
Dev: `pytest` 9.2.0, `pytest-asyncio` 1.5.0, `ruff` 0.17.6, and **`pytest-cov` 7.1.0**. The spec didn't list `pytest-cov`; I added it to measure the ≥90% coverage target.

## 11. Commits
`git log --oneline main..HEAD` before this report commit:
```
ea512aa feat(doctor): add offline/live configuration diagnostic
7c8bd2f test(core): cover V1-V8 rules, registry, settings, providers and prompt loader
5dab36d feat(skills): add the four skill stubs and explicit default catalog
94f9b0d feat(testing): add scriptable FakeLLM and synthetic skill-spec helper
9eb73ed feat(llm): add rate-limited, retrying OpenAI-compatible gateway
cc15bca feat(llm): add async sliding-window rate limiter with injectable clock
f90768c feat(llm): add provider-agnostic LLM types and shared structured-output repair loop
75879a0 style: apply ruff format and keep markdown out of ruff
9274595 feat(prompts): add versioned prompt loader
b5a2222 feat(config): add settings and provisional provider profiles
c718afc feat(skills): add SkillSpec, budgets, context and parameter models
d033754 feat(core): add plan and skill I/O types with V1-V8 validation and skill registry
c3e9ea5 feat(core): add error hierarchy and Persian-aware language utilities
7c5442d chore: scaffold uv project with runtime and dev dependencies
```
Plus this commit, `docs(handoff): add WP1 report`, for 15 in total. On `main`: `2ee04ea docs: add architecture, contracts, decisions and agent prompts`.

## 12. Live LLM calls made
0. There was no `.env` or key in the workspace, so `doctor --live` was not run.
