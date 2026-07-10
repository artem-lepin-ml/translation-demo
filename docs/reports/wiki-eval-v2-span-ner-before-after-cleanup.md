# Wiki-eval v2 span-level NER — before/after the gold-cleanup campaign

Offline replay, gemini-3.1-flash-lite 10-article pilot (`reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z/`). No LLM calls, no network. `gt.jsonl` was never modified; `pred.jsonl` was only read. Method: reused verbatim from Section D of
[wiki-eval-v2-pilot-ner-vs-disambig.md](wiki-eval-v2-pilot-ner-vs-disambig.md) — QID-agnostic token-span overlap between the 1203 pred mentions and gold anchors, tier-filtered (`tier_assignment.json`), named/term classified via `aggregate_corpus_v3._classify` pooled over each unit's surfaces. Script:
[data/eval/wiki/cleanup/tools/span_ner_before_after.py](../../data/eval/wiki/cleanup/tools/span_ner_before_after.py) (deterministic, two runs byte-identical).

## Why this exists

Since the pilot-analysis report, the gold changed twice: commit `4c77b7c` dropped 56 spurious
IPA-template anchor tuples (4 articles), and commit `f4c3d00` replaced 5 non-ancient articles.
Separately, `data/eval/wiki/anchor_exclusions_draft.json` (@`13553f8`) now lists 750 semantic
exclusions from the 10-wave gold-cleanup campaign — **DRAFT, not applied to `gt.jsonl` on disk**,
pending owner approval. This report answers: what would the pilot's span-level recall/precision
look like if those exclusions were live, restricted to the pilot's own 10 articles?

## Pilot-article status

| title | status |
|---|---|
| KV35YL | kept |
| XXVII династия | kept |
| XXX династия | kept |
| Абдмилькат | kept |
| Азиатская экспедиция (336—334 до н. э.) | kept |
| Академия Цзися | kept |
| Амударьинский клад | kept |
| Арахозия | kept |
| Армия империи Хань | kept |
| Арслантепе (Мелид) | kept |

**All 10 pilot articles are kept** — none coincide with the 5 titles `f4c3d00` replaced
(Гелиополиты, Керченский пролив, Кесарево безумие, Стигия, Яффа). Status above is derived from
actual title membership in the current `gt.jsonl` (not the hardcoded replaced-title list, which
the script keeps only as a documentation cross-check).

Stronger than that: the 10 pilot articles' `gt_tuples` are **byte-identical** across the pre-fix
snapshot (`4c77b7c~1`), the post-IPA-fix snapshot (`4c77b7c`), and current `gt.jsonl` (post
`f4c3d00`) — verified tuple-by-tuple, not just by count. Neither gold change touched this pilot's
10 articles at all. Every "after" delta below comes exclusively from the in-memory draft
exclusions, not from the two already-committed gold changes.

## Baseline reproduction (sanity gate)

Gold = `gt.jsonl` at `4c77b7c~1`, the snapshot the published report used (confirmed identical to
the pilot's 10 articles as above). **Gate: PASS** — reproduced the published numbers exactly:

| class | hit | total | recall |
|---|---:|---:|---:|
| named | 400 | 428 | **93.46%** (report: 93.5%) |
| term | 59 | 95 | **62.11%** (report: 62.1%) |
| **overall** | 459 | 523 | **87.76%** (report: 87.8%) |

Per-article spread matches too: min 78.38% (Амударьинский клад), max 100.0% (Академия Цзися) —
21.6pp spread, same as the published report.

## Before vs after

"After" gold = current `gt.jsonl`, restricted to the 10 kept pilot articles, minus the live
exclusions from `anchor_exclusions_draft.json` matched by `(title, token_index, anchor_text, qid,
span_len)`, applied in-memory only.

### Recall (mention-level, over gold anchors)

| class | before hit/total | before recall | after hit/total | after recall | Δ recall |
|---|---:|---:|---:|---:|---:|
| named | 400/428 | 93.46% | 400/419 | **95.47%** | +2.0pp |
| term | 59/95 | 62.11% | 57/84 | **67.86%** | +5.7pp |
| **overall** | 459/523 | 87.76% | 457/503 | **90.85%** | +3.1pp |

The denominator (`total`) drops by exactly 20 (523 → 503) — every tier-0 exclusion removed a
*singleton*-anchor gold unit (no unit lost only some of its anchors, and no unit changed
named/term class as a result — verified directly, not assumed). `hit` drops too (459 → 457,
named unchanged at 400, term 59 → 57): 2 of the 20 removed term-class anchors had actually been
correctly matched by a pred mention, so removing them costs 2 true hits but removes 11 anchors
from the term denominator — net recall still rises because the ratio improves.

### Precision (mention-level, over the 1203 pred mentions; severe lower bound — see caveats)

| class | before hit/total | before precision | after hit/total | after precision | Δ |
|---|---:|---:|---:|---:|---:|
| named | 390/928 | 42.03% | 390/928 | 42.03% | 0.0pp |
| term | 67/275 | 24.36% | 65/275 | **23.64%** | −0.7pp |
| **overall** | 457/1203 | 37.99% | 455/1203 | **37.82%** | −0.2pp |
| dedup (`(title, norm(lemma/surface))` groups) | 366/690 | 53.04% | 364/690 | **52.75%** | −0.3pp |

Precision's denominator (1203 pred mentions) is pred-side and unaffected by a gold change; only
`hit` can move, and only downward (fewer gold anchors to match against) — named is untouched (no
tier-0 named exclusion happened to be the *sole* anchor overlapping any pred mention), term loses
2 hits, dedup loses 2 groups. The effect is small and one-directional, as expected.

## Excluded-anchor counts per article

`n_exclusion_entries_matched` = all matched exclusion identities for that article (any tier);
`n_tier0_anchors_removed` = the subset that is tier-0 and therefore actually moves the D-metric
denominators above (the rest were already dropped by the tier filter regardless of the exclusion
list, so removing them changes nothing here).

| title | gt_tuples before → after | exclusions matched | of which tier-0 (metric-affecting) |
|---|---:|---:|---:|
| KV35YL | 44 → 36 | 8 | 6 |
| XXVII династия | 41 → 41 | 0 | 0 |
| XXX династия | 26 → 26 | 0 | 0 |
| Абдмилькат | 40 → 38 | 2 | 1 |
| Азиатская экспедиция (336—334 до н. э.) | 56 → 55 | 1 | 1 |
| Академия Цзися | 32 → 25 | 7 | 0 |
| Амударьинский клад | 42 → 33 | 9 | 4 |
| Арахозия | 27 → 23 | 4 | 2 |
| Армия империи Хань | 26 → 26 | 0 | 0 |
| Арслантепе (Мелид) | 239 → 224 | 15 | 6 |
| **total** | 573 → 527 | **46** | **20** |

All 46 matched exclusion identities were verified to actually exist in `gt.jsonl`'s current
tuples for these articles (0 unmatched) — the draft exclusion file's identities are consistent
with the live gold for this pilot.

## Caveats (honest, nothing hidden)

1. **Draft, not live.** `anchor_exclusions_draft.json` exclusions are applied here strictly
   in-memory for this analysis; `gt.jsonl` on disk is untouched, per the task's constraint and
   pending the owner's approval of the draft.
2. **All 10 pilot articles happened to be untouched by both prior gold commits.** This is a
   convenient coincidence for this specific pilot, not a general property of the cleanup — a
   different 10-article sample would show the IPA-fix and article-swap deltas directly. The
   entire "after" delta reported here is 100% attributable to the still-unapproved draft
   exclusions.
3. **Precision remains a severe lower bound**, same caveat as the original report: Wikipedia
   links only the first mention of each entity, so every correct repeated mention counts as a
   miss. Read it as "at most ~38% of extracted spans are novel-first-mention-worthy," not as
   true extraction correctness — before or after this cleanup pass.
4. **Small sample.** 10 articles, one model, one config (`111`). 20 tier-0 anchors moved the
   recall denominators — not enough to treat the per-class deltas (especially term, n=84 after)
   as more than descriptive.
5. **No class reclassification and no partial-unit removal occurred** in this pilot's 20 tier-0
   exclusions — verified directly (each excluded tier-0 anchor was its unit's only anchor, and no
   unit's named/term class changed). This kept the "after" analysis simple; it is not guaranteed
   to hold on other article subsets.
