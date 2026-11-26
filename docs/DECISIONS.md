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
**Status:** Accepted (direction) — model id final after WP0 measurements + owner's Persian review
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
