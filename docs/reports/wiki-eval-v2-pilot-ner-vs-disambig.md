# Wiki-eval v2 pilot — decomposing recall/precision errors into retrieval vs disambiguation

Data-scientist analysis, gemini-3.1-flash-lite 10-article pilot. Fully offline: no LLM calls,
no network access — Wikidata candidate retrieval is replayed strictly against the committed
cache file, with the network path hard-disabled (raises on any miss, never fetches).

Scope: `A_fn_decomposition` (recall side), `B_oracle_recall`, `C_precision_decomposition`
(precision side), and an owner-requested addition, `D_span_level_ner` (QID-agnostic span
overlap quality). Script and full JSON: `<scratchpad>/ner_vs_disambig/replay_analysis.py` /
`replay_output.json` (not committed — scratch, reproducible by rerunning against the same
committed inputs).

## Inputs

- Pilot run (read-only, untouched): `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z/` — `pred.jsonl` (1203 records), `metrics.json`, `meta.json`.
- Gold: `data/eval/wiki/gt.jsonl`, restricted to the 10 titles present in `pred.jsonl` (verified identical to the pilot titles — see Reconciliation below).
- Tier filter: `data/eval/wiki/tier_assignment.json` (gold-side only, same as the production aggregator).
- Wikidata cache: `reports/terminology/wikidata_cache.jsonl` (22,200 lines; contains this run's own 3,204 cache hits + 352 appended network calls).
- Code reused as-is (not reimplemented): `palimpsest.terminology.evaluation.metrics.aggregate_corpus_v3` (+ its internal `_classify` helper), `palimpsest.terminology.grounding.candidates.generate_candidates`, `palimpsest.terminology.grounding.match.norm`, `palimpsest.terminology.wikidata.WikidataClient`.

## Method

### Reconciliation gate (run first, would have stopped the analysis on any mismatch)

`aggregate_corpus_v3` was called on `pred.jsonl` restricted to the 10 pilot titles + the gold
subset + the tier file — exactly the same call the run's own `cmd_report` makes. Result:

| class | tp | fn | fp | gold_units | match vs. task spec |
|---|---:|---:|---:|---:|---|
| named | 255 | 47 | 106 | 302 | exact |
| term | 32 | 45 | 62 | 77 | exact |

`n_ambiguous_gold_units=15`, `n_gold_mentions_dropped_by_tier=50` — both exact matches too. The
recomputed result also matches the run's own committed `metrics.json` byte-for-byte on every
`tp/fn/fp/gold_units`/`R_doc`/`P_doc` cell. **Gate: PASS, no discrepancy — proceeded.**

Exact `(article, qid)` unit sets for TP/FN/FP were then extracted by replicating
`aggregate_corpus_v3`'s own per-article grouping loop (same `tier_assignment` gate, same
`M._classify` call, not a rewritten classifier) and capturing the identifying tuples instead of
just counting. Self-consistency check: summing these sets back up reproduces the gate counts
above exactly, per class.

### Candidate replay

Every one of the 1203 `pred.jsonl` records (grounded and ungrounded alike) was replayed through
`generate_candidates()` with `TermMention(surface, lemma, lang="ru")` and the run's own
`GroundingConfig(use_lemma=True, use_cirrus=True, use_sitelink=False, match_aliases=True)`
(defaults `search_limit=7, enrich_top=5`, matching the cache's own `limit=7` query strings and
`meta.json`'s `grounding_config`). All Wikidata I/O went through `OfflineWikidataClient`, a
`WikidataClient` subclass that answers only from the in-memory dict loaded once from
`wikidata_cache.jsonl` at construction; a cache miss raises instead of calling `urllib`, and
`_store` is hard-disabled so a bug could never append to the real cache file. Zero network
sockets were opened.

**Cache-only guarantee, quantified:** `1203/1203` mentions replayed with **0 cache misses
(0.00%)** — well under the 2% partial-analysis threshold, so the full decomposition below is
reported as complete, not partial.

**Replay sanity checks:**
- Of the 946 mentions with `resolved_by ∈ {exact_label, llm_disambiguation}` (a chosen qid
  exists), the chosen qid was present in the replayed candidate set for **946/946 (100.00%)**.
- Of the 162 `resolved_by=no_candidates` mentions, the replayed candidate set was empty for
  **162/162 (100.00%)**.

Both sanity checks hit the ~100% target exactly — the replay reproduces the live run's own
retrieval decisions with no observed divergence on this pilot.

### Unit definitions

Unit level = unique `(article, qid)`, same as the v3 aggregator; class = named/term via the same
`_classify` (any-capitalized-surface -> named, pooled over the unit's gold anchors, ambiguous
units still classed named). Overlap = half-open token intervals `[index, index+span_len)`
intersect. All anchor/anchor-set operations below reuse the same tier-filtered anchor lists
(`tier_assignment.get(qid, 0) == 0`).

---

## A. FN decomposition (recall side)

Priority order (mutually exclusive, best case wins): `not_extracted` -> `no_candidates` ->
`retrieval_miss` -> `disambig_miss`.

| class | bucket | n | % of FN |
|---|---|---:|---:|
| named (n_fn=47) | retrieval_miss | 20 | 42.6% |
| named | not_extracted | 11 | 23.4% |
| named | disambig_miss | 10 | 21.3% |
| named | no_candidates | 6 | 12.8% |
| term (n_fn=45) | not_extracted | 24 | 53.3% |
| term | retrieval_miss | 15 | 33.3% |
| term | no_candidates | 4 | 8.9% |
| term | disambig_miss | 2 | 4.4% |

**Retrieval/coverage/NER bottleneck (buckets 1–3) vs. disambiguation bottleneck (bucket 4):**

| class | retrieval/coverage bottleneck | disambiguation bottleneck |
|---|---:|---:|
| named | 37/47 = **78.7%** | 10/47 = **21.3%** |
| term | 43/45 = **95.6%** | 2/45 = **4.4%** |

`disambig_miss` subcounts (what happened to the mention that had the gold QID among its
candidates but didn't pick it):

| class | subbucket | n |
|---|---|---:|
| named | resolved to a different QID (llm_disambiguation) | 9 |
| named | resolved to a different QID (exact_label) | 1 |
| term | resolved to a different QID (llm_disambiguation) | 1 |
| term | resolved to a different QID (exact_label) | 1 |

No `judge_rejected (qid=null)` subcount occurred on this pilot — every `disambig_miss` unit's
eligible mention actually picked a (wrong) QID rather than rejecting outright.

**Reading it — this is the headline finding of the report.** A prior surface/lemma-matching
analysis (`docs/reports/wiki-eval-v2-pilot-analysis.md`, Task 2, same run) attributed most named
FN to "the judge chose a different QID" (42.6% of named FN there) and read that as a
disambiguation-quality problem. With actual candidate-set replay, that read does not hold up:
**42.6% of named FN and 33.3% of term FN are `retrieval_miss` — candidates were present, but the
correct QID was in none of them** — a candidate-generation ceiling, not a judge failure. Once
`not_extracted` (NER coverage) and `no_candidates` are folded in, **78.7% of named FN and 95.6%
of term FN never had the correct QID available for any component to pick** — the bottleneck is
overwhelmingly upstream of disambiguation. True disambiguation-attributable misses are a
minority: 21.3% of named FN, 4.4% of term FN.

---

## B. Oracle recall ("if we wrote down every QID retrieval found")

Two variants, both protocol-v3-consistent (same gold filtering, same class split):

- **Article-pooled** `S_p_oracle` = union of replayed candidate QIDs over ALL 1203 mentions in
  that article; `R_oracle = |S_p_oracle ∩ S_t| / |S_t|` per class, pooled micro like `R_doc`.
- **Overlap-restricted** `S_p_oracle_overlap` (diagnostic) — same union, but only over mentions
  that token-span-overlap that specific unit's own gold anchors. This is the "recoverable by a
  perfect judge working from what retrieval actually surfaced at this position" ceiling.

| class | actual R_doc | R_oracle (article-pooled) | matched/total | R_oracle_overlap (position-restricted) | matched/total |
|---|---:|---:|---:|---:|---:|
| named | 84.44% | **88.41%** | 267/302 | **87.09%** | 263/302 |
| term | 41.56% | **44.16%** | 34/77 | **37.66%** | 29/77 |

Both oracle variants sit above actual R, as expected — the pooled ceiling is higher than the
position-restricted one since it also credits units whose correct QID surfaced somewhere else in
the article (a different mention of the same entity), not just at this unit's own gold anchor.

One honest wrinkle worth flagging: `R_oracle_overlap`'s matched count (263 named, 29 term) is
*below* `TP + disambig_miss` (265 named, 34 term) — i.e. a handful of TP units (2 named, 5 term)
were correctly grounded by a mention that did **not** span-overlap that unit's own gold anchor(s)
at all (a different mention of the same multiply-occurring entity, positioned elsewhere in the
article, happened to be the one that got graded correct under v3's article-wide qid-set rule).
This is a real property of the article-wide TP definition, not a bug in the replay — confirmed by
re-deriving the same delta from the independently-computed A/C unit sets.

**Escalated-mention candidate-set size** (mentions with `resolved_by ∈ {llm_disambiguation,
judge_rejected}`, n=668 — this number was flagged "not computable" in the prior surface-matching
report; the replay now closes that gap):

| stat | value |
|---|---:|
| mean | 4.35 |
| median | 5.0 |
| min / max | 1 / 5 (capped by `enrich_top=5`) |
| histogram (size: n) | 1: 49, 2: 47, 3: 29, 4: 39, 5: 504 |
| share with exactly 1 candidate | 7.3% (49/668) |

75.4% of escalated mentions hit the `enrich_top=5` cap — most disambiguation decisions face a
genuinely crowded candidate list, not a a near-trivial 1-candidate confirmation.

**`|S_p_oracle|` per article** (size of the article-pooled candidate union — the cost of "writing
down everything"):

| stat | value |
|---|---:|
| mean | 173.9 |
| median | 127.0 |
| min | 69 (Арахозия) |
| max | 411 (Арслантепе (Мелид)) |

---

## C. Precision decomposition (disambiguation-induced FP, by span overlap)

| class | bucket | n | % of FP |
|---|---|---:|---:|
| named (n_fp=106) | no_gold_overlap | 76 | 71.7% |
| named | disambig_swap | 30 | 28.3% |
| term (n_fp=62) | no_gold_overlap | 49 | 79.0% |
| term | disambig_swap | 13 | 21.0% |

`disambig_swap` subcounts (was the correct QID available to be picked instead?):

| class | subbucket | n | % of disambig_swap |
|---|---|---:|---:|
| named | forced_swap (right answer never surfaced) | 21 | 70.0% |
| named | true_wrong_pick (right answer was available) | 9 | 30.0% |
| term | forced_swap (right answer never surfaced) | 12 | 92.3% |
| term | true_wrong_pick (right answer was available) | 1 | 7.7% |

**Cross-check with A:** of the 12 `disambig_miss` FN units (10 named + 2 term), **10** have a
corresponding `disambig_swap` FP in the same article (the wrong QID that "stole" that unit's
span). The 2 without a matching swap FP are cases where the eligible mention's wrong pick did not
survive into the FP set as classified here (e.g. the wrongly-chosen QID happened to also be a
legitimate gold unit elsewhere, so it landed in TP rather than FP for that article) — consistent,
not a discrepancy.

**Reading it:** most FP is `no_gold_overlap` — extraction/grounding beyond what Wikipedia's sparse
hyperlink annotation captures (expected and documented as the reason `P_doc` is a conservative
lower bound, not true precision, per `metrics.py`'s own docstring). Within the genuinely
disambiguation-caused FP (`disambig_swap`), **forced swaps dominate over true wrong-picks for
both classes** (70.0% / 92.3%) — mirroring A's finding: retrieval not surfacing the right QID is
the larger lever than judge accuracy on already-available candidates.

---

## D. Span-level NER quality (QID-agnostic)

Owner-requested addition. Ignores QIDs entirely — pure token-span-overlap between the 1203 pred
mentions and the gold anchors (tier-filtered exactly as in A/B/C: `n_gt_tuples=573` total pilot
gold mentions minus 50 tier-dropped = **523** surviving anchors, split 428 named / 95 term —
reconciles exactly with `573 - 50 = 523`). Ambiguous-gold anchors are classed via the same
per-unit `gold_class` lookup used everywhere else in this report (an ambiguous unit's individual
anchors inherit the unit's "named" class, mirroring v3's any-capitalized-surface rule rather than
re-deciding per single anchor).

### NER recall (mention-level, over gold anchors)

| class | hit | total | recall |
|---|---:|---:|---:|
| named | 400 | 428 | **93.46%** |
| term | 59 | 95 | **62.11%** |
| **overall** | 459 | 523 | **87.76%** |

Per-article spread: min **78.4%** (Амударьинский клад), max **100.0%** (Академия Цзися) — a
21.6pp spread across the 10 articles.

### NER precision (mention-level, over pred mentions)

| class | hit | total | precision |
|---|---:|---:|---:|
| named | 390 | 928 | **42.03%** |
| term | 67 | 275 | **24.36%** |
| **overall** | 457 | 1203 | **37.99%** |

**Caveat, prominently flagged:** gold links only the *first* mention of each entity per Wikipedia
convention — every repeated true mention of an already-linked entity counts as a miss here, so
this raw span precision is a **severe lower bound**, not a measure of extraction correctness. It
should be read as "at most 38% of extracted spans are novel-first-mention-worthy," not "62% of
extraction is wrong."

**Dedup variant** (closer to honest): group pred mentions by `(article, norm(lemma or surface))`
— a group counts as a hit if ANY member overlaps a gold anchor.

| metric | value |
|---|---:|
| hit groups | 366 |
| total groups | 690 |
| precision (dedup) | **53.04%** |

The dedup variant recovers +15pp over the raw mention-level precision (38.0% -> 53.0%),
confirming a real chunk of the "miss" is the first-mention-only annotation artifact rather than
spurious extraction — though 53% still leaves a substantial share as either genuinely spurious
extraction or legitimate-but-unannotated entities (indistinguishable from Wikipedia's sparse
hyperlinking alone, same caveat as `P_doc` in C).

---

## Limitations (honest, nothing hidden)

1. **Cache misses: zero.** 1203/1203 mentions replayed with 0.00% cache misses — the analysis
   is reported as complete, not partial, per the task's own 2% threshold.
2. **Sanity checks: both 100%.** No divergence observed between the replay and the live run's own
   retrieval/grounding decisions on this pilot (946/946 chosen-qid-in-candidates,
   162/162 no_candidates-replays-empty). This is a small, single-pilot sample (10 articles) — it
   does not rule out divergence on a larger corpus with different query patterns.
3. **`R_oracle_overlap` < `TP + disambig_miss`** for both classes (263 vs 265 named, 29 vs 34
   term) — explained in section B as a genuine property of the article-wide TP definition
   (multiply-occurring entities graded correct via a non-overlapping mention), not a replay bug;
   flagged rather than silently smoothed over.
4. **Section C's `disambig_swap` classification uses a priority rule** (any qualifying
   overlap-pair marks the unit `true_wrong_pick`) when a FP qid's mentions overlap multiple gold
   anchors — documented in the method section, not hidden, but it is a hand-authored convention
   for this report, not an existing codebase primitive.
5. **Section D's precision (both raw and dedup) is confounded by Wikipedia's sparse
   first-mention-only linking**, as flagged inline — cannot be disentangled from genuinely
   spurious extraction using only this pilot's gold data.
6. **Single 10-article pilot, one model (gemini-3.1-flash-lite), one config (`111`,
   `--no-sitelink`).** None of these findings are claimed to generalize to the full 100-article
   corpus or other models without rerunning this same replay against their own pred.jsonl/cache
   state.
7. No statistical-significance testing (e.g. bootstrap CIs on the bucket shares) was run beyond
   the raw counts — sample sizes are small (e.g. term `disambig_miss` n=2), so bucket-share
   percentages at that end should be read as descriptive, not inferential.
