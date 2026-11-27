# WP7a Handoff Report — Text-skill prompts v1 → v2 (targeted, measured)

- **Agent session date:** 2026-11-27
- **Branch / worktree:** `feat/prompts-v2` / `.worktrees/wp7a`
- **Final commit:** see §11 (this report is the last commit)
- **Status:** complete. **The owner's blind A/B scores are still pending, and they decide what merges.**

## 1. Summary
I wrote `v2.md` for `summarizer`, `translator` and `general_chat`. Each one changes only what a measured finding pointed at, and each change in its header names the sample that motivated it. v1 is unchanged; a test pins its hash. I ran a blind A/B of 8 samples (v1 vs v2) for the owner's Persian review and a targeted dev check of 8 cases at v2. Together they used 40 live calls, exactly the budget. My unscored reading:
- **general_chat v2:** a clear register improvement (casual, complete, concrete Persian).
- **translator v2:** small gains (technical terms, «بررسی می‌کنیم»). It did not reach «افزایش ۱۲ درصدی فروش» on t1.
- **summarizer v2:** mixed. It reliably keeps the source's attribution verb («اعلام کرد») and the advice (3/3 runs on s2; v1 failed both in 2/2 runs). But two v2 summaries contain **factual errors**:
  - s4 calls councillor Maria Lopez «شهردار» (mayor).
  - Dev D12 says «خورشید در شب می‌درخشد» ("the sun shines at night"), the opposite of the source.

  The owner should weigh these errors when deciding whether summarizer v2 merges.

## 2. Deliverables
| Path | Purpose |
|---|---|
| `skillagent/prompts/summarizer/v2.md` | v2 summarizer: natural Persian from English sources, explicit roles, attribution verbs, kept advice, EN→FA few-shot; 7 documented changes |
| `skillagent/prompts/translator/v2.md` | v2 translator: Persian collocations, established technical terms, register both ways, colloquial interjections by meaning, exact time expressions; 6 changes |
| `skillagent/prompts/general_chat/v2.md` | v2 general chat: casual Persian register, complete sentences, no clichés, request-specific declines, degraded-mode retry line; 5 changes |
| `tests/unit/skills/test_prompts_v2.py` | 22 offline tests: v1+v2 ship, v2 default, **v1 sha frozen**, v2 uses exactly v1's variables, every change has "→" and a sample id, Persian rules + one marker per change reach the model, degraded note stays last, pinning selects v1/v2 end to end through each skill |
| `tests/live/run_prompt_ab.py` | Live blind A/B runner (resumable, stops on a quota 429, `--rerun-v2`, `--build-only`) |
| `docs/handoffs/WP7a_persian_review.md` | **Blind A/B sheet for the owner** (8 samples, A/B random order, empty F/A/N + preference columns) |
| `docs/handoffs/WP7a_persian_review_key.md` | Key: which letter is v2, prompt shas |
| `docs/handoffs/WP7a_ab_raw.jsonl` | Raw outputs + meta (unblinded; includes 6 superseded draft-v2 outputs) |
| `eval/reports/dev_20261127-1112_v2-targeted.md` | Eval runner report, 8 dev cases at v2 |

## 3. How to verify (commands actually run, with real output excerpts)
```
uv run pytest -q                       → 1314 passed in 14.69s
uv run ruff check .                    → All checks passed!
uv run ruff format --check .           → 1 file would be reformatted: tests/unit/llm/test_gateway.py
                                         (pre-existing on main, WP1-owned, not touched)
uv run python tests/live/run_prompt_ab.py --build-only    → rebuilds the sheet and key, 0 calls
uv run python -m eval.runner --set dev --cases D01,D02,D04,D10,D12,D23,D24,D28 --label v2-targeted \
  --prompt-versions summarizer=2,translator=2,general_chat=2 --max-calls 18
  → 7/7 (stopped before D28 by the call reserve); resumed with --max-calls 4 → routing-correct 8/8
```
Score the A/B: open `docs/handoffs/WP7a_persian_review.md`, fill it in, then open the key.

## 4. Contract deviations / proposals
None. Both v2 prompts use exactly the v1 variables (tested), so no code changes were needed.
- **Proposal (merge mechanics):** `PromptLoader` picks the highest version, so merging this branch makes all three v2 prompts the default. If the owner rejects one skill's v2, delete that `v2.md` and remove the skill's name from `NAMES` in `tests/unit/skills/test_prompts_v2.py`. Its v1-specific tests stay green because §9's edits made them version-agnostic.
- **Proposal (test run):** v2 prompts cost more tokens. Measured provider prompt tokens per dev case (router + skills), v1 baseline → v2: D01 3269 → 3749, D02 3544 → 4024, D04 3112 → 3508, D10 4200 → 5081 (+11 % to +21 %). Plan the test-set quota with this.

## 5. Decisions made within my scope
- **Few-shots and contrast pairs never reuse the A/B or eval text.** The prompt shows «کاهش ۳۰ درصدی قیمت‌ها», not t1's «افزایش ۱۲ درصدی فروش», and a harbour story, not Riverton. Otherwise the A/B on s4/t1/c2 would test memorized answers. Alternative: quote the owner's exact fixes, which would have looked better but meant less. The new samples n1–n3 test generalization outright.
- **Iterated the summarizer twice inside the A/B, openly.** In the first run, v2 added a title (s4, mayor) and changed the weekday (n1, Wednesday for Thursday). I added a guard (change 6) and re-ran all three v2 summarizer samples. The second run turned Tuesday into «دوشنبه», which is copied from the few-shot's "on Monday". I removed the weekday from the example (change 7) and re-ran all three again. The sheet shows only outputs of the final prompt (`601357a578af`). The 6 draft outputs stay in the raw log; the key says so. Only these 6 calls repeat work; no sample was re-run selectively for a better result.
- **Stopped iterating although s4 still says «شهردار».** The remaining budget was needed for the required dev check. The blind sheet shows the error to the owner as it is.
- **Degraded-mode "suggest retrying" is in the prompt, not in code.** The note text belongs to `general_chat.py` (WP3). v2 only says how to behave when the "This request" section is present. A test confirms the note is still rendered last.
- **v1 dev comparison reuses the 2026-11-26 v1 baseline** (D01, D02, D04, D10). There was no budget to re-run v1 for D12, D23, D24 or D28.

## 6. Measured results
Provider Groq, model `qwen/qwen3.8-27b`, 2026-11-27. Each case and sample ran once, so these are single-run results at temperature 0.2–0.7.

### 6.1 Blind A/B (owner scores pending)
8 samples: s4, s2, t1, c2, c5 (WP3) plus three new ones: n1 (an English rail-news paragraph, ~130 words, summarized in Persian), n2 (technical EN→FA: open-source ML library) and n3 (a colloquial Persian chat line after a bad meeting). All 16 final outputs have status `ok`; no `postprocess` flag fired. My notes below are **not scores**; the owner's scores replace them.

| Sample | What v2 changed (my reading, unscored) |
|---|---|
| s4 | v1 this run was not broken (no title for Lopez). v2 restructures and keeps "argued/warned", but calls Lopez «شهردار» (mayor): an **accuracy error** in 2 of 3 v2 runs and in 0 of 2 v1 runs |
| s2 | v2 keeps «اعلام کرد» and the advice to farmers and drivers (3/3 v2 runs); v1 wrote «پیش‌بینی کرد» and dropped the advice (2/2 runs: WP3 and today) |
| t1 | v2 «بررسی می‌کنیم» instead of «بحث خواهیم کرد»; still «۱۲ درصد افزایش فروش», not «افزایش ۱۲ درصدی فروش» |
| c2 | v2 casual and concrete («حق داری خسته باشی… یه چای یا آب بخور»); v1 formal written Persian |
| c5 | v2 casual, a concrete suggestion, complete conditional; v1 clichés («تو لایق آرامش و شادی هستی») |
| n1 | Both keep the advice and the leader; v2 adds the attribution «اعلام کرد» and splits sentences |
| n2 | v2 «کارت گرافیک»، «فضای ابری»، «مجموعه‌های داده»; but "fine-tune" → «بهینه‌سازی» (v1 «تنظیم دقیق» is more accurate) |
| n3 | v2 casual; one odd phrase «از اجتماع فاصله بگیری» |

### 6.2 Dev check (8 cases; v1 = 2026-11-26 baseline `dev_20261126-1913_v1-baseline`, v2 = `dev_20261127-1112_v2-targeted`)
| Case | Skills | Routing v1 / v2 | Output checks v1 | Output checks v2 | `postprocess` fired v1 / v2 | Note on v2 |
|---|---|---|---|---|---|---|
| D01 | summarizer (en) | ✓ / ✓ | script_latin ✓ no_preamble ✓ | same ✓ ✓ | none / none | 98 → 100 words |
| D02 | summarizer (fa) | ✓ / ✓ | script_fa ✓ no_arabic ✓ no_preamble ✓ | same ✓ ✓ ✓ | none / none | 106 → 136 words |
| D04 | translator fa→en | ✓ / ✓ | script_latin ✓ | ✓ | none / none | identical output |
| D10 | summarizer → translator (fa) | ✓ / ✓ | script_fa ✓ no_arabic ✓ | ✓ ✓ | none / none | |
| D12 | summarizer (EN text → fa) | — / ✓ | not run | script_fa ✓ no_arabic ✓ | — / none | **meaning inverted:** «خورشید در شب می‌درخشد» |
| D23 | summarizer (FA text → en, 3 bullets) | — / ✓ | not run | script_latin ✓ no_preamble ✓ | — / none | 3 bullets |
| D24 | summarizer → translator (en) | — / ✓ | not run | script_latin ✓ | — / none | |
| D28 | translator en→fa | — / ✓ | not run | script_fa ✓ no_arabic ✓ | — / none | «موزه در روزهای تعطیل رسمی بسته است.» |

v2: routing-correct 8/8 and every output check passed. The automated checks cover script, letters and preamble only, so they do not catch D12's inversion.

### 6.3 Before → after → why (for the README)
**Skill:** summarizer, Persian news → Persian summary (sample s2).

**Input** (Persian weather news, excerpt): «سازمان هواشناسی **اعلام کرد** که از فردا یک سامانهٔ بارشی … وارد کشور می‌شود … این سازمان **از کشاورزان خواسته است** برای حفاظت از محصولات گلخانه‌ای اقدام کنند و **به رانندگان توصیه کرده است** از سفرهای غیرضروری به مناطق کوهستانی خودداری کنند …»

**v1 prompt** (excerpt): `1. Use only information that is in the text. Add no facts, background, opinions or advice.`

**v1 output** (2026-11-27; the 2026-11-26 run had the same two defects):
> سازمان هواشناسی **پیش‌بینی کرد** که از فردا یک سامانهٔ بارشی وارد کشور شده و تا پایان هفته بیشتر استان‌ها را فرا می‌گیرد؛ در این میان، احتمال بارش شدید و آب‌گرفتگی در گیلان و مازندران و کاهش ۸ درجه‌ای دما در تهران وجود دارد. این بارش‌ها می‌تواند بخشی از کمبود آب سدهای تهران را جبران کند، اما برای رفع کامل خشک‌سالی کافی نیست و هوا از روز جمعه به‌تدریج پایدار می‌شود.

**v2 prompt** (excerpt):
```
1. … Add no facts, background, opinions or advice of your own.
6. Keep who said what, with the source's own kind of verb: "announced" stays announced («اعلام کرد»),
   "warned" stays warned («هشدار داد») … (an announcement is not a prediction, a claim is not a fact).
7. Advice, requests and warnings that the text addresses to specific people (residents, drivers,
   customers, students…) are key content, not minor details: keep them, briefly.
```

**v2 output** (final prompt `601357a578af`):
> سازمان هواشناسی **اعلام کرد** که از فردا یک سامانهٔ بارشی وارد کشور می‌شود که در گیلان و مازندران احتمال آب‌گرفتگی معابر و در تهران کاهش ۸ درجه‌ای دما را در پی دارد؛ **این سازمان از کشاورزان خواسته برای حفاظت از محصولات گلخانه‌ای اقدام کنند و به رانندگان توصیه کرده از سفرهای غیرضروری به مناطق کوهستانی خودداری کنند.** کارشناسان می‌گویند این بارش‌ها می‌تواند بخشی از کمبود آب سدهای استان تهران را جبران کند، اما برای رفع کامل خشک‌سالی کافی نیست و به گفتهٔ مدیرکل پیش‌بینی، از روز جمعه هوا به‌تدریج پایدار می‌شود و دما دوباره افزایش می‌یابد.

**Why:** the owner's v1 review (s2: A4, N4) noted that «اعلام کرد» became «پیش‌بینی کرد» and the advice to farmers and drivers was dropped. Rule 1's "add no … advice" likely read as "drop advice", and nothing protected the source's verb. v2 narrows rule 1 to advice *of your own* and adds rules 6 and 7. Result: v1 showed both defects in 2/2 runs; v2 showed neither in 3/3 runs. These are single runs, not a rate. The owner's A/B score for s2 is pending.

## 7. Known issues, limitations, risks
- **summarizer v2 accuracy:** «شهردار» for a councillor (s4, 2 of 3 v2 runs), and the negation lost in D12. I didn't run D12 at v1, so I can't tell whether v2 caused the D12 error. One candidate cause for s4 is v2's "keep every role explicit". A v3 candidate is to keep only the «به رهبری» construction and drop the push to label every role. This is untested.
- **translator v2 did not fix t1's collocation.** The rule with a different example («کاهش ۳۰ درصدی قیمت‌ها») did not transfer to «افزایش ۱۲ درصدی فروش» in one run.
- Every comparison is n=1 per prompt version at non-zero temperature. Run-to-run variance is visible: v1 s4 was not broken today.
- The A/B covers Persian output only. FA→EN register (WP0 items 4 and 5) and the English decline (c3) were changed but not measured live.
- v2 system prompts are larger. Estimator, rendered for Persian: summarizer 524 → 958 tokens, translator 658 → 981, general_chat 577 → 843. Measured per-case provider cost: +11 % to +21 % (§4).

## 8. Questions for the architect
1. If the owner's A/B supports general_chat and translator v2 but not summarizer v2, should I remove `summarizer/v2.md` on this branch before merge (as in the §4 proposal), or should the owner merge and delete it?
2. Should summarizer v3 (the role-label fix) be attempted before the final test-set runs, given today's quota?

## 9. Files touched outside my ownership
- `tests/unit/skills/test_{general_chat,summarizer,translator,text_helpers}.py` (WP3): 4 assertions that hard-coded `prompt_version == 1` now assert the loaded (highest) version. Without this, any merged `v2.md` breaks them. Their v1-specific content checks pass on v2 unchanged. v1's own coverage moved to `test_prompts_v2.py` (frozen sha, pinning).
- `eval/reports/dev_20261127-1112_v2-targeted.md` (WP6 area): a generated report, committed as the dev-check evidence. Its raw JSONL logs are git-ignored and stay in the worktree's `eval/reports/raw/`. I deleted the partial `…1107…` report (my own output, superseded by the resumed `…1112…` one).

## 10. Dependencies added
None.

## 11. Commits
```
1313328 docs(eval): targeted dev check at text-skill prompts v2
ba0e1bd test(live): blind v1/v2 A/B runner with the Persian review sheet and key
42f668a fix(prompts): summarizer v2 adds no titles or days, few-shot without a weekday
4644009 test(skills): v2 templates, frozen v1 hashes and version pinning
cc1d955 feat(prompts): general_chat v2 for casual Persian register and tailored declines
401c3db feat(prompts): translator v2 for Persian collocations, terms and register
80d9c31 feat(prompts): summarizer v2 for natural Persian from English sources
6f92def test(skills): assert the default prompt version instead of a literal v1
(+ this report: docs(handoff): WP7a report)
```

## 12. Live LLM calls made
Groq `qwen/qwen3.8-27b`. **40 successful calls, exactly the budget**: A/B 16 + 2 × 3 summarizer re-runs = 22; dev check 16 + 2 = 18. That is 49 HTTP attempts: the 9 extras were per-minute 429 retries the gateway absorbed, which returned no completion. No daily-quota 429. Dev-check provider tokens: 32 917 prompt + 2 266 completion. A/B tokens weren't recorded per call (estimated < 25K). Throttle ≥ 2 s between calls (A/B) and the runner's automatic throttle (dev).
