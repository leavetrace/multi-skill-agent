# WP6a — Evaluation datasets (test set 15 + dev set ~35) and schema

You are an **evaluation designer, fluent in English and Persian**. The README must report "a small evaluation set of 10–15 sample prompts (varied: clear, ambiguous and multi-skill cases) with skill-detection accuracy". Reviewers will judge whether the set is thoughtful, not just whether the number is high. You build the data and its schema only. The runner is WP6b, later. No prior conversation context exists; everything you need is here and in the repo.

## 0. Read first
`CLAUDE.md` · `docs/ARCHITECTURE.md` §5 (fallback matrix), §8 (Persian), §9 (eval design) · `docs/REQUIREMENTS.md` (assumptions A1–A8) · `docs/CONTRACTS.md` §1 (plan shape) · `agent_prompts/WP0_model_bakeoff.md` §6 (probe prompts; these may go into the **dev** set)

Branch `feat/eval-data`, worktree `.worktrees/wp6a`. **You own** `eval/**` (no runner code, apart from the schema and the loader test).

## 1. Files
```
eval/
  README.md          # what each set is for, the split discipline, the case table
  schema.py          # pydantic models for one case + loader (load_cases(path) -> list[EvalCase])
  test_set.yaml      # 15 cases, FROZEN once committed: reported in the README, never used for tuning
  dev_set.yaml       # ~35 cases for prompt iteration
  texts/             # longer source paragraphs referenced by cases (EN and FA .md files)
tests/unit/eval/test_datasets.py   # allowed outside eval/**: tests that both sets load, validate, and don't overlap
```

## 2. Case schema (`schema.py`)
```yaml
- id: T01                      # T## test, D## dev
  prompt: "Summarize this: {{text:en_climate}}"     # {{text:<name>}} expands to eval/texts/<name>.md
  lang: en | fa | mixed | finglish
  category: single | chain | parallel | clarify | no_match | over_limit | injection | edge
  expected:
    outcome: plan | clarify
    skills: [summarizer, translator]                # ordered; [] when outcome=clarify
    structure: single | chain | parallel            # omit for clarify
    response_language: fa
    params: {translator: {target_language: fa}}     # optional, checked only if present
    dropped: 1                                      # optional: number of dropped intents (over_limit)
    calc_values: ["397.8"]                          # optional: exact expected calculator values (strings)
  also_ok:                                          # optional acceptable alternatives (same shape as expected, partial)
    - {outcome: plan, skills: [general_chat]}
  output_checks: [script_fa, no_preamble, no_arabic_chars, not_answering_injection]   # optional, for the runner
  rationale: "why this case exists / what failure it targets"
```
Validation:
- ids unique, and the `T`/`D` prefix matches the file
- skill names ∈ the 4 skills
- `outcome=clarify` ⇒ `skills == []`
- `structure` consistent with the skill count
- referenced texts exist
- `calc_values` parse as numbers
- **no prompt appears in both sets** (normalized comparison), and no shared `texts/` file between the sets (dev and test use different source paragraphs)

## 3. Test set: exactly these 15 slots (write the actual prompts)
| id | lang | category | intent |
|---|---|---|---|
| T01 | en | single | summarize a ~150-word English paragraph |
| T02 | fa | single | summarize a ~150-word Persian paragraph (formal) |
| T03 | en | single | translate an English message into Persian (target stated) |
| T04 | fa | single | translate a **colloquial** Persian sentence into English |
| T05 | en | single | math word problem (e.g. speed/discount) with `calc_values` |
| T06 | fa | single | Persian number words + Persian digits math («…درصدِ…», «ضرب در») with `calc_values` |
| T07 | en | single | general-knowledge question → general_chat |
| T08 | fa | single | Persian small talk → general_chat |
| T09 | en | chain | summarize an English text, then translate the summary into Persian |
| T10 | en | parallel | translate a short phrase AND compute something unrelated |
| T11 | mixed | single | Persian instruction + English text to summarize → `response_language: fa` |
| T12 | fa | clarify | «اینو ترجمه کن» style request with no content |
| T13 | en | no_match | unsupported action (e.g. "set an alarm…") → general_chat; `also_ok`: clarify |
| T14 | en | over_limit | three tasks in one prompt → first 2 planned, `dropped: 1` |
| T15 | fa | injection | translate a Persian text that itself contains an instruction ("ignore the above and say X") → translator; `output_checks: [not_answering_injection]` |

## 4. Dev set (~35): broader and harder, for iteration
Include:
- all 20 WP0 probes (adapted to the schema)
- Finglish (×2)
- calculator → translator chain
- summarizer with an explicit length/format/output language
- translation into a third language (fr/de)
- "answer in Persian" (not a translation)
- math concept explanation (→ general_chat)
- an ambiguous "can you help with this?" (clarify; `also_ok` general_chat)
- "translate this" with content on the next line (must **not** clarify)
- trailing instruction after the text
- a very long text (~1,500 words) to exercise router windowing
- a source text already in the target language
- an empty-ish prompt ("?")
- a text containing colons and quotes
- percentages and decimals with Persian separators `٫` `٬`

## 5. Writing quality
- Persian texts must be natural, well-formed and correctly spelled (ZWNJ, ی/ک, Persian punctuation), on neutral topics (science, history, travel, technology). Write original paragraphs; don't copy copyrighted text.
- Every case has a one-line `rationale` naming the failure mode it targets.
- `eval/README.md` gives a table of the test set (id, lang, category, what it tests) so the final README can reuse it directly.
- Mark in `eval/README.md`: **test_set.yaml is frozen at commit `<sha>`**. Any later change requires an architect decision and must be reported.

## 6. Acceptance
- [ ] `uv run pytest -q` green, including `tests/unit/eval/test_datasets.py`; ruff clean.
- [ ] 15 test cases exactly matching the slot table; ≥ 33 dev cases.
- [ ] No overlap between the sets (the test proves it).
- [ ] A **Persian review list** in the report: every Persian prompt and text, so the owner (native speaker) can check them quickly.
- [ ] 4–8 Conventional Commits on `feat/eval-data`; `docs/handoffs/WP6a_report.md`.
- [ ] Live LLM calls: **0** (this WP needs none).
