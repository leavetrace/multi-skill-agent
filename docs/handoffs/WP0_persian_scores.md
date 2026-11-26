# WP0 — Owner's Persian review scores (Groq `qwen/qwen3.8-27b`, C2)

Scored by the owner (native Persian speaker) on 2026-11-26 from `WP0_persian_review.md`.
Scale 1–5. F = fluency (correctness, readability), A = accuracy (meaning preserved),
N = naturalness (idiomatic to a native speaker). Only C2 produced outputs, so this is an
absolute rating, not a comparison.

| # | Task | F | A | N | Owner's notes (summarised) |
|---|---|---|---|---|---|
| 1 | Casual EN → FA | 4 | 3 | 3 | «این هفته» means *this week*, not *this weekend* («آخر هفته»). «تماس قبلی‌ات» is stiff; «جواب تماست رو ندادم» is more natural. |
| 2 | Technical EN → FA | 4 | 4 | 3 | «حساب ابری» is wrong for *cloud computing*; the established term is «رایانش ابری». «فضای ذخیره‌سازی» is better than «حافظه» for *storage*; «برحسب نیاز» better than «به‌صورت درخواستی». |
| 3 | Entities EN → FA | 5 | 5 | 4 | Names, date, number and place preserved. «پژوهشی با مشارکت ۱۲۵۰ نفر» slightly more idiomatic. |
| 4 | Formal FA → EN | 4 | 5 | 3 | Accurate; "All respected members" is unnatural English ("All members"). |
| 5 | Colloquial FA → EN | 4 | 2 | 3 | «بابا ول کن دیگه» ≈ "Come on, give it a rest", not "Dad, stop ignoring me". «کلی منتظرت موندم» = "I waited for ages", not "all day". |
| 6 | Water summary FA → FA | 5 | 4 | 5 | Clear and natural; keeps the central causes and solutions. |
| 7 | Sleep summary FA → FA | 5 | 4 | 5 | Good summary; keeps the main message and recommendations. |
| 8 | Mood chat FA → FA | 5 | 5 | 4 | Considerate; slightly formal for a casual input. |
| 9 | Joke chat FA → FA | 3 | 2 | 2 | Punchline incoherent; no humour delivered. |
| | **Mean (unweighted, 9 items)** | **4.3** | **3.8** | **3.4** | |

**Owner's interpretation:** competent at straightforward translation and summarisation (best: entities, formal translation, summaries). Weaknesses: idiomatic/colloquial understanding, register (tends to formal Persian with casual input), established Persian technical terms, and creative generation (jokes). Summaries should be judged on whether they keep the central claims, not every fact.

**How this feeds the work:**
- Translator prompt v2 candidates (WP7): translate idioms and colloquial interjections by intended meaning; match the source register; prefer established Persian technical terms (e.g. «رایانش ابری»).
- General chat: mirror the user's register in Persian small talk.
- These are scores for raw WP0 probe prompts, not our WP3 prompts; the WP3 samples on Groq (`WP3_samples_groq.md`) are the next native review.
