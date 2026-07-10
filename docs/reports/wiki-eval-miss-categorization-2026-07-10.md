# Wiki-eval miss categorization — gemini 10-article slice, 2026-07-10

Artifact: [data/eval/wiki/cleanup/miss_categorization_gemini10.json](../../data/eval/wiki/cleanup/miss_categorization_gemini10.json)
(74 entries + the tables below + provenance header).

## Scope

74 misses / 358 gold entities from the `google--gemini-3.1-flash-lite--Google-AI-Studio`
wiki-eval run (run `111`, `2026-07-10T20-19-19Z`), first 10 articles: KV35YL, XXVII
династия, XXX династия, Абдмилькат, Азиатская экспедиция (336—334 до н. э.), Академия
Цзися, Амударьинский клад, Арахозия, Армия империи Хань, Арслантепе (Мелид).

## Method

1. **Harness** — `data/eval/wiki/cleanup/tools/search_miss_analysis.py` produced
   `gemini_misses_10.json`: for each gold entity not scored `candidates_hit`, it records
   the outcome class (`not_extracted` / `no_candidates` / `retrieval_miss`), the NER
   category(-ies) of any overlapping predicted mention, and the returned Wikidata
   candidate list.
2. **5-agent wave** — the 74 misses were split into 5 chunks of 14-15; five Sonnet
   agents independently categorized each entry (`primary_category`, `rescue_by`,
   `evidence`) and **empirically replicated the search** against the live Wikidata
   `wbsearchentities` API for every single entry (`checked_wikidata=true` on all 74) —
   not just trusting the harness's captured candidate list, but re-running
   surface/lemma/canonical-label queries themselves to confirm root cause and whether a
   label-guess would actually rescue it.
3. **Aggregation** (this pass) — merged the 5 chunks, validated 1:1 against
   `gemini_misses_10.json` by `(gold_qid, article)` key, cross-checked `surface` against
   `gold_mentions[*].anchor_text`, and normalized one semantic inconsistency (below).

## Validation result: 74/74, zero discrepancies

- Every `(gold_qid, article)` pair in `gemini_misses_10.json` appears in the merged set
  exactly once; no missing, no extra, no duplicate keys on either side.
- Every merged `surface` matches one of the source entry's `gold_mentions[*].anchor_text`
  (agents took the first mention's anchor text as `surface` for multi-mention misses,
  consistently).
- `outcome_class` matches the source `outcome` for all 74.
- `primary_category` (5 values: `other`, `morphology-gap`, `honest-ner-miss`,
  `gold-noise`, `search-truncation`) and `outcome_class` (3 values) use a single clean
  spelling across all 5 chunks — **no spelling normalization was needed**.
- **One semantic normalization was needed** on `rescue_by`: 3 entries — Q7209 (Армия
  империи Хань, "Западной Хань"), Q1023301 (Арслантепе (Мелид), "Куммух"), Q1790257
  (Арслантепе (Мелид), "Кумме") — were labelled `rescue_by=none` by their originating
  agents even though their own evidence text states the correct real-world entity was
  already present among the harness's returned candidates (verified against
  `overlapping_pred_mentions` in `gemini_misses_10.json`). That is exactly the situation
  the Q373521 (Псамметих III) entry was labelled `already-hit-in-reality` for by a
  different agent. Relabeled all 4 consistently to `already-hit-in-reality`. This moves
  count from `already-hit-in-reality: 1` to `4`, and `none: 21` to `18`.

## Tables

### 2a. `primary_category` — overall and × outcome_class

| Category | Overall | not_extracted | no_candidates | retrieval_miss |
|---|---|---|---|---|
| other | 24 (32.4%) | — | 8 (42.1%) | 16 (41.0%) |
| morphology-gap | 23 (31.1%) | — | 9 (47.4%) | 14 (35.9%) |
| honest-ner-miss | 15 (20.3%) | 15 (93.8%) | — | — |
| gold-noise | 6 (8.1%) | 1 (6.2%) | 1 (5.3%) | 4 (10.3%) |
| search-truncation | 6 (8.1%) | — | 1 (5.3%) | 5 (12.8%) |
| **Total** | **74** | **16** | **19** | **39** |

Reading: `not_extracted` is almost entirely genuine NER misses (span never tagged, so no
search stage was reached) — the one exception is gold-noise (Q12859263 "оратора", a
common-noun apposition, not a real named-entity span). `no_candidates` and
`retrieval_miss` are dominated by `morphology-gap` (inflected/transliteration-variant
surface vs. canonical label) and `other` (compound-phrase / demonym-vs-polity /
alias-not-indexed mismatches).

### 2b. `rescue_by` — overall and × outcome_class (post-normalization)

| rescue_by | Overall | not_extracted | no_candidates | retrieval_miss |
|---|---|---|---|---|
| label-guess | 52 (70.3%) | — | 18 (94.7%) | 34 (87.2%) |
| none | 18 (24.3%) | 16 (100%) | 1 (5.3%) | 1 (2.6%) |
| already-hit-in-reality | 4 (5.4%) | — | — | 4 (10.3%) |
| alt-names | 0 (0%) | — | — | — |

**Notable: `alt-names` is 0 across all 74 entries.** No miss in this slice was rescuable
by simply searching an in-sentence parenthetical alternate name (e.g. "Мелид-Камману
(Хате, «Великая Хатти»)"). Every rescuable entry needed `label-guess` — knowledge of the
canonical Wikidata ru-label, which is frequently *not* derivable from anything in the
sentence (e.g. surface "быку" [bull] → canonical "Апис"; surface "Персией" → canonical
"Держава Ахеменидов"). Two agents (chunks 4/5) explicitly checked and rejected
`alt-names` as inapplicable for Q1149666 (Вашуканни → Телль-Фехерия), Q2062419
(Айраратское царство → Ервандидское царство), Q2142541 (Гузана → Тель-Халаф) — the
in-sentence parenthetical, where one existed, named a different concept, not the
rescuing alias.

### 2c. NER-category distribution of misses × outcome_class

From `gemini_misses_10.json`'s `overlapping_pred_mentions[*].category` (multi-category
mentions counted once per distinct category per entity — 4 known multi-category
entities, listed below).

| Category | no_candidates | retrieval_miss |
|---|---|---|
| place | 7 | 16 |
| people | 6 | 8 |
| person | — | 7 |
| culture | 3 | 3 |
| event | 2 | 1 |
| institution | 2 | 1 |
| title | — | 2 |
| deity | 1 | — |
| realia | — | 1 |
| language | — | 1 |
| dynasty | — | 1 |
| **category-instance sum** | **21** | **41** |

`not_extracted`: n/a — by construction these have no `overlapping_pred_mentions` (NER
never produced a span to categorize).

Category-instance sum (21+41=62) exceeds the 58 search-stage misses by exactly 4 — the 4
multi-category entities:

| gold_qid | article | surface | categories |
|---|---|---|---|
| Q389688 | XXX династия | "Персидской империей" | institution, people |
| Q389688 | Азиатская экспедиция (336—334 до н. э.) | "Персией" | people, place |
| Q131802 | Амударьинский клад | "скифского «звериного стиля»" | culture, people |
| Q770281 | Арслантепе (Мелид) | "позднехетских царств" | culture, institution |

`place` (23 instances) and `people`/`person` (14+7=21 instances) dominate — consistent
with the corpus being ancient-history articles full of toponyms, ethnonyms and
demonym-vs-polity references.

### 2d. Projected search-stage uplift (58 = 19 no_candidates + 39 retrieval_miss)

| Mode | Rescued (this mode) | Cumulative rescued | Remaining |
|---|---|---|---|
| baseline | — | 0 | 58 |
| +alt-names | 0 | 0 | 58 |
| +label-guess | 52 | 52 | 6 (5 metric artifacts + 1 irreducible) |

**`candidates_hit` rate, this 10-article slice (358 gold entities):**

| Configuration | Hits | Rate |
|---|---|---|
| baseline (production) | 284/358 | 79.3% |
| +alt-names | 284/358 | 79.3% (unchanged) |
| +label-guess (cumulative) | 336/358 | 93.9% |
| *(aside)* if the 5 metric-artifact gold rows were also corrected | 341/358 | 95.3% |

**Metric artifacts (5 of the 58) — not real search failures, flagged FOR OWNER DECISION.**
These entries make production's `candidates_hit` metric look worse than the retrieval
actually is; **`gt.jsonl` and `anchor_exclusions.json` were NOT touched** — this is a
report, the owner decides whether/how to correct gold:

| gold_qid | article | surface | outcome_class | issue |
|---|---|---|---|---|
| **Q373521 / Q316278** | XXVII династия | "Псамметих III" | retrieval_miss | `gold_qid` Q373521 is *currently* labelled "Псамметих II" on Wikidata (ruwiki sitelink "Псамметих II") — a different pharaoh than the sentence describes. The single returned candidate **Q316278** is labelled "Псамметих III" and matches the sentence exactly; search also ranks it #1. **This is the relabel case** — the gold annotation likely predates a Wikidata QID/label reshuffle for this pharaoh numbering. |
| Q7209 / Q1072949 | Армия империи Хань | "Западной Хань" | retrieval_miss | A precise, correctly-labelled entity for "Западная Хань" already exists (**Q1072949**, ru label "династия Западная Хань") and was itself among the returned candidates. Recorded gold Q7209 is the broader parent "империя Хань" (whole Han dynasty) — an imprecise gold pick, not a retrieval failure. |
| Q1023301 / Q1792017 | Арслантепе (Мелид) | "Куммух" | retrieval_miss | Search on the exact surface finds **Q1792017** (ru label "Куммух", the Neo-Hittite kingdom, ruwiki sitelink literally titled "Куммух") — the obviously correct entity, already a returned candidate. Recorded gold Q1023301 is "Кемах", a modern town in Erzincan ~200km away with only a Wikidata-flagged-uncertain alias "Kummaha?" — a different real-world referent. |
| Q1790257 / Q1792004 | Арслантепе (Мелид) | "Кумме" | retrieval_miss | Gold ru-label is "Кумми" (Kummanni, Kizzuwatna's cult capital in Cilicia). The top search hit is **Q1792004** "Kumme" (ru alias "Кумме"), a distinct Urartu-border holy city; enwiki explicitly states Kummanni "should not be confused with Kumme". The sentence lists "Кумме" among Nairi/Urartu-region polities, matching Kumme's geography, not Kummanni's — the arguably-correct entity is already the top candidate. |
| **Q131802 / Q1092377** | Амударьинский клад | "скифского «звериного стиля»" | no_candidates | The phrase "скифский звериный стиль" is a verified ru **alias of Q1092377** ("скифо-сибирский звериный стиль" / Scythian art), not of Q131802 ("скифы"/Scythians, the ethnic group) assigned as gold. Searching the exact phrase returns only Q1092377 — this is a **wikidata-duplicate-style gold mis-annotation** (unlike the 4 rows above, no candidates were returned at all under Q131802, so this one is *not* "already-hit-in-reality" — it would need both a gold fix and a re-check that Q1092377 is retrievable). |

**Irreducible failure (1 of 58) even under oracle label-guess:**

- **Q12087706** (Академия Цзися, surface "ванов") — gold ru label is the bare title "Ван",
  a literal homograph shared by several unrelated Wikidata items (Vannes, Van/Turkey,
  etc.). Label-guess reproduces the *identical* query as the original surface search
  (`ван`/`ванов` share the same lemma-search string) and still ranks gold 17th/20 — a
  genuine ranking/disambiguation problem, not a naming problem. No amount of
  label-substitution rescues this one; it needs a re-ranking or disambiguation-context
  fix at the search stage itself.

## Key findings, ranked by actionability

1. **`morphology-gap` + `other` (54/74, 73%) are the largest fixable bucket, and all of it
   routes through `label-guess`, never `alt-names`.** If the search stage added a
   canonical-label fallback lookup (not a naive alt-names/parenthetical scan), it would
   close ~52 of the 58 search-stage misses on this slice (93.9% projected `candidates_hit`
   vs. 79.3% baseline).
2. **`honest-ner-miss` (15/74, 20%) is a pure NER recall problem**, not a search problem —
   these spans were never extracted at all (adjectival/genitive mentions like
   "древнеегипетских", "варварского", institution names in genitive case). No candidate
   search or label fix touches these; would need NER model/prompt changes.
3. **5 metric artifacts inflate the miss count** — the search retrieval already found the
   real-world-correct entity in 4/5 cases; the 5th needs a gold relabel too. These are
   listed explicitly above for owner review; **no gold file was modified**.
4. **1 genuinely irreducible case** (homograph collision on a single-character title
   "Ван") — worth noting as a search-stage limit, not chasing further on this slice.

## What was NOT done

- `gt.jsonl` and `anchor_exclusions.json` were **not** touched — the 5 gold-noise
  entries above are flagged for owner decision only.
- No fix was implemented for `morphology-gap`/`label-guess`-rescuable misses; this is a
  categorization/measurement pass, not an implementation pass.
- Only the gemini run's first-10-article slice was analyzed; deepseek and gemma runs
  (also present under `reports/terminology/wiki-eval/`, untracked by another concurrent
  agent) were out of scope for this task.
