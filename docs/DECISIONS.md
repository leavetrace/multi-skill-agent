# DECISIONS — Architecture Decision Log

> Status values: **Proposed** (awaiting owner review) · **Accepted** · **Superseded**.
> Each entry: context → decision → alternatives → consequences. Keep entries short; ARCHITECTURE.md has the detail.

---

### ADR-001 — Plan-then-execute with registry-generated nodes and dynamic `Send` dispatch
**Status:** Accepted
**Context:** We need ≤2 skills per request, either parallel or chained, and a design that scales to 20+ skills.
**Decision:** The router emits a validated mini-DAG (`steps` with `input_from`). A deterministic scheduler dispatches READY steps in waves through LangGraph `Send` to per-skill nodes generated from the registry.
**Alternatives:** (a) static conditional edges plus hardcoded combination edges, which grows O(N²) and has no generic dependencies; (b) a ReAct/tool-calling loop, which gives unbounded iterations, no explicit validated routing and weak behavior on small models; (c) a supervisor multi-agent setup, which adds extra LLM hops per step; (d) a pure embedding classifier, which can't extract dependencies or params.
**Consequences:** Parallel and sequential share one mechanism. Graph topology is static in code but generated from data. Routing is inspectable and measurable.

### ADR-002 — Router never reproduces the payload
**Status:** Accepted
**Decision:** `PlanStep.instruction` is ≤300 chars. Skills receive the original prompt (or the dependency's output) plus the instruction.
**Why:** Echoing the payload doubles tokens and latency, risks silent alteration and blows output budgets on free tiers.
**Trade-off:** Skills must separate instruction from content themselves. This is handled with delimiters and explicit prompt rules, and tested.

### ADR-003 — Deterministic composer (no synthesis LLM call)
**Status:** Accepted
**Why:** Cheaper, faster and explainable, and it never paraphrases away an exact translation or calculator result.
**Trade-off:** Combined answers are sectioned rather than fluent prose. An LLM synthesizer is left as a future option.

### ADR-004 — Calculator = forced tool call + safe AST evaluator + exact arithmetic + fast path
**Status:** Accepted
**Decision:** The LLM translates natural language (EN/FA, number words) into `evaluate(expression)`. A custom whitelisted `ast` evaluator computes the result with `Fraction` where possible. Guards cover exponent, factorial and result size. No `eval`, no `sympify` (sympify uses `eval` internally and is unsafe on untrusted input). A pure-expression regex fast path skips the LLM.
**Why:** The brief requires a real computational tool [M]. The tool-call interface shows genuine tool use, and exact arithmetic avoids `0.1+0.2` artifacts.
**Risk:** Some free endpoints have unreliable tool calling. Mitigation: a JSON-mode fallback that uses the same evaluator.

### ADR-005 — Deterministic language detection + router `response_language`; Persian normalization
**Status:** Accepted
**Decision:** Script ratio gives the hint, and the router decides the response language (the instruction language wins in mixed prompts). Persian char/digit normalization happens in `preprocess`.
**Assumption (documented):** A summary is written in the user's instruction language unless the user specifies otherwise.

### ADR-006 — OpenAI-compatible gateway; provider chosen by measured bake-off
**Status:** Accepted (direction). Leading candidate **superseded by ADR-026**: Groq Qwen3.8-27B is primary.
**Leading candidate:** Gemma 4 31B IT (30.7B dense) via Google AI Studio free tier. **Alternate:** Qwen3.8-27B (27B dense) via Groq free tier.
**Rejected as primary:** OpenRouter `:free` models, capped at 50 requests/day without purchased credits, which is too few for evaluation iteration.
**Rule:** Prefer dense models so "≤35B parameters" is unambiguous.

### ADR-007 — Fallback & clarification policy
**Status:** Accepted
**Decision:** The matrix in ARCHITECTURE §5. Key rules: no-match goes to general_chat; missing input or high-cost ambiguity goes to clarify; mild ambiguity proceeds with the best guess; >2 intents executes the first 2 and notifies; router failure falls back to degraded general_chat.
**Limitation:** There's no cross-request memory, so clarification asks the user to resend the full request.

### ADR-008 — Scalability via code-enforced limits; Top-K only above a threshold
**Status:** Accepted
**Decision:** Nine mechanisms (ARCHITECTURE §7). BM25 Top-K candidate selection activates when N > 12, `general_chat` is always included, and recall@K is measured. It's proven with 20 synthetic skills in tests only.
**Alternatives:** Always-on Top-K (recall loss for no gain), embeddings (extra provider), hierarchical routing (only worth it at 50+).

### ADR-009 — Context isolation through `Send` payloads
**Status:** Accepted
**Decision:** Skill nodes receive `StepTask` → `SkillInput` only. There's no shared transcript, and the router rationale never reaches skills.

### ADR-010 — Structured output: JSON mode + Pydantic + one repair retry
**Status:** Accepted
**Why:** Portable across providers that don't enforce JSON schemas. A bounded retry prevents loops.

### ADR-011 — Evaluation: dev/test split, 3 runs, versioned prompts, measured only
**Status:** Accepted

### ADR-012 — Stack: Python 3.11+, uv, async LangGraph, typer+rich, pytest, ruff
**Status:** Accepted

### ADR-013 — Ship exactly 4 skills; scalability demonstrated by synthetic tests
**Status:** Accepted
**Why:** More than 4 skills is explicitly out of scope [M]. The interviewer's scaling concern is answered by mechanisms plus measurements, not by extra product features.

### ADR-014 — Documentation layout
**Status:** Accepted
`docs/` holds the living design docs, `docs/handoffs/` holds per-WP reports, `agent_prompts/` holds agent task prompts, and the root `CLAUDE.md` holds shared agent conventions. Together these are the AI-usage disclosure artifacts the brief asks for.

### ADR-015 — Plain `openai.AsyncOpenAI` gateway instead of LangChain chat-model wrappers
**Status:** Accepted
**Why:** we need precise control over `response_format`, `tool_choice`, `extra_body` (thinking control), retries and rate limiting across three providers with different quirks; one thin gateway is easier to test (FakeLLM implements the same protocol) and to explain. LangGraph does not require LangChain models.
**Trade-off:** we re-implement small conveniences (structured-output repair, tool-call parsing) — ~150 lines, fully tested.

### ADR-016 — One worktree + branch per agent; strict file ownership; owner merges with `--no-ff`
**Status:** Accepted
**Why:** several Claude sessions run concurrently on one machine; sharing a working tree would corrupt each other's checkouts. Ownership map (CLAUDE.md §4) makes merges conflict-free by construction; stubs for all 4 skills are created in WP1 so no two WPs edit the same file.

### ADR-017 — Naming
**Status:** Accepted
GitHub repo `multi-skill-agent`; Python package `skillagent`; CLI `python -m skillagent`. Language codes are ISO 639-1 (`response_language`), separate from the deterministic script hint (`fa|en|mixed|unknown`).

### ADR-018 — Assignment PDF excluded from the public repository
**Status:** Accepted — company-authored document; README paraphrases requirements.

### ADR-019 — Placeholder git identity until the owner provides theirs
**Status:** Accepted (owner request, 2026-11-25)
**Decision:** WP1 bootstrap sets a repository-local identity `skillagent-dev <skillagent-dev@example.invalid>` (worktrees share it). Nothing is pushed before the GitHub repo exists.
**Before the first push:** rewrite author and committer on all commits to the owner's identity while **preserving merge commits and branch structure**. Use `git filter-repo --mailmap` (preferred) or `git rebase --rebase-merges --root --exec "git commit --amend --no-edit --reset-author"`. Then set the real identity in local config and remove the placeholder. This is safe because the history is unpublished. Verify with `git log --format='%an <%ae> | %cn <%ce>' | sort -u`.
**Why not `.mailmap` only:** GitHub attribution uses the commit metadata itself, so the commits would still show the placeholder.

### ADR-020 — Two agent delivery modes; local Claude Code preferred
**Status:** Accepted (after WP1, 2026-11-25)
**Context:** WP1 ran in a cloud workspace. It could copy files into the owner's folder but could not write `.git`, so it delivered history as a git bundle and the owner ran the import commands.
**Decision:**
- **Mode A** (local Claude Code in the owner's folder; worktree per WP) is preferred. Tests then run on Windows, the target platform, and no import step is needed.
- **Mode B** (cloud) is allowed with a strict protocol: input `main.bundle`, output `<wp>.bundle` containing only `<branch> ^main`, and the report copied next to it.
- Rebuilding history from plain files is forbidden, because unrelated histories can't be merged.

### ADR-021 — WP1 review outcome
**Status:** Accepted
- WP1 is accepted: 246 tests reproduced by the architect, contracts satisfied, 15 clean commits.
- Architect follow-ups on `feat/foundation` (3 commits): `LLMResponse.finish_reason`, `rationale` truncation, `.gitattributes`. These became CONTRACTS v1.1.
- Answers to WP1's questions:
  - (1) `llm/types.py` and `llm/structured.py` are accepted as permanent.
  - (2) All proposals are accepted.
  - (3) Keyless `custom` provider: no. A local model isn't free-tier evidence, so it's out of scope.
  - (4) The 60 s `retry-after` fail-fast stays a constant. The eval runner treats `LLMRateLimitError` as "stop the run, report partial", and never sleeps through quotas.
- Carried to later WPs:
  - The language hint reflects content, not instruction (→ WP4 leading-segment hint).
  - One gateway per event loop (→ WP5: the CLI REPL runs inside one `asyncio.run`).
  - The gateway has no overall deadline (→ WP5 wrapper `wait_for`).
  - Tools are sent even when `supports_tools=False` (→ WP2 JSON fallback).

### ADR-022 — WP2 review outcome
**Status:** Accepted
- WP2 accepted and merged. The architect reproduced 852 tests after the merge (Linux), ruff is clean, and the `eval`/`exec`/`sympify` grep is empty.
- Spot checks: exact `0.1+0.2 = 3/10`; `9**9**9`, `__import__`, `().__class__` rejected in < 0.1 ms; Persian «۲۵ درصد از ۸۴۰» → `۲۱۰` with 0 LLM calls.
- **Windows run:** done 2026-11-26 on the owner's computer: 852 passed, ruff check and format clean.
- Answers to WP2's questions:
  1. **Yes.** WP4's fast path reuses `skillagent.skills.calculator.normalize.strip_cues` + `looks_like_expression`, so there is one definition of "pure expression" instead of two diverging regexes. The WP4 prompt is updated.
  2. The `<task>` + `<request>`/`<previous_result>` message shape is accepted.
  3. The Persian `٬` thousands separator is accepted. The owner may veto it during the Persian review.
  4. **Yes:** CONTRACTS v1.3 §13 records the calculator meta keys.
- Its edit outside ownership (`tests/unit/skills_base/test_skills_scaffold.py`, excluding the calculator from the stub-output check) is accepted. WP3 must make the same one-line change for its three skills; the WP3 prompt is updated.
- Untested so far: live tool-calling quality, which WP0/WP6 will measure.

### ADR-023 — WP6a review outcome
**Status:** Accepted
- WP6a accepted and merged (`399df33`). Reproduced on Windows: 879 tests, ruff clean; 8 commits, placeholder identity, only `eval/**`, `tests/unit/eval/**` and its report touched.
- `test_set.yaml` unchanged since the freeze commit `926a680`. All 15 slots match the WP6a table. Every `calc_values` entry recomputed by hand (test and dev): correct.
- Answers: (1) **T09 gets no `also_ok`.** The user explicitly asks for a translation step and T09 is the only chain in the test set, so a single summarizer writing Persian counts as a miss. (2) Router few-shots are compared against the test set during the WP4 review (ADR-024) instead of a permanent cross-package test.
- Owner's native review: `test_fa_qanat.md` / T02 OK; the other Persian test prompts are pending. Any fix is one recorded change before the first scored run.

### ADR-024 — WP4 review outcome
**Status:** Accepted; merge after WP3 (its card tests render the final SPEC texts)
- Reproduced in `.worktrees/wp4`: 958 tests, ruff clean; 9 commits, placeholder identity, only router files touched. Public interface matches CONTRACTS §11; `build_messages` is an accepted additive public method.
- Spot checks: lead hint «این متن رو summarize کن: <EN>» → `fa`; quoted spans ignored; fast path catches `2+2`, `(3+4)*2^3/7`, `۲۵ درصد از ۸۴۰` and rejects "what is 2+2 in Persian?" and "2 apples and 3 oranges".
- Few-shot vs test set (normalized similarity): no copied prompt. The closest is the generic chain example "Summarize this article and translate the summary into Persian" vs T09 (ratio 0.66): the canonical chain phrasing required by the WP4 prompt, written without opening the test set. Disclosed here; not changed.
- Answers: (1) `ROUTER_VIEW_TOKENS` stays a module constant (no need shown). (2) **Yes**, V8 should reset model-written `dropped_intents`; small architect follow-up in WP1-owned `core/types.py`, tracked for the WP5 window. (3) **Yes**, the architect runs the WP4 live smoke (≤ 20 calls) after WP0 finishes, and records `usage.prompt_tokens` so the scalability table uses provider-measured numbers.
- Known risk: router system prompt ≈ 2.7k estimated tokens for 4 skills; on Groq (8K TPM) that limits throughput to a few router calls per minute. Trim examples first if eval hits it.
- **Live smoke (architect, 2026-11-26, Groq `qwen/qwen3.8-27b`, all of WP3+WP4 trial-merged, dev D01–D20):** plan correct 19/20, `response_language` 20/20, 0 fallbacks, 19 LLM calls + 1 fast path. The one miss, D16 ("Summarize this, translate it to German, and compute 3+4"), planned translator in parallel instead of chained to the summary; arguably ambiguous. **Measured router prompt: median 4 732 provider tokens** (the estimator said ~2.7k). With Groq's 8K TPM, every call waited on a 429 `retry-after` of ~35 s, so median router latency was 36.5 s. The router prompt must shrink before eval (ADR-026).

### ADR-025 — WP3 review outcome
**Status:** Accepted; merge before WP4
- Reproduced in `.worktrees/wp3`: 997 tests, ruff clean; 9 commits, placeholder identity. Files outside WP3 ownership: `skills/_text.py` (new, now **assigned to WP3**), `tests/unit/skills_base/test_skills_scaffold.py` (allowed), `tests/live/run_text_samples.py` (requested), its handoff files.
- Trial merge of WP3 + WP4 + WP0 on top of `main` in a scratch worktree: 1 130 tests pass, ruff clean, no conflicts.
- Live samples ran on Google Gemma during its outage: 3/13 returned (general chat only), so **translator and summarizer live quality is still unmeasured**. The architect reruns the 13 samples on the chosen provider after ADR-026.
- Answers: (1) **Yes**, the WP5 skill wrapper does not truncate input for `requires_payload` skills; they own their budgets (translator rejects, summarizer truncates with a note). ARCHITECTURE §4.5 is amended when WP5 is written. (2) ` + ` is accepted as the parallel plan notation; CONTRACTS v1.4 records it. (3) `_text.py` → WP3. (4) **Yes**, `meta["postprocess"]` flags become CONTRACTS §14 in v1.4, so WP6b can count leakage.
- Gemma's `<thought>…</thought>` / `<message>` wrapping is fixed once, in the gateway's `strip_think` (WP1-owned, architect follow-up), not per skill.

### ADR-026 — WP0 outcome: provider choice
**Status:** Accepted (owner approved Groq Qwen, 2026-11-26). Supersedes ADR-006's leading candidate.
- Owner's Persian scores for Qwen (9 WP0 items, `docs/handoffs/WP0_persian_scores.md`): fluency 4.3, accuracy 3.8, naturalness 3.4. Strong on entities, formal translation and summaries; weak on colloquial idioms, register matching, technical terms and jokes. These become translator/general-chat v2 targets.
- Implemented on `chore/groq-default`: default provider `groq`, `extra_body={"reasoning_effort": "none"}`, `strip_think` handles Gemma's `<thought>` and lone `<message>` wrapper, V8 owns `dropped_intents` (CONTRACTS v1.4).
- Measured 2026-11-26: Groq `qwen/qwen3.8-27b` (27B dense) passed every capability probe, routing 20/20 with the draft prompt, calculator extraction 5/5, clean Persian automated checks, p50 ≈ 0.9 s. Google `gemma-4-31b-it`: 18 of 26 chat calls returned 503 "high demand" in a 35-minute window; successful calls took 8–70 s and leaked `<thought>` reasoning into content, with no working thinking-off switch. Routing/Persian for Gemma were never measured.
- **Recommendation:** amend ADR-006 so Groq / Qwen3.8-27B is primary (`llm_provider` default `groq`, `extra_body={"reasoning_effort": "none"}`, system role, JSON mode and tools supported). Gemma 4 31B on Google stays configured as the documented alternate, with `<thought>` stripping in the gateway.
- Consequences: Groq's free tier limits are 8K tokens/min and 1K output tokens/min, so the router prompt must be trimmed (target ≤ 2.5K provider tokens) and the gateway must honour `retry-after` (it does). Qwen3.8-27B is a Groq **preview** model, so deprecation risk is real and the alternate stays wired.

### ADR-027 — WP4b review outcome (compact router prompt)
**Status:** Accepted
- Reproduced in `.worktrees/wp4b`: 1 143 tests, ruff clean; 9 commits; only router files, its live script and its handoff files.
- Measured by WP4b on Groq: router system prompt **4 732 → ~2 293 provider tokens**; dev D01–D20 plan 20/20 (v1 baseline 19/20), language 20/20; D01–D40 plan 40/40; p50 router latency 36.5 s → 0.92 s with no 429. 41 live calls.
- Compact v1 **replaces v1 in place**: no scored eval had used the old v1, so the compact prompt is the eval baseline (template sha `535b63458c5a`).
- **G2 exception accepted:** an explicit "answer/reply in X" keeps the model's reply language. Recorded here; guards are internal to the router, not a contract.
- Answers: (1) cue order now matters (first 3 Use + 2 Don't-use cues render); SPEC owners reorder cues in WP7 when eval points at a card. (2) This ADR records G2.
- Caveat: dev accuracy was measured once (temperature 0), on the set the prompt was tuned against; only the test set run in WP7 is reportable.

### ADR-028 — WP5 review outcome (graph, API, CLI) and architect follow-ups
**Status:** Accepted
- Reproduced in `.worktrees/wp5`: 1 188 tests, ruff clean; 11 commits; owned files plus `pyproject.toml` `[project.scripts]` (allowed) and `tests/unit/graph/` (new, assigned to WP5).
- Trial merge of WP4b + WP5 + `fix/review-followups` on `main`: **1 206 tests** pass, ruff clean, no conflicts.
- Accepted deviations: run-scoped values (`RunContext`: prompt, start, deadline) travel in `config["configurable"]`, keeping `AgentState` exactly as CONTRACTS §10; node names `skill_<name>` (LangGraph reserves `:`), trace keeps `skill:<name>`; `SkillInput` resolved in `dispatch`; `clarify → END`.
- **Architect live check (Groq, merged code, ~14 calls):** chain (summarize → Persian), clarify ("Summarize this") and Persian small talk were correct. **Bug found:** a Persian parallel request «این جمله را به آلمانی ترجمه کن «صبح بخیر دوستان» و ۱۵ درصد از ۳۶۰ را هم حساب کن» translated the whole prompt, because the rest of the message exceeded the payload instruction-word cap and the router didn't quote the span. Fixed on `fix/review-followups` (payload: router-quoted span anchor + "quoted span whose own clause is the request"; tests include a quotation inside a long text to summarize). Re-checked live: «Guten Morgen, Freunde».
- Also on `fix/review-followups`: calculator direct path drops a sentence-final period (`(15/100)*240. = 36` → `(15/100)*240 = 36`), as WP5 reported.
- Answers: (1) Retry warnings: the CLI will keep `skillagent.llm` at ERROR unless `--trace` (small architect follow-up after merge). (2) Yes, the README embeds the Mermaid output. (3) Fixed (above).
- WP5's scalability token table used the old v1 router prompt; WP7 regenerates it after WP4b is merged.
### ADR-029 — WP6b review outcome (eval runner) and the Groq daily quota
**Status:** Accepted
- Reproduced in `.worktrees/wp6b`: 1 289 tests, ruff clean; 16 commits, only `eval/**`, `tests/unit/eval/**` and its handoff. The test-set guard refuses `--set test` without `--i-know-this-is-the-test-set`; `--dry-run` makes 0 calls. No real Groq account id is in any commit (`git log -S`).
- Dev v1 baseline is **partial: D01–D10, 10/10 routing-correct**. Not a baseline number; D11–D40 hold every hard category.
- **Groq free tier also limits tokens per day: 200 000 (TPD)**, measured from the 429 body. One eval case costs ~3 000 tokens (router ~2 300), so a day covers ~65 cases, shared with every other Groq session on the account. Consequences: live work is budgeted **per day**; the final test-set run (15 × 3 ≈ 135K tokens) gets a day to itself; dev iteration uses `--resume` and fewer runs.
- Answers: (1) Amendment accepted (this ADR). (2) **Yes**, the gateway will redact `org_…` itself (architect follow-up); the eval redaction stays as a second line. (3) Replace the partial report with the merged one when D11–D40 run; git keeps the history.
- Proposals carried to WP7: after a router `LLMRateLimitError`, skip the fallback skill call; degraded fallback wording should suggest retrying later.
### ADR-030 — Deadline-day plan (2026-11-27)
**Status:** Accepted (owner: "today is the deadline")
- Groq's 200K tokens/day is the binding constraint. Priorities follow the mandatory requirements: test-set accuracy (R16), one measured prompt-improvement example (R15), README (R13–R20), GitHub repo (R21).
- **Test set:** one insurance run at the current prompts (v1) now; after the owner's blind A/B review of WP7a's v2, the remaining runs at the final versions. The README reports each prompt version's runs separately, never pooled.
- **Dev baseline D11–D40 is dropped** for quota; the README labels the partial dev numbers as such.
- WP7a (targeted v2 text-skill prompts, ≤ 40 calls) and WP7b (README, Dockerfile, release checks; 0 calls) run in parallel. **README.md is delegated to WP7b** for this WP; the architect fills the measured placeholders.