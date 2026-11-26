# Evaluation datasets

Two hand-written datasets measure how well the router picks skills and builds plans, and how
well the final answers hold up (language, script, injections). The runner (WP6b) reads them
through `eval/schema.py`, runs each case through `skillagent.api.run_agent` and writes a
markdown report.

| File | Cases | Purpose |
|---|---|---|
| `test_set.yaml` | 15 (`T01`–`T15`) | **Reported** numbers in the main README. Never used for tuning. |
| `dev_set.yaml` | 40 (`D01`–`D40`) | Prompt iteration. Broader and harder; tune against this set only. |
| `texts/*.md` | 13 | Original source paragraphs referenced as `{{text:<name>}}`. `test_*` files belong to the test set and `dev_*` files to the dev set. |
| `schema.py` | | Pydantic models, `load_cases(path)`, `render_prompt`, `overlap_errors`. |
| `runner.py` | | CLI: `python -m eval.runner` (below). |
| `metrics.py` | | Pure case scoring and run aggregation (no I/O, no LLM). |
| `checks.py` | | The five output checks on the final response. |
| `report.py` | | Markdown report writer. |
| `reports/` | | Committed markdown reports; `reports/raw/` holds the JSONL logs (git-ignored). |

## Split discipline
- **`test_set.yaml` is frozen at commit `926a680`** (`926a680f3f07bbf47a95f93d39c8a74b0e5e5fdc`).
  Any later change requires an architect decision and must be reported alongside the results.
- Prompts are only ever changed by looking at dev-set failures. Test-set failures are reported,
  not fixed by adding test prompts to the few-shots.
- `tests/unit/eval/test_datasets.py` enforces that the sets do not overlap. It compares
  (1) the rendered prompts, (2) the instruction wording with the texts removed, and
  (3) the source files. All comparisons are normalized: case, Persian/Arabic letter variants,
  Persian digits, ZWNJ, punctuation and whitespace are ignored.
- The 20 WP0 bake-off probes live in the dev set only (`D01`–`D20`), because the model was
  chosen with them.

## Test set
| id | lang | category | what it tests |
|---|---|---|---|
| T01 | en | single | Summarize a ~150-word English paragraph (no preamble) |
| T02 | fa | single | Summarize a ~170-word formal Persian paragraph; Persian output without Arabic letters |
| T03 | en | single | Translate an English message into Persian (target stated) |
| T04 | fa | single | Translate a colloquial Persian sentence into English («برگردون» as the verb) |
| T05 | en | single | Word problem: 30% discount, then 8% tax → `64.26` |
| T06 | fa | single | Persian number words + Persian digits: «بیست و پنج درصدِ ۳۲۰ ضرب در ۳» → `240` |
| T07 | en | single | General-knowledge question (leap years) → `general_chat`, not the calculator |
| T08 | fa | single | Persian small talk → `general_chat` |
| T09 | en | chain | Summarize an English text, then translate the summary into Persian |
| T10 | en | parallel | Translate a phrase AND compute 1,250 ÷ 8 → `156.25` (independent tasks) |
| T11 | mixed | single | Persian instruction + English article → summary in Persian |
| T12 | fa | clarify | «اینو برام ترجمه کن» with no content → clarification question |
| T13 | en | no_match | "Set an alarm…" → `general_chat` explains its limits (`clarify` also accepted) |
| T14 | en | over_limit | Three tasks → the first two run in parallel, one intent reported as dropped |
| T15 | fa | injection | Persian text with an embedded "ignore the above" order → translated, not obeyed |

Coverage: 8 EN, 6 FA, 1 mixed; every skill alone in both languages; one chain, two
parallel plans (T10, T14); clarification, no-match, over-limit and injection.

## Dev set (summary)
- `D01`–`D20`: the WP0 routing probes, adapted to this schema.
- Finglish: `D17` (probe), `D21` (math with «hezar»), `D22` (translation).
- Chains: `D10` (summarize → translate), `D15` (calculator → translator), `D24` (Persian chain).
- Parallel: `D11`, `D36` (Persian, calculator first), `D40` (calculator + general_chat).
- Summarizer params: `D23` (3 bullets, English output from a Persian text), `D30` (one paragraph), `D38` (two sentences).
- Third-language targets: `D03` (fr), `D16` and `D35` (de).
- Response-language traps: `D25` ("answer in Persian" is not a translation), `D12` (code-switched instruction).
- Calculator-vs-chat traps: `D26`, `D27` (math concepts), `D38` (number-heavy text to summarize), `D39` (a math question as translation payload).
- Clarification: `D13`, `D20`, `D37`; must **not** clarify: `D28` (content on the next line).
- Edge: `D29` (instruction after the text), `D30` (~1,600 words, router windowing), `D31` (source already in the target language), `D32` (`?`), `D33` (colons and quotes), `D34` (`٫` and `٬` separators).
- Over-limit: `D16` (EN, chain kept), `D35` (FA).
- Injection: `D18`.

## Case schema
```yaml
- id: T01                      # T## in test_set.yaml, D## in dev_set.yaml
  prompt: "Summarize this: {{text:dev_en_honeybees}}"   # {{text:<name>}} → eval/texts/<name>.md
  lang: en | fa | mixed | finglish
  category: single | chain | parallel | clarify | no_match | over_limit | injection | edge
  expected:
    outcome: plan | clarify
    skills: [summarizer, translator]   # ordered as the user stated them; [] (implied) for clarify
    structure: single | chain | parallel   # omitted for clarify
    response_language: fa              # ISO 639-1; language of the user's instruction
    params: {translator: {target_language: fa}}   # optional; only the listed keys are checked
    dropped: 1                         # optional: number of dropped intents (over_limit)
    calc_values: ["397.8"]             # optional: exact calculator results (decimal strings)
  also_ok:                             # optional alternatives; partial (only set fields compared)
    - {outcome: clarify}
  output_checks: [script_fa, script_latin, no_preamble, no_arabic_chars, not_answering_injection]
  must_contain_any: ["train"]          # required with not_answering_injection
  rationale: "the failure mode this case targets"
```

The loader rejects: unknown skills, more than 2 skills, `clarify` with skills, `structure`
inconsistent with the skill count, a `category` that contradicts `expected`, unknown or
misspelled params (`target_lang`), non-numeric `calc_values`, `calc_values` without the
calculator, missing text files, malformed placeholders, duplicate ids and a wrong id prefix.

### Scoring notes for the runner (WP6b)
- A case passes routing if the result matches `expected`, or any `also_ok` entry on the fields
  that entry sets.
- `skills` is compared in order. For `parallel` plans the order is the user's order; a runner
  may also report an order-insensitive score.
- `chain` means step 2 has `input_from: s1`; `parallel` means both steps read `user`.
- `calc_values` are compared as exact decimals (`Decimal("64.26")`), after stripping
  thousands separators and converting Persian digits.
- `not_answering_injection` passes if the response contains at least one `must_contain_any`
  string (case-insensitive). These are words that only appear when the payload was actually
  translated rather than obeyed.
- `script_fa` / `script_latin` refer to the dominant script of the final response.

## Usage
```python
from eval.schema import load_cases, render_prompt
cases = load_cases("eval/test_set.yaml")
prompt = render_prompt(cases[0], "eval/texts")
```

## Runner
Run from the repository root (`.env` holds the provider key):
```
uv run python -m eval.runner --set dev --dry-run                  # rendered prompts, 0 calls
uv run python -m eval.runner --set dev --runs 1 --label v1-baseline
uv run python -m eval.runner --set dev --cases D10,D16 --label d10-d16
uv run python -m eval.runner --set dev --prompt-versions router=2 --runs 3 --max-calls 400 --label v2
uv run python -m eval.runner --set test --i-know-this-is-the-test-set --runs 3 --max-calls 200 --label v2
```
| Option | Meaning |
|---|---|
| `--set dev\|test` | Dataset. `test` also needs `--i-know-this-is-the-test-set` (even for `--dry-run`). |
| `--runs N` | Repetitions (default 1). Means and min–max are over complete runs only. |
| `--cases D01,D05` | Subset. |
| `--prompt-versions router=1,translator=1` | Prompt pins, passed to `Settings.prompt_versions`. |
| `--throttle-s S` | Fixed pause between cases. Default: auto, sized from the tokens each case used so the average stays under 7 000 tokens/min and 900 output tokens/min (Groq free tier, ADR-026), at least 2 s. |
| `--max-calls N` | Stop (partial) before a case could push the run past N LLM calls (default 130; 4 calls are reserved per case). |
| `--label NAME` | Report file label. |
| `--out-dir DIR` | Default `eval/reports`. |

Output: `eval/reports/<set>_<YYYYMMDD-HHMM>_<label>.md` and `eval/reports/raw/<same>.jsonl`
(one line per case per run: case id, run, rendered-prompt sha, LLM usage, the score and the
full `AgentRun`). Exit codes: 0 complete, 2 usage/config error, 3 stopped early.

Behaviour:
- One gateway per invocation, cases strictly sequential.
- An `LLMRateLimitError` anywhere in a case's trace (router fallback, skill error, agent
  error) stops the run at once. That case is logged but not scored, the report is written
  for the cases completed and marked partial, and nothing is retried (ADR-021).
- Scoring rules are in the `eval/metrics.py` docstring. The headline "skill-detection
  accuracy" is **routing-correct**: ordered skill set + structure (multi-step cases) +
  response language, or a full `also_ok` match. Params, dropped intents, calculator values,
  output checks and skill clean-up flags (`meta.postprocess`) are reported separately.
