# WP1 — Foundation: repository bootstrap, contracts, LLM gateway, language utilities

You are a **senior Python engineer** building the foundation of a LangGraph-based multi-skill agent. Several other agents will build on your code in parallel right after you finish, so correctness of the shared interfaces matters more than anything else. You have no prior conversation context; everything you need is in this file and the repository docs.

## 0. Read first (in this order)
1. `CLAUDE.md` (repo root) — shared rules: git worktrees, ownership, standards, reporting
2. `docs/CONTRACTS.md` — **frozen v1.0 interfaces; implement them exactly**
3. `docs/ARCHITECTURE.md` — §2–§8 for context (you are not building router, skills logic, or graph)
4. `docs/DECISIONS.md` — ADR-002, 005, 006, 010, 012

## 1. Mission
Deliver a clean, tested `skillagent` package that provides:
- core types & validation rules (CONTRACTS §1–3, §5)
- language utilities with strong Persian support (§6 + spec below)
- prompt loader (§7), settings (§8), provider profiles
- an async, rate-limited, retrying, OpenAI-compatible **LLM gateway** + a scriptable **FakeLLM** (§4)
- the skill registry, the 4 skill **stubs**, and `build_default_registry()`
- a `doctor` diagnostic command
- the test scaffold used by every later WP

**Out of scope:** router logic, real skill logic, LangGraph graph, CLI, eval. Don't build them, even partially.

## 2. Step 0 — Bootstrap (the only time `main` is committed directly)
Run in the repo root (`C:\Users\ai\Desktop\multi-skill AI agent`):
1. If `.git` doesn't exist: `git init -b main`.
2. **Git identity (owner decision, ADR-019):** the owner will supply their real identity later. If `git config user.name` or `user.email` resolves to nothing, set a **repository-local** placeholder: `git config --local user.name "skillagent-dev"` and `git config --local user.email "skillagent-dev@example.invalid"`. **Never** touch `--global` config. If a real identity is already configured, use it unchanged.
3. Create `.gitignore` with at least: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `.env`, `.worktrees/`, `eval/reports/raw/`, `*.egg-info/`, `AIEngineerTask.pdf`. The assignment PDF is the company's document and stays out of the public repo.
4. Commit the existing docs: `git add .gitignore CLAUDE.md docs agent_prompts` → `docs: add architecture, contracts, decisions and agent prompts`.
5. Create your worktree: `git worktree add .worktrees/wp1 -b feat/foundation main`, then `cd .worktrees/wp1`. All further work happens there.

## 3. Project setup
- `uv init --package --name skillagent` (or hand-write `pyproject.toml`): Python `>=3.12`, src layout **not** used (package dir `skillagent/` at repo root).
- Runtime deps: `langgraph`, `openai`, `pydantic>=2`, `pydantic-settings`, `python-dotenv`, `typer`, `rich`, `pyyaml`. Pre-adding them avoids lockfile conflicts later.
- Dev deps: `pytest`, `pytest-asyncio`, `ruff`.
- Ruff config: line-length 100, rules `E,F,I,UP,B,SIM,ASYNC`. Pytest config: `asyncio_mode = "auto"`, marker `live` (excluded by default via `-m "not live"` in addopts).
- `.env.example` documenting every variable in CONTRACTS §8, with comments and no real values.

Target layout (create only what's listed; empty `__init__.py` where needed):
```
skillagent/
  __init__.py            # __version__
  config.py
  doctor.py
  core/   __init__.py types.py errors.py registry.py language.py
  llm/    __init__.py gateway.py providers.py ratelimit.py
  prompts/__init__.py    # PromptLoader (prompt *files* are created by later WPs)
  skills/ __init__.py base.py params.py catalog.py
          summarizer.py translator.py general_chat.py   # stubs
          calculator/__init__.py                        # stub (WP2 will expand the package)
  testing/__init__.py fake_llm.py
tests/
  conftest.py
  unit/core/ unit/llm/ unit/skills_base/
```

## 4. Specifications beyond CONTRACTS.md

### 4.1 `core/language.py`
| Function | Required behaviour |
|---|---|
| `normalize_persian` | `ي`/`ى`→`ی`, `ك`→`ک`, remove tatweel `ـ`, collapse repeated ZWNJ (U+200C) into one, remove ZWNJ adjacent to spaces. **Digits and all other text unchanged.** Idempotent. |
| `to_ascii_digits` | Persian `۰–۹` and Arabic-Indic `٠–٩` → `0–9`; `٫` → `.`; `٬` removed only when between digits. |
| `to_persian_digits` | ASCII digits → Persian digits; `.` between digits → `٫`. Leaves other text alone. |
| `detect_lang_hint` | Count letters only (ignore digits, punctuation, whitespace, emoji). Arabic-script letters (U+0600–06FF, U+FB50–FDFF, U+FE70–FEFF) vs Latin letters. No letters → `unknown`. Arabic-script share ≥ 0.85 → `fa`; ≤ 0.15 → `en`; otherwise `mixed`. (All Latin text counts as `en` here; the router decides the real language.) |
| `estimate_tokens` | Conservative and language-aware: `ceil(latin_chars/4 + arabic_script_chars/2.5 + other_non_space_chars/1.5)`, minimum 1 for non-empty text. Document the rationale (Persian tokenizes ~2–3× worse). |
| `truncate_to_tokens` | Returns `(text, truncated)`. If over budget, cut at the last sentence boundary (`.!?؟\n`), else whitespace, before the limit. Never mid-word. |
| `normalize_lang_code` | Accepts codes (`fa`, `EN`, `fr-FR`→`fr`), English names (`Persian`, `Farsi`, `English`, `German`, `French`, `Arabic`, `Spanish`, `Turkish`, `Chinese`, `Russian`, `Italian`, `Japanese`…), and Persian names (`فارسی`, `انگلیسی`, `آلمانی`, `فرانسوی`, `عربی`, `ترکی`, `اسپانیایی`, `روسی`, `چینی`). Unknown → `ValueError`. |
| `strip_think` | Remove `<think>…</think>` blocks (multi-line, case-insensitive) and an unterminated leading `<think>…` prefix; strip surrounding whitespace. |
| `extract_json_object` | Strip markdown code fences; return the first balanced top-level `{…}`, respecting strings and escapes. Raise `ValueError` if none. |

### 4.2 `core/types.py` & `core/registry.py`
Implement CONTRACTS §1–3 exactly, including validation rules V1–V8 and canonical skill-name resolution (lowercase, spaces and hyphens → underscores). V5–V8 apply only when the context provides `registry` / `max_skills`. Error messages must be clear enough for an LLM to repair its output, e.g. `"steps[1].input_from='s3' must reference an earlier step id or 'user'"`.

### 4.3 `config.py` & `llm/providers.py`
- `Settings` per CONTRACTS §8. Add `get_settings()` (cached) and `Settings.api_key()` → the `SecretStr` for the active provider; raise `ConfigError` with an actionable message if it's missing.
- `.env` discovery: search upward from CWD (`dotenv.find_dotenv(usecwd=True)`) so worktrees find the root `.env`.
- `ProviderProfile` with the provisional values from CONTRACTS §8. Set `supports_system_role=True`, `supports_json_mode=True`, `supports_tools=True` and `extra_body={}` for now; WP0 will measure the real values.

### 4.4 `llm/ratelimit.py` + `llm/gateway.py` — `OpenAICompatGateway(settings, profile=None)`
- Uses `openai.AsyncOpenAI(base_url=…, api_key=…, max_retries=0)`. **We** handle retries.
- **Concurrency:** one `asyncio.Semaphore(llm_max_concurrency)` per gateway instance. **Rate:** an async sliding-window limiter of `llm_rpm` requests per 60 s, shared by the instance. Create one gateway per process and reuse it.
- **Retries:** up to `llm_max_retries` on 429, 5xx, timeouts and connection errors. Exponential backoff (1 s, 2 s, 4 s…) with ±25% jitter, and honour `retry-after` when present. No retry on other 4xx; map them to `LLMProviderError` with the provider's message, keys never included.
- **Timeout:** `asyncio.wait_for` with `timeout_s or settings.llm_timeout_s`.
- **System role:** if `profile.supports_system_role` is False, merge system messages into the first user message as `"[Instructions]\n…\n\n[User]\n…"`.
- **JSON mode:** `response_format={"type": "json_object"}` when `json_mode` is set and supported. If the provider rejects it (400 mentioning response_format), retry once without it, cache that it's unsupported, and log a warning.
- **Tools:** map `ToolSpec` → OpenAI `tools`. `tool_choice` `"required"` or a tool name → OpenAI format. Parse tool calls into `ToolCall` (invalid JSON arguments → `arguments={}` with `raw_arguments` kept).
- Apply `profile.extra_body`. Strip `<think>` from text. Fill `LLMUsage`, `latency_ms`, `model` and `attempts`.
- **`complete_structured`:**
  1. Call `complete(json_mode=True)`.
  2. Run `extract_json_object` on the text.
  3. `schema.model_validate_json(..., context=validation_context)`. Use `model_validate(json.loads(...), context=...)` if needed for context support.
  4. On parse or validation failure, append the assistant reply plus a user message: `"Your previous output was invalid: <concise error>. Return ONLY a corrected JSON object that fixes this."` Retry up to `max_repairs` times with `purpose=f"{purpose}:repair"`.
  5. If it still fails, raise `StructuredOutputError(raw_text, errors)`.
- Log via stdlib `logging` (logger `skillagent.llm`): purpose, model, attempts, latency and token counts. **Never prompt contents at INFO or above, and never keys.**

### 4.5 `testing/fake_llm.py` — `FakeLLM`
Implements `LLMClient` deterministically for tests:
```python
FakeRule(match: Callable[[list[ChatMessage], str], bool] | str,   # str = regex searched in purpose + last user message
         reply: str | list[ToolCall] | Exception | Callable[[list[ChatMessage]], str],
         times: int | None = None)                                  # None = unlimited
FakeLLM(rules: list[FakeRule], default: str | None = None)          # no match & no default → AssertionError naming the purpose
.calls -> list[RecordedCall(purpose, messages, kwargs)]
```
`complete_structured` must reuse the **same** parse/validate/repair logic as the real gateway. Factor that logic into a shared helper, so router repair behaviour can be unit-tested with FakeLLM.

### 4.6 `prompts/__init__.py` — `PromptLoader` per CONTRACTS §7
Default root = the `skillagent/prompts` package directory. Version files match `v(\d+)\.md`. Pinned versions come from `Settings.prompt_versions`. Unknown name or version → `FileNotFoundError` listing what's available.

### 4.7 Skills scaffold
- `skills/base.py`, `skills/params.py` exactly per CONTRACTS §1.3 and §2.
- Four stubs. Each module exposes `SPEC: SkillSpec` with the fixed fields from the CONTRACTS §2 table, a reasonable one-line description, 2 bilingual `when_to_use` cues, and a `run` that returns `SkillOutput(status="ok", output=f"[stub:{name}] {instruction}")`. Budgets: summarizer (4000 in / 700 out / 30 s / 0.3), translator (4000 / 1500 / 30 s / 0.2), calculator (800 / 300 / 20 s / 0.0), general_chat (1500 / 600 / 25 s / 0.7). Later WPs replace these files completely.
- `skills/catalog.py`: `build_default_registry()` imports the four `SPEC`s explicitly (no auto-discovery magic; explicit is easier to explain).

### 4.8 `doctor.py` (`uv run python -m skillagent.doctor`)
Prints provider, model, base URL, and key presence (masked: first 4 + last 4 characters). With `--live`, it sends one plain completion ("Reply with OK") and one `complete_structured` call with a trivial schema, printing latency, tokens and success. Exit codes: 0 OK, 2 config error, 3 provider error. Without `--live` it makes **no network calls**.

## 5. Tests (offline, fast; aim for ≥ 90% coverage of `core/` and the gateway helper logic)
Use FakeLLM, or a stubbed `AsyncOpenAI` via monkeypatch/`httpx.MockTransport` for the gateway. Must include:
- **language:** each function, including Persian edge cases: mixed text, ZWNJ, Arabic letters, Persian and Arabic-Indic digits, `۳٫۵`, `۱٬۲۰۰`, Finglish → `en`, emoji-only → `unknown`, idempotency, truncation that never cuts words, think-stripping, and JSON extraction from fenced or noisy text.
- **types:** every rule V1–V8 (positive and negative), canonical name resolution, `LangCode` normalization (`"Persian"` → `fa`, `"فارسی"` → `fa`).
- **registry:** duplicate and unknown errors, ordering, `build_default_registry()` has exactly the 4 names.
- **gateway:**
  - retry on 429 with retry-after
  - no retry on 400
  - timeout → `LLMTimeoutError`
  - JSON-mode fallback
  - system-role merging
  - tool-call parsing
  - `<think>` stripping
  - concurrency never exceeds the semaphore (instrumented fake)
  - rate limiter (use an injectable clock; don't sleep for real)
- **structured:** success, repair-then-success, repair-exhausted → `StructuredOutputError`, and validation context passed through.
- **prompts:** highest version, pinned version, render with a missing variable.
- **doctor:** a config error without a key returns exit code 2 with no network.

## 6. Acceptance criteria
- [ ] `uv sync` then `uv run pytest -q` all green offline. `uv run ruff check .` and `uv run ruff format --check .` are clean.
- [ ] Every name in CONTRACTS §1–8 exists with matching signatures and fields.
- [ ] `uv run python -c "from skillagent.skills.catalog import build_default_registry as b; print(b().names())"` prints the 4 skills.
- [ ] `uv run python -m skillagent.doctor` without `.env` exits 2 with a helpful message.
- [ ] No network access in tests; no keys anywhere in the repo.
- [ ] 8–15 logical Conventional Commits on `feat/foundation`.
- [ ] `docs/handoffs/WP1_report.md` written from `docs/handoffs/TEMPLATE.md` and committed.

## 7. Constraints
- **Live LLM calls:** 0 required. If `.env` with a key exists you may run `doctor --live` once (2 calls max). Report it.
- Don't implement anything listed as out of scope. Don't change frozen contracts. If something in them is unimplementable or contradictory, implement the closest faithful version, flag it in report §4, and keep going.
- Keep modules small and readable; reviewers will read this code in an interview.

## 8. Report
Follow `CLAUDE.md` §9. In §5 of the report, explicitly list any judgement calls you made where this spec was silent.
