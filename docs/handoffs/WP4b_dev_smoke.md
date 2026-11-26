# Router dev smoke (2026-11-26 13:24)

| id | plan | lang | signature | resp. lang | src | prompt_tokens | latency ms | guards |
|---|---|---|---|---|---|---|---|---|
| D01 | ✓ | ✓ | `summarizer(user)` | en | llm | 2442 | 1421 |  |
| D02 | ✓ | ✓ | `summarizer(user)` | fa | llm | 2578 | 641 |  |
| D03 | ✓ | ✓ | `translator(user, target_language=fr)` | en | llm | 2296 | 1391 |  |
| D04 | ✓ | ✓ | `translator(user, source_language=fa, target_language=en)` | fa | llm | 2302 | 594 |  |
| D05 | ✓ | ✓ | `calculator(user)` | en | rule |  | 1 |  |
| D06 | ✓ | ✓ | `calculator(user)` | fa | llm | 2307 | 1015 |  |
| D07 | ✓ | ✓ | `general_chat(user)` | en | llm | 2293 | 687 |  |
| D08 | ✓ | ✓ | `general_chat(user)` | fa | llm | 2289 | 922 |  |
| D09 | ✓ | ✓ | `general_chat(user)` | en | llm | 2291 | 610 |  |
| D10 | ✓ | ✓ | `summarizer(user) -> translator(s1, target_language=fa)` | en | llm | 2434 | 1281 |  |
| D11 | ✓ | ✓ | `translator(user, target_language=fa) + calculator(user)` | en | llm | 2301 | 703 |  |
| D12 | ✓ | ✓ | `summarizer(user)` | fa | llm | 2436 | 1531 |  |
| D13 | ✓ | ✓ | `CLARIFY(en)` | en | llm | 2287 | 828 |  |
| D14 | ✓ | ✓ | `general_chat(user)` | en | llm | 2292 | 1156 |  |
| D15 | ✓ | ✓ | `calculator(user) -> translator(s1, target_language=fa)` | en | llm | 2298 | 672 |  |
| D16 | ✓ | ✓ | `summarizer(user) -> translator(s1, target_language=de)` | en | llm | 2441 | 1125 |  |
| D17 | ✓ | ✓ | `general_chat(user)` | fa | llm | 2292 | 656 |  |
| D18 | ✓ | ✓ | `translator(user, target_language=en)` | fa | llm | 2310 | 984 |  |
| D19 | ✓ | ✓ | `calculator(user)` | en | llm | 2301 | 625 |  |
| D20 | ✓ | ✓ | `CLARIFY(en)` | en | llm | 2292 | 985 |  |
| D21 | ✓ | ✓ | `calculator(user)` | fa | llm | 2300 | 546 |  |
| D22 | ✓ | ✓ | `translator(user, source_language=fa, target_language=en)` | fa | llm | 2310 | 1813 |  |
| D23 | ✓ | ✓ | `summarizer(user, format=bullets, length=short, output_language=en)` | en | llm | 2551 | 782 |  |
| D24 | ✓ | ✓ | `summarizer(user) -> translator(s1, target_language=en)` | fa | llm | 2557 | 1125 |  |
| D25 | ✓ | ✗ | `general_chat(user)` | en | llm | 2297 | 641 | G2_language |
| D26 | ✓ | ✓ | `general_chat(user)` | en | llm | 2299 | 1890 |  |
| D27 | ✓ | ✓ | `general_chat(user)` | fa | llm | 2296 | 812 |  |
| D28 | ✓ | ✓ | `translator(user, target_language=fa)` | en | llm | 2299 | 907 |  |
| D29 | ✓ | ✓ | `summarizer(user)` | en | llm | 2425 | 453 |  |
| D30 | ✓ | ✓ | `summarizer(user, format=paragraph, length=short)` | en | llm | 2914 | 1234 |  |
| D31 | ✓ | ✓ | `translator(user, source_language=fa, target_language=fa)` | en | llm | 2578 | 1906 |  |
| D32 | ✓ | ✓ | `CLARIFY(en)` | en | llm | 2286 | 891 |  |
| D33 | ✓ | ✓ | `translator(user, target_language=fa)` | en | llm | 2328 | 578 |  |
| D34 | ✓ | ✓ | `calculator(user)` | fa | llm | 2311 | 1203 |  |
| D35 | ✓ | ✓ | `translator(user, target_language=de) + calculator(user)` | fa | llm | 2324 | 1296 |  |
| D36 | ✓ | ✓ | `calculator(user) + translator(user, target_language=en)` | fa | llm | 2323 | 1453 |  |
| D37 | ✓ | ✓ | `CLARIFY(en)` | en | llm | 2291 | 547 |  |
| D38 | ✓ | ✓ | `summarizer(user, format=paragraph, length=short)` | en | llm | 2439 | 922 |  |
| D39 | ✓ | ✓ | `translator(user, target_language=fa)` | en | llm | 2298 | 671 |  |
| D40 | ✓ | ✓ | `calculator(user) + general_chat(user)` | en | llm | 2307 | 968 |  |

```
cases: 40 (scored 40, errors 0)
plan accuracy: 40/40
language accuracy: 39/40
route_source: llm 39, rule 1, fallback 0
p50 router latency (llm cases): 922 ms
median prompt_tokens: 2302
live HTTP responses: 39 (attempts incl. retries: 39)

cases D01–D20: 20 (scored 20, errors 0)
plan accuracy: 20/20
language accuracy: 20/20
route_source: llm 19, rule 1, fallback 0
p50 router latency (llm cases): 922 ms
median prompt_tokens: 2301
```
