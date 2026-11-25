# REQUIREMENTS — Traceability Matrix

Source: `AIEngineerTask.pdf` (I4Twins, Sept 2026). [M] = mandatory, [B] = bonus, [X] = explicitly out of scope, [O] = our objective.
Every [M] row must be ✅ with evidence before release (WP7 checklist).

| ID | Requirement | Class | Design element | Verification | README section |
|---|---|---|---|---|---|
| R1 | Exactly 4 skills: Summarizer, Translator, Calculator, General Chat | M | registry with 4 specs | unit + eval | Skills |
| R2 | Calculator uses a real computational tool, not LLM guessing | M | tool call → safe AST evaluator | unit (≥50 cases incl. security) + eval numeric check | Calculator |
| R3 | Flow: raw prompt → routing node → skill node(s) w/ original prompt → final response | M | preprocess → router → scheduler/skills → composer | integration test | Graph architecture |
| R4 | Routing output structured & validated (Pydantic) | M | `RoutingDecision` + validators | unit | Graph architecture |
| R5 | Detect & apply up to 2 skills in one prompt | M | plan DAG ≤2 steps | eval multi-skill cases | Multi-skill |
| R6 | Explain combination strategy (parallel/sequential) in README | M | ADR-001 | doc review | Multi-skill |
| R7 | Clearly defined fallback for no-match/ambiguous; explained | M | ADR-007 policy | eval ambiguous/no-match cases | Fallback |
| R8 | Persian: understand, route, correct Persian output | M | §8 Persian handling | eval FA/mixed cases + native review | Persian |
| R9 | Free-tier provider | M | ADR-006 | README statement + evidence link | Model/provider |
| R10 | Model ≤35B params; state model & param count | M | dense model | README | Model/provider |
| R11 | LangGraph (≥ routing node + skill nodes) | M | graph builder | integration test, mermaid export | Graph architecture |
| R12 | CLI interface (no web API) | M | `agent/cli.py` | manual + smoke test | How to run |
| R13 | README: how to run (prereqs, install, env vars, commands) | M | WP7 | fresh-clone test | How to run |
| R14 | README: graph architecture + reasoning per decision | M | ARCHITECTURE/DECISIONS | doc review | Architecture |
| R15 | README: prompt engineering per skill + ≥1 before/after improvement example with why | M | versioned prompts + eval history | measured v1 vs v2 | Prompt engineering |
| R16 | README: eval set 10–15 prompts (clear/ambiguous/multi) + skill-detection accuracy | M | `eval/test_set.yaml` + runner | measured report | Evaluation |
| R17 | README: Persian handling | M | §8 | — | Persian |
| R18 | README: known limitations + production gaps | M | WP7 | — | Limitations |
| R19 | README: assumptions where brief ambiguous | M | ASSUMPTIONS list | — | Assumptions |
| R20 | AI usage disclosure (spec/prompt files in repo) | M | `agent_prompts/`, `CLAUDE.md`, docs | present in repo | AI usage |
| R21 | Code in GitHub repository | M | WP7 | repo link | — |
| R22 | Git hygiene: feature branches, clear incremental commits | B | branch per WP, conventional commits | git log | Development process |
| R23 | Docker optional | B (plus) | optional minimal Dockerfile | build test | How to run |
| X1 | No auth, DB, persistence, deployment, scalability/load infra | X | — | — | — |
| X2 | No memory/history across requests | X | stateless graph per request | — | Limitations |
| X3 | No >4 skills or >2 simultaneous skills | X | synthetic skills only in tests | — | Scalability |
| X4 | No FastAPI layer | X | — | — | — |
| O1 | Scalability to 10–20+ skills without redesign | O | ARCHITECTURE §7 | `tests/scalability` measurements | Scalability |
| O2 | Execution/context explosion control | O | limits, isolation, budgets | tests | Scalability |
| O3 | Measured, reproducible eval (3 runs, variance) | O | ADR-011 | report | Evaluation |
| O4 | Prompt-injection resistance for payload skills | O | delimiters + rules | eval case | Prompt engineering |

## Evaluation criteria (from brief) → where we earn points
1. Skill-detection accuracy → router prompt quality, bilingual few-shots, dev/test discipline.
2. Prompt quality (esp. Summarizer, Translator) → WP3, native review, documented iterations.
3. Calculator correctness/reliability → WP2 evaluator + tests.
4. Graph design & code readability → ADR-001, contracts, small modules.
5. Documentation quality, architectural thinking, creativity → README + these docs.
6. Persian handling → §8.
7. Edge cases → fallback matrix + eval coverage.
8. Git hygiene (bonus) → branch-per-WP.

## Assumptions log (feeds README "Assumptions")
- A1. Translation target unspecified → Persian input goes to English, anything else goes to Persian.
- A2. "Simultaneously" means "in the same request", not necessarily concurrent execution.
- A3. Summary language = the user's instruction language unless the user specifies otherwise.
- A4. General Chat answers general-knowledge questions from model knowledge (no web access).
- A5. "≤35B parameters" = total parameters; a dense model avoids MoE ambiguity.
- A6. Clarification is a terminal response (no memory), so the user resends the full request.
- A7. >2 intents → the first two in the user's order are executed and the user is notified.
- A8. Google AI Studio / Groq free plans qualify as "free-tier providers" (no payment method required).
