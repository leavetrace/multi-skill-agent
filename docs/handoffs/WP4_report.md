# WP4 Handoff Report — Router

- **Agent session date:** 2026-11-26
- **Branch / worktree:** `feat/router` / `.worktrees/wp4` (Mode A, local, owner's Windows PC)
- **Final commit:** see §11 (this report is the last commit)
- **Status:** complete, except the live smoke (§7 of the task), which was **not run** because there is no `.env` at the repo root

## 1. Summary
The `skillagent.router` package implements CONTRACTS §11. It covers deterministic preprocessing, a leading-segment language hint, skill cards and examples rendered from the registry, the bilingual prompt `prompts/router/v1.md`, a fast path that reuses WP2's expression detector, `AllSkills`/`BM25TopK` candidate selection, guards G1/G2, and the `Router.route` flow with trace events and a fallback that never raises. Long prompts are cut to a head+tail window before the router sees them. 106 new offline tests; the whole repo passes (958 tests) on Windows and ruff is clean. Measured BM25 recall@6 on 20 synthetic bilingual skills / 40 queries is 0.975.

## 2. Deliverables
| Path | Purpose |
|---|---|
| `skillagent/router/__init__.py` | re-exports `Router`, `RouteResult`, `build_user_request`, `leading_segment_hint` |
| `skillagent/router/preprocess.py` | `build_user_request`, `leading_segment_hint`, plus helpers `instruction_segment`, `is_unambiguous_english`, `strip_quoted`, `word_count` |
| `skillagent/router/cards.py` | `render_cards`, `render_params` (from `params_model`), `render_examples` |
| `skillagent/router/examples.py` | 12 router-level JSON examples (`PlanExample`), filtered by the available skills |
| `skillagent/router/candidates.py` | `CandidateSelector`, `AllSkills`, `BM25TopK` (pure Python), `tokenize` |
| `skillagent/router/fast_path.py` | empty input → clarification (en); pure expression → calculator (`route_source="rule"`) |
| `skillagent/router/guards.py` | G1 missing payload, G2 language sanity |
| `skillagent/router/router.py` | `Router`, `RouteResult`, `router_view` (long-prompt window), fallback |
| `skillagent/prompts/router/v1.md` | router prompt template (sha `19ad6d4e53e8`) |
| `tests/unit/router/*` | 106 tests |

## 3. How to verify (commands actually run, Windows 11, uv 0.13.10)
```
uv run pytest -q
958 passed in 17.66s
uv run ruff check .
All checks passed!
uv run ruff format --check .      (after `ruff format`)
65 files already formatted
uv run pytest -q -s tests/unit/router     # prints the measured tables of §6
```

## 4. Contract deviations / proposals
- **None to the public interface.** `Router.__init__`, `route`, `RouteResult`, `build_user_request`, `leading_segment_hint`, `CandidateSelector`, `AllSkills` and `BM25TopK(k)` match §11.
- `Router.build_messages(request, candidates)` is an extra public method. It renders the prompt without calling the LLM, so tests and WP5's scalability section can measure prompt size.
- `ROUTER_VIEW_TOKENS` (700/500/150) is a module constant in `router/router.py`, not a `Settings` field, because `config.py` belongs to WP1. **Proposal:** add `SKILLAGENT_ROUTER_VIEW_TOKENS` if anyone needs to tune it.
- **Proposal (CONTRACTS §1.1):** V8 *extends* `dropped_intents`. If a model writes its own `dropped_intents` (the prompt never asks it to), that text survives. A one-line change in the validator could reset the field before applying V8. I didn't change it because it's WP1-owned and hasn't been seen in practice.

## 5. Decisions made within my scope
- **Skill-specific wording lives only in SPECs and filtered examples.** The cards, the skill list, and the params (field names and allowed values, from the `params_model` type) are all generated. The prompt names exactly one skill, through `${fallback_skill}` = `general_chat`, which the contract requires as the safety net. The calculator-vs-chat and "answer in Persian ≠ translation" rules are phrased generically ("read each card's Use/Don't use lines"; "asking for the answer in a language is not translation"). The specifics come from the SPEC cards. The 12 router-level examples name product skills, so `render_examples` drops any example that uses a skill outside the candidate set. A test proves a synthetic 5th skill shows up in the skill list and the cards with no code change.
- **Prompt sha only covers the template.** The examples live in Python, so the trace records both `sha` (template) and `rendered_sha` (the full rendered system prompt). Eval should use `rendered_sha` to tell prompt variants apart.
- **SPEC examples use compact notation** (`skill(input_from, params) -> …`) under a one-line legend, not JSON. Converting another WP's free-form notation to JSON would be fragile, and WP2/WP3 are still editing their SPECs.
- **Leading-segment hint:**
  - Quoted spans are removed first (`Translate «سلام» to English` → `en`).
  - A script-mixed segment is decided by word majority. With letter ratios, «این متن رو summarize کن» is `mixed`; with word majority it is `fa`.
  - If the prefix before `:` is longer than 15 words, a short last line (≤ 15 words) is used as the instruction.
- **G2's fa → en override only fires when the instruction is clearly English:** at least 2 English marker words making up ≥ 30% of the words. The marker list leaves out Finglish homographs (`in`, `to`, `man`, `be`), so "salam chetori" and "in matno kholase kon" stay `fa`. G2 also skips clarification decisions, because their question text is already written in the model's language and we can't translate it deterministically.
- **G1 cue (skill-agnostic):** ≤ 4 words, and one of these:
  - a deictic word outside quotes (this/it/that…, «این/اینو/متن/زیر…»)
  - a single word ("Summarize")
  - a bare Persian noun + light verb («ترجمه کن»)
  - a trailing colon

  The skill side comes from `SkillSpec.requires_payload` on a `"user"` step. "Translate hello to French" doesn't fire.
- **Guard order:** G2 runs before G1, so G1's clarification uses the corrected language.
- **Fast-path language:** `fa` if the input contains any Arabic-block character (letters or Persian digits), otherwise `en`.
- **Fallback catches** `StructuredOutputError`, every `LLMError`, and the builtin `TimeoutError`, which covers a caller's `asyncio.wait_for`. Anything else is a programming error and propagates, as §11 says.
- **`llm_calls` on fallback:**
  - `StructuredOutputError` → 2 (the first call plus the repair).
  - `LLMError` → 1, a lower bound: if the error happened during the repair call, the true count is 2. `complete_structured` doesn't report how many calls it made before raising.

## 6. Measured results
**Router system-prompt size** (`estimate_tokens`, the conservative language-aware estimator; real tokenizer counts will be lower), all cards shown (`AllSkills` forced):

| Skills | synthetic only | 4 real + synthetic padding |
|---|---|---|
| 4 | 1 374 | 2 708 |
| 10 | 1 923 | 3 286 |
| 20 | 2 842 | 4 218 |

- Growth per card is about 92 tokens for synthetic cards. A test asserts the 4→10 and 10→20 slopes differ by less than 25%.
- With 20 skills and the default selector (20 > 12, so `BM25TopK(6)` plus `general_chat`), the router prompt for a summarize request is **2 895** tokens, against 4 218 with all cards.
- The real 4-skill prompt is dominated by the 12 router examples and the bilingual calculator card.
- User message: windowed to ≤ ~650 tokens. Measured on a 3 000-word input: head ≤ 500 and tail ≤ 150 tokens.

**BM25 Top-K recall** (20 synthetic bilingual skills + `general_chat`; 40 queries, 20 EN + 20 FA, worded differently from the cues):

| k | recall@k |
|---|---|
| 3 | 0.975 |
| 6 | 0.975 (EN 1.00, FA 0.95) |
| 10 | 0.975 |

The one miss at every k is «برای ویزای آلمان چه مدارکی لازم است؟». The query has «ویزای» (ezafe form) while the card has «ویزا»; without stemming BM25 can't match them. I didn't tune the query to hide this. A light Persian suffix-stripper (ی/های/ها) in `tokenize` would fix it if Top-K ever matters.

**Live smoke:** **not run.** No `.env` exists at the repo root (checked 2026-11-26), so there is no accuracy table or latency figure. The WP0 probes are ready to run once keys exist; this is ≤ 20 router calls.

## 7. Known issues, limitations, risks
- **The router prompt is about 2.7k estimated tokens for 4 skills.** That's fine for Gemma 4 31B context, but every request pays for it. If eval shows TPM pressure (Groq 8K TPM), trim the router examples first (`examples.py`) and check accuracy in WP6.
- **G2 overrides the user in one case.** A Persian instruction that explicitly asks for an English answer («به انگلیسی جواب بده: what is AI?») is forced to `fa`. This follows the spec ("lead_hint fa and model en → fa"). If eval shows the case matters, check for an explicit "answer in X" phrase before overriding.
- **G1 only handles ≤ 4-word prompts.** «متن زیر رو خلاصه کن» (5 words) relies on the LLM to clarify, by design.
- **`leading_segment_hint` is a heuristic.** A 50/50 word split returns `mixed`, which never triggers G2.
- Every prompt-quality claim is untested against a real model until the live smoke or WP6 eval runs.

## 8. Questions for the architect
1. Should `ROUTER_VIEW_TOKENS` become a setting? (See §4.)
2. Do you want the V8 `dropped_intents` reset? (See §4.)
3. Should the router prompt be measured with the provider tokenizer (e.g. `usage.prompt_tokens` from a live call) before WP5 publishes the scalability table? The current numbers are conservative estimates.

## 9. Files touched outside my ownership
None.

## 10. Dependencies added
None.

## 11. Commits
```
8c4b78c test(router): cover windowing, fast path, guards, repair, fallback and V8
50f1c1a test(router): cover preprocessing, prompt rendering/scaling and BM25 recall
a7fd311 feat(router): add Router.route with windowed view, trace events and fallback
8f1fff8 feat(router): add fast-path rules and deterministic guards G1/G2
a3c024e feat(router): add bilingual router prompt v1
ca6674e feat(router): render skill cards and few-shot examples from the registry
5e10c13 feat(router): add candidate selectors (AllSkills, pure-Python BM25 Top-K)
8c8b913 feat(router): add request preprocessing and instruction-segment language hint
(+ docs(handoff): add WP4 report)
```

## 12. Live LLM calls made
0 (no `.env` / API keys on this machine).
