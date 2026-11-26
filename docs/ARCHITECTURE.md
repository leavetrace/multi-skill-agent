# ARCHITECTURE — Multi-Skill AI Agent

> **Status: v1.0 — ACCEPTED by owner 2026-11-25.** Interfaces frozen in `docs/CONTRACTS.md` (currently v1.4; normative; wins over §3 below if they ever differ).
> Owner: Chief Architect (coordinator session). Single source of truth for design.
> Any agent that finds a conflict between its task prompt and this file must stop and report it, not resolve it silently.

---

## 0. Requirement classes used in this document

| Tag | Meaning |
|---|---|
| **[M]** | Mandatory — stated in `AIEngineerTask.pdf` |
| **[O]** | Our additional objective — not required, chosen to strengthen the deliverable (e.g. scalability emphasis from the interview) |
| **[D]** | Architectural decision — our choice among valid options (see `DECISIONS.md`) |

Full requirement traceability: `docs/REQUIREMENTS.md`.

---

## 1. Problem framing

The brief is small (4 skills, ≤2 per request, CLI), but it's graded on routing accuracy, prompt quality, calculator correctness, graph design, Persian handling, edge cases and documentation. The interviewer also asked how the design holds up at 10–20+ skills.

There are two traps:
1. **Under-design.** Hardcoding `router → if/else → 4 nodes` plus a special edge for "summarize then translate". It works for 4 skills, falls apart at 20, and gives nothing to defend in the interview.
2. **Over-design.** Shipping production infrastructure or more than 4 skills. The brief explicitly puts that **out of scope** [M].

**Resolution [D]:** ship *exactly* 4 skills and ≤2 per request, but make the *mechanisms* (registry, plan validation, scheduler, budgets, candidate selection) generic. Then show that they scale with **tests that use synthetic skills**, not with extra product skills.

### What actually breaks as skills grow 4 → 20+

The usual intuition is that "the router prompt gets too big". Our estimate is that this is the smallest of the problems:

| Growth vector | 4 skills | 20 skills | Real risk | Mechanism |
|---|---|---|---|---|
| Router prompt size (skill cards ≈ 60–100 tokens each) | ~400 tok | ~2K tok | Low until ~50+ skills | Compact generated cards; Top-K candidate selection above a threshold |
| **Confusion between similar skills** (accuracy) | low | **high** | **Primary risk** | Disambiguation notes in cards, bilingual negative examples, per-skill precision/recall in eval |
| **Graph wiring** if combinations are hardcoded | 4 nodes + few edges | O(N²) edges | High | Graph is generated from the registry; one generic scheduler; no pairwise edges |
| **Execution fan-out** (LLM emits a 6-step plan) | — | high | High | Hard limits in code (max steps, max parallel, max depth), not in the prompt |
| **Context accumulation** across chained steps | low | high | High | Each step receives only its declared input; no shared transcript |
| **Provider rate limits** under parallelism | low | high | High on free tiers | Global semaphore + rate limiter + retry/backoff in one LLM gateway |
| Invalid compositions (e.g. summarize a number) | n/a | medium | Medium | Typed skill I/O (`input_kind`/`output_kind`) checked during plan validation |

So the scalability story rests on **six code-enforced mechanisms**, not on prompt tricks (§7).

---

## 2. High-level architecture — "Validated plan, dynamic dispatch"

```
                ┌──────────────┐
  raw prompt ──▶│  preprocess  │  deterministic: Persian normalization, digit mapping,
                └──────┬───────┘  script-based language hint, input-size budget check
                       ▼
                ┌──────────────┐  1. candidate selection (all skills if N ≤ threshold, else Top-K)
                │    router    │  2. LLM → RoutingDecision (JSON) → Pydantic validation
                └──────┬───────┘  3. one repair retry on validation error → else safe fallback
                       ▼
             route_after_router()            (conditional edge)
        ┌──────────────┼──────────────────────┐
        ▼              ▼                      │
   ┌─────────┐   ┌───────────┐                │
   │ clarify │   │ scheduler │◀───────────┐   │
   └────┬────┘   └─────┬─────┘            │   │
        │        dispatch(): Send() for   │   │
        │        every READY step         │   │
        │        (deps satisfied, ≤ max_parallel)
        │      ┌───────┼────────┬────────┐│   │
        │      ▼       ▼        ▼        ▼│   │
        │  [summarizer][translator][calculator][general_chat]   ← one node per registered skill,
        │      └───────┴────┬───┴────────┘    generated from the registry
        │                   │ results merged by reducer keyed by step_id
        │                   └──── back to scheduler (next wave) ─┘
        │        when no steps remain
        │                   ▼
        │            ┌────────────┐  deterministic: format results, partial-failure notes,
        │            │  composer  │  "skipped 3rd skill" notice, response language
        │            └─────┬──────┘
        └──────────────────┴──────▶ END → CLI prints response (+ optional trace)
```

**Why this shape [D] (ADR-001):**
- The *router* decides **what** to run (a small validated DAG of ≤2 steps). The *scheduler* decides **when** (topological waves). Skills decide **how**. Each concern is testable on its own.
- **Parallel and sequential are one mechanism.** Independent steps land in the same wave and run concurrently through LangGraph `Send`. A dependent step waits for the next wave. The README question "how do you combine two skills?" has a principled answer: *by declared data dependency*.
- **LangGraph `Send` gives context isolation for free.** A skill node receives only the `Send` payload (`StepTask`), never the full graph state.
- Adding a skill means registering one `SkillSpec`. The router prompt, the node list and the routing enum are all generated. No edges change.

---

## 3. Core contracts (summary)

> Summary only — the normative, complete version is **`docs/CONTRACTS.md`** (adds `SkillOutput`, `StepTask`, `TraceEvent`, param models, IO `accepts` sets, LLM gateway protocol, settings, public `run_agent` API). Package name is `skillagent`.

| Contract | Purpose | CONTRACTS § |
|---|---|---|
| `UserRequest` | normalized prompt + script hint + token estimate | 1 |
| `PlanStep`, `RoutingDecision` (+ rules V1–V8) | the router's validated mini-DAG; skill limit and IO-kind checks are enforced in the validator | 1, 1.1 |
| `SkillInput` → `SkillOutput` | the only data a skill sees, and what it returns | 1.2 |
| `SkillResult`, `StepTask`, `TraceEvent` | wrapper result, `Send` payload, observability | 1.2 |
| `SkillSpec`, `SkillBudget`, `SkillContext` | registry entry: cards, `accepts`/`output_kind`, budgets, runner | 2 |
| `SkillRegistry`, `build_default_registry()` | canonicalizing lookup; exactly 4 product skills | 3 |
| `LLMClient` (`complete`, `complete_structured`), `FakeLLM` | provider-agnostic gateway with repair loop; offline test double | 4 |
| `PromptLoader` | versioned prompt files, pinning for v1-vs-v2 eval | 7 |
| `Settings`, `ProviderProfile` | every limit and budget is configurable | 8 |
| `run_agent()` → `AgentRun` | public API for CLI and eval | 9 |
| `AgentState` | graph state with reducers | 10 |

## 4. Node-by-node design

### 4.1 `preprocess` (deterministic, no LLM)
- Normalize Arabic → Persian characters (`ي→ی`, `ك→ک`). Map Persian (`۰–۹`) and Arabic-Indic (`٠–٩`) digits to ASCII in a *calculation view*, while keeping the original text for translation and summarization. Persian decimal `٫` and thousands `٬` separators are handled too.
- Language hint from the Persian/Latin script ratio → `fa | en | mixed`. Finglish (Persian in Latin script) can't be caught this way, so the router decides `response_language`.
- **Language-aware token estimate.** Persian costs ~2–3× more tokens per character than English with most tokenizers. If the input exceeds the global input budget, the request is answered with a polite limit message and no LLM call is made.

### 4.2 `router` (1 LLM call, sometimes 2)
- **Candidate selection** (`CandidateSelector` interface): `AllSkills` when `N ≤ router.top_k_threshold` (default 12; so it's always on for our 4). Above the threshold: `BM25TopK` over skill cards, including Persian cues. `general_chat` is always included as the safety net.
- Prompt is **generated from the registry**: role, output JSON schema, skill cards, decision rules, bilingual few-shots. It includes single, chained, parallel, ambiguous, no-match, >2 intents and prompt-injection cases.
- **Strategy for structured output [D] (ADR-010):** JSON mode + Pydantic validation + **one repair retry** that feeds back the validation error. We don't rely on provider-side JSON-schema enforcement because free endpoints don't guarantee it (OpenRouter lists Gemma 4 as "JSON without schema enforcement"). This approach works across providers.
- **The router never copies the payload [D] (ADR-002).** It emits a short `instruction` (≤300 chars) and an `input_from` reference. Echoing a 2,000-word text would double output tokens and latency, and the model might alter the text. Skills resolve their own input.
- **Deterministic fast path [D]:** if the normalized prompt is a pure arithmetic expression (strict regex), emit `[calculator]` without calling the LLM. It's cheaper and 100% reliable, and it shows up in the trace as `route_source="rule"`.
- **Thinking/reasoning modes are disabled** for router calls, and any `<think>` blocks are stripped defensively.
- Temperature 0.

### 4.3 Conditional edge `route_after_router`
| Condition | Next |
|---|---|
| `needs_clarification` | `clarify` |
| `steps` non-empty | `scheduler` |
| router failed after repair / provider error | `scheduler` with plan `[general_chat]`, flagged `degraded` |

### 4.4 `scheduler` + `dispatch` (deterministic)
- READY = steps not yet done whose `input_from` result is `ok`.
- `dispatch` returns `[Send(skill_node, StepTask)]` for up to `max_parallel` READY steps, or `"composer"` when nothing remains.
- If a dependency failed, its dependents are marked `skipped` and never run, so errors don't cascade.
- Hard caps: `max_steps`, `max_waves`, overall `request_deadline_s`. The LangGraph `recursion_limit` is set from these caps as a backstop.

### 4.5 Skill nodes (one per registered skill, generated)
Generic wrapper: build `SkillInput` (resolve `text` from user or dependency; truncate to `budget.max_input_tokens` only for skills without `requires_payload`, because payload skills own their budgets — CONTRACTS §15), run `spec.run` under `asyncio.wait_for(timeout_s)`, convert exceptions into `SkillResult(status=error)`, and record latency and tokens in `meta`.

| Skill | Approach (prompt details in WP3/WP2 prompts) |
|---|---|
| **Summarizer** | Faithful, no added facts. Length adapts to input size. Output language = `response_language` unless overridden. Text arrives inside `<text>` delimiters and is treated as data, never as instructions. Input that's too short gets a clarification or a pass-through note. |
| **Translator** | `params.target_language`, `params.source_language?`. Default when the target is unspecified: fa→en, otherwise →fa (documented assumption). Output is the translation only, with no preamble. Formatting, numbers and named entities are preserved. Persian output uses standard written Persian with correct ZWNJ (نیم‌فاصله) and Persian punctuation `، ؛ ؟`. Injection resistance: it translates commands, it doesn't execute them. |
| **Calculator** | LLM **tool call** `evaluate(expression)` (forced `tool_choice`) → **safe AST evaluator** (whitelisted nodes and functions, no `eval`/`sympify`). Exact `Fraction` arithmetic where possible. DoS guards on exponent, factorial and digit size. The number in the answer always comes from the tool and the LLM never states it. The response is formatted deterministically, with Persian digits when `response_language=fa`. The fast path skips the LLM entirely. |
| **General Chat** | Greetings, small talk, general knowledge, and the no-match fallback. Answers in `response_language`. Honest about its limits ("I can't book flights; here's what I can do…"). Doesn't do arithmetic: if math appears here, that's counted as a router error in eval. |

### 4.6 `clarify` (deterministic)
Returns the router's `clarification_question` in the user's language. Because there's **no cross-request memory** [M out-of-scope], the message asks the user to resend the *full* request with the missing detail. This is documented as a limitation.

### 4.7 `composer` (deterministic, no LLM) [D] (ADR-003)
- 1 step → its output.
- Chain → the final output (intermediate output available in `--trace`).
- Parallel → labeled sections in `response_language`.
- Partial failure → the successful outputs plus a short localized error note. Dropped intents → a localized notice ("I handle up to 2 tasks per request; skipped: …").
- Why not an LLM synthesizer: it adds a call, cost and latency, and it can paraphrase away exact translations or calculator results. It's available as a future option.

---

## 5. Fallback & ambiguity policy (ADR-007)

| Situation | Behaviour | Rationale |
|---|---|---|
| Small talk / general question | `general_chat` (normal route, not a fallback) | It's a first-class skill |
| Request outside all skills ("book a flight") | `general_chat`, which explains its capabilities | Helpful, never a dead end |
| Skill clear, required input missing ("translate this") | `clarify` | Can't be guessed |
| Intent genuinely ambiguous between skills, high cost of a wrong guess | `clarify` | Avoids confident wrong answers |
| Intent mildly ambiguous, a cheap reasonable guess exists | proceed with best guess (confidence logged) | Avoids annoying over-clarification |
| >2 intents | execute first 2 (user order), notify about the rest | Spec limit with graceful UX |
| Router output invalid after repair / provider error | `general_chat` degraded; static bilingual apology if that fails too | The CLI never crashes |
| Prompt injection inside payload | executes the user's skill on the text as data | Delimiters + explicit rule + eval case |

Over- and under-clarification are both measured in eval.

---

## 6. LLM gateway & provider (ADR-006)

A single gateway (`skillagent/llm/`, `OpenAICompatGateway`) is the only code that talks to providers:
- Plain `openai.AsyncOpenAI` with `base_url` (ADR-015: no LangChain model wrapper, which means fewer layers and explicit control of JSON mode, tools and `extra_body`). Switching providers is a config change; Google AI Studio, Groq and OpenRouter all expose OpenAI-compatible endpoints. Per-provider quirks (system-role support, JSON mode, tools, thinking control) live in a `ProviderProfile` measured by WP0.
- A **global** `asyncio.Semaphore(llm_max_concurrency)` plus a sliding-window RPM limiter, shared by all requests and eval workers.
- Retries with exponential backoff and jitter on 429/5xx, honoring `retry-after`. Per-call timeout.
- Per-call `max_tokens` from the skill budget, thinking disabled, `<think>` stripping, token-usage capture for the trace.

**Provider/model candidates** (research 2026-11-25; final choice after the WP0 measured bake-off):

| Candidate | Params | Free-tier limits (published) | Notes |
|---|---|---|---|
| **Gemma 4 31B IT** via Google AI Studio (Gemini API) | 30.7B **dense** | Free tier; per-project limits in AI Studio | **Leading candidate.** Dense, so the ≤35B claim is unambiguous. Strong multilingual. Same model also free on OpenRouter. Note: free-tier data may be used by Google for training. |
| **Qwen3.8-27B** via Groq | 27B **dense** | 30 RPM, 1K RPD, 8K TPM, 200K TPD | Very fast. *Preview* model; Groq retired qwen3-32b / qwen3.6-27b this year → deprecation risk. 8K TPM caps long-text summarization. |
| Gemma 4 26B A4B (MoE) | 25.2B total / 3.8B active | Free on OpenRouter & AI Studio | Fallback; MoE "parameter count" wording needs care. |
| Any `:free` model via OpenRouter | — | **20 RPM, 50 requests/day** without ≥10 purchased credits | **Not primary.** One eval run ≈ 35–45 calls, so 50/day blocks iteration. Buying credits to lift the cap muddies the "free-tier" claim. |

Decision rule: dense ≤35B, free with no card, best measured **routing validity + Persian quality** in WP0, with a second provider configured as a documented alternate.

---

## 7. Scalability & explosion-control mechanisms [O]

All limits live in `config.py` (pydantic-settings, env-overridable) and are **enforced in code**:

| # | Mechanism | Where | Default |
|---|---|---|---|
| 1 | **Registry-generated everything** — router cards, routing enum, graph nodes | registry, graph builder | — |
| 2 | **Candidate selection (Top-K)** above threshold; `general_chat` always included; recall@K measured | router | threshold 12, k 6 |
| 3 | **Per-request skill limit**, overflow → `dropped_intents` | Pydantic validator + scheduler | 2 (spec) |
| 4 | **Execution bounds**: max steps, max waves, max parallel per request, request deadline, per-step timeout | scheduler, skill wrapper | 2 / 2 / 2 / 60s / 25s |
| 5 | **Global concurrency + rate limiting** across requests | LLM gateway | e.g. 4 concurrent, provider RPM |
| 6 | **Context isolation & minimal state**: skills get `SkillInput` only; chains pass only the declared dependency's output; router rationale never reaches skills | `Send` payload, wrapper | — |
| 7 | **Token budgets**: language-aware input estimate, per-skill max in/out tokens, truncation/rejection with notice | preprocess, wrapper, gateway | per skill |
| 8 | **Typed composition**: `input_kind`/`output_kind` checked at plan validation | `RoutingDecision` validator | — |
| 9 | **Fast-path rules** reduce LLM calls for trivially classifiable inputs | router | arithmetic only |

**How we prove it without violating "exactly 4 skills":** `tests/scalability/` registers 20 synthetic skills with a fake LLM. It asserts that the graph builds without code changes, measures router-prompt tokens versus N, verifies that limits and isolation hold, and measures BM25 Top-K recall on synthetic bilingual queries. The results go in a README table.

**Alternatives challenged:**
- *Embedding-based Top-K:* better semantic recall, but it needs an embedding API or model (an extra provider, latency and free-quota use). BM25 over curated bilingual cues is enough at 20 skills, and the selector is an interface so embeddings can be swapped in later.
- *Hierarchical routing (category → skill):* appropriate at 50–100+ skills. It adds an LLM hop, which isn't justified at 20.
- *Top-K always on:* it reduces recall for no benefit at small N. That's why there's a threshold.

---

## 8. Persian language handling (summary)
1. Normalization (chars, digits, separators) before routing and calculation; the original text is preserved for translation and summarization.
2. Script-ratio language hint plus router `response_language` (instruction language wins in mixed prompts).
3. Bilingual skill cards and few-shots, including Persian number words ("بیست و پنج درصد") and Finglish.
4. Persian style rules in prompts: ZWNJ, punctuation, formal written register by default.
5. Language-aware token budgets.
6. CLI: forced UTF-8 I/O (`PYTHONUTF8`, `reconfigure`), `--file` input for long or multi-line text, `--out` to write the response to a UTF-8 file. Windows terminals render RTL/bidi text inconsistently, so this needs a real test on the owner's machine.
7. Native-speaker review of Persian outputs (owner) with a small rubric, alongside automated checks (output script, Arabic chars, preamble leakage).

---

## 9. Evaluation design (WP6)
- **Datasets:** `eval/test_set.yaml` (15 prompts, reported in the README, frozen before final prompt tuning) and `eval/dev_set.yaml` (~30–40 prompts used during prompt iteration). The split avoids overfitting the reported numbers.
- **Coverage:** EN, FA, mixed and Finglish; each skill alone; chain and parallel; ambiguous / missing input; no-match; >2 intents; prompt injection; calculator edge cases.
- **Metrics (measured, never invented):** skill-set exact-match accuracy; per-skill precision/recall; plan-structure accuracy (chain vs parallel, correct dependency); clarification correctness; calculator numeric exactness; output checks (language/script, preamble leakage, Arabic chars); latency p50/p95; LLM calls per request.
- **Reproducibility:** report the model id, provider, date, prompt-version hashes and temperature. Run **3 times** and report mean and min–max, because free endpoints are nondeterministic even at T=0.
- **Prompt-improvement evidence:** prompts are versioned files (`skillagent/prompts/*/vN.md`). The runner records the version. v1 → v2 deltas, with real numbers, go in the README.
- **Offline tests:** a `FakeLLM` scripted harness lets the full graph run in `pytest` without network access.

---

## 10. Repository layout (target)
```
multi-skill-agent/            # GitHub repo name; Python package: skillagent
  README.md  CLAUDE.md  pyproject.toml  uv.lock  .env.example  .gitignore
  skillagent/
    config.py  doctor.py  api.py  cli.py  __main__.py
    core/        types.py errors.py registry.py language.py
    llm/         types.py structured.py gateway.py providers.py ratelimit.py
    router/      router.py cards.py candidates.py fast_path.py         (WP4)
    skills/      base.py params.py catalog.py summarizer.py translator.py general_chat.py
                 calculator/ (evaluator.py, tool.py, skill.py)          (WP2)
    graph/       state.py builder.py scheduler.py nodes.py composer.py  (WP5)
    prompts/     __init__.py (loader) + router/ summarizer/ translator/ calculator/ general_chat/  v<N>.md
    testing/     fake_llm.py
  eval/          test_set.yaml dev_set.yaml runner.py metrics.py reports/
  tests/         unit/ integration/ scalability/
  spikes/        model_bakeoff/                                         (WP0, throwaway)
  docs/          ARCHITECTURE.md CONTRACTS.md DECISIONS.md REQUIREMENTS.md TASK_BOARD.md handoffs/
  agent_prompts/ README.md WP*.md
```

## 11. Tech stack [D]
Python 3.12, `uv`, `langgraph`, `openai` (AsyncOpenAI against OpenAI-compatible endpoints), `pydantic` v2, `pydantic-settings`, `typer` + `rich` (CLI), `pytest` + `pytest-asyncio`, `ruff`. Async end to end. Optional: a minimal `Dockerfile` (the brief calls it "a plus"), built last if there's time.

## 12. Development workflow (multi-agent)
- Coordinator (architect session) owns `docs/`, `CLAUDE.md`, `agent_prompts/`, `README.md`; reviews every WP against this document and CONTRACTS before merge.
- Each WP agent: own branch + own git worktree under `.worktrees/` (git-ignored) so parallel sessions never share a working tree; strict file ownership (CLAUDE.md §4) so branches merge without conflicts.
- Owner merges approved branches into `main` with `git merge --no-ff` (keeps feature-branch structure visible — git-hygiene bonus). History is pushed to GitHub when the repo is created; local branch history is preserved.
- Handoff = `docs/handoffs/WPx_report.md` on the WP branch (template in `docs/handoffs/TEMPLATE.md`).
- The assignment PDF is not committed (company document; public repo). README restates requirements in our own words.
