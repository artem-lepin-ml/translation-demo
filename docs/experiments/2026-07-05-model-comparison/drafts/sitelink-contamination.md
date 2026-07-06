# Sitelink-rung contamination — quantification (offline replay)

Method: for every grounded prediction (`qid != null`) in each run's `pred.jsonl`,
replay the G6 candidate ladder (`generate_candidates`,
[src/palimpsest/terminology/grounding/candidates.py](/home/user/translation-demo/src/palimpsest/terminology/grounding/candidates.py))
purely from the cached live-Wikidata responses in each run's own
`wikidata_cache.<model>.jsonl` — no network, no LLM calls. Config was `111`
(`use_lemma=True, use_fallbacks=True, match_aliases=True`, `search_limit=7`,
[base.py](/home/user/translation-demo/src/palimpsest/terminology/base.py) defaults,
confirmed via `scripts/wiki_eval.py:_config_from_bits`). `pred.jsonl` does not
itself record which rung supplied the candidate (`resolved_by` only records
`exact_label`/`llm_disambiguation`/etc., not the search mechanism) — the ladder
decision (`wbsearch` → `cirrus` → `sitelink`) had to be reconstructed.

**Replay fidelity: 100%.** Zero `unknown` (missing cache entry) and zero
`inconsistent` (all three rungs empty despite the row being grounded) rows in
either run — every grounded mention's ladder decision was fully reconstructable
from that run's own cache. As an independent correctness check, my own
per-article `match_m3`/`match_m2` recomputation over the **unfiltered**
prediction set reproduced the run's own `metrics.json` recall to the 4th decimal
in all four cells (gemini M3 5493/7959=0.6902, M2 5011/7959=0.6296; deepseek M3
4890/7959=0.6144, M2 4167/7959=0.5236) — the tuple/GT loading and matching logic
match the harness exactly, so the "clean" deltas below are trustworthy.

## 1. Source distribution of grounded predictions

| Model | n grounded | wbsearch | cirrus | **sitelink** | unknown |
|---|---:|---:|---:|---:|---:|
| gemini-3.1-flash-lite | 16,709 | 16,274 (97.4%) | 231 (1.4%) | **204 (1.22%)** | 0 |
| deepseek-v4-flash | 13,680 | 13,354 (97.6%) | 184 (1.3%) | **142 (1.04%)** | 0 |

The sitelink rung — RU-Wikipedia title → Wikidata QID via `pageprops`, the
mechanism that **directly replays** how the GT reference tuples themselves were
built (human wikilink → title → wikibase_item) — supplies ~1% of grounded
predictions in both runs. All 346 sitelink-sourced candidates across both runs
resolved via `llm_disambiguation` (**0%** via the deterministic `exact_label`
path): the sitelink lookup returns exactly one bare `{"id": qid}` candidate with
no guaranteed label match against the surface/lemma, so it always needed the
judge to confirm it — spot-checked below.

## 2. Sitelink-sourced predictions vs the reference (M3, document-level)

| Model | sitelink-sourced | of which match GT (M3, same article) | match rate |
|---|---:|---:|---:|
| gemini | 204 | 123 | 60.3% |
| deepseek | 142 | 74 | 52.1% |

A 52–60% match rate on a subpopulation of predictions whose candidate pool was
built from the *same construction the reference used* is the headline
circularity signal: these are not "the model got it right independently" —
for these mentions the model's grounding path and the GT's construction path
partially coincide by design.

## 3. Contamination's net effect on corpus recall (original vs sitelink-removed "clean")

"Clean" = drop the sitelink-sourced predictions from the prediction set, then
recompute `match_m3`/`match_m2` per article and re-sum (matches
`aggregate_corpus`'s micro-average: sum raw matched/total across articles, one
division at the end — never averaged per-article). Note the recall units lost
(49/41 for M3) are **smaller** than the raw sitelink-matched count (123/74):
some GT QIDs matched by a sitelink-sourced prediction are *also* independently
matched by another (wbsearch/cirrus-sourced) prediction elsewhere in the same
article, at the document level M3 credits any co-occurrence — removing the
sitelink one alone doesn't flip that QID back to "unmatched". So the exclusive
contamination (recall units actually attributable ONLY to the sitelink rung)
is 49/123 (gemini) and 41/74 (deepseek) of the raw sitelink-matched count.

### R (all 7,959 GT tuples, T0/unfiltered)

| Model | Mode | Original recall | Clean recall | Δ (pp) | Recall units lost |
|---|---|---:|---:|---:|---:|
| gemini | M3 | 0.6902 (5493/7959) | 0.6840 (5444/7959) | −0.62 | 49 |
| gemini | M2 | 0.6296 (5011/7959) | 0.6222 (4952/7959) | −0.74 | 59 |
| deepseek | M3 | 0.6144 (4890/7959) | 0.6092 (4849/7959) | −0.52 | 41 |
| deepseek | M2 | 0.5236 (4167/7959) | 0.5187 (4128/7959) | −0.49 | 39 |

### R-T2 (7,174 GT tuples surviving the tier-2 filter — meta/calendar/generic-lexical noise dropped; `tier_assignment.json`/`tier_defs.json`, membership `assignment==0`)

| Model | Mode | Original R-T2 | Clean R-T2 | Δ (pp) | Recall units lost |
|---|---|---:|---:|---:|---:|
| gemini | M3 | 0.7411 (5317/7174) | 0.7345 (5269/7174) | −0.66 | 48 |
| gemini | M2 | 0.6880 (4936/7174) | 0.6798 (4877/7174) | −0.82 | 59 |
| deepseek | M3 | 0.6631 (4757/7174) | 0.6574 (4716/7174) | −0.57 | 41 |
| deepseek | M2 | 0.5722 (4105/7174) | 0.5668 (4066/7174) | −0.54 | 39 |

## 4. Reading

- **Scale: small but not negligible.** The sitelink rung is ~1% of grounded
  volume and its removal costs 0.5–0.8 recall points (both M2/M3, both tiers,
  both models) — a real but minor share of headline recall. It does not
  explain the gemini/deepseek recall gap (both lose a comparable ~0.5–0.7pp).
- **The rung is disproportionately "GT-shaped."** Its 52–60% M3 match rate is
  well above what the sitelink rung's tiny 1% share would predict if hits were
  random noise — consistent with genuine circularity, not just "this rung
  fires on obscure real terms that the harness *also* happens to get right."
- **Tier filtering (T2) and sitelink contamination are near-orthogonal.**
  Removing sitelink drops recall by essentially the same absolute unit count
  at T0 and T2 (49→48 gemini M3, 41→41 deepseek M3) — the sitelink rung isn't
  concentrated in the generic-lexical noise T2 already strips out.
- **Caveat — this only measures the *candidate-generation* circularity**, not
  full annotation circularity: even a wbsearch/cirrus-sourced correct
  prediction could still coincide with the GT by construction elsewhere in the
  pipeline. This analysis isolates the one mechanism named in the brief
  (`wikipedia_wikibase_item` as the ladder's LAST rung) and nothing else.

## Replay-fidelity caveats

- **Unknown-cache count: 0/0** for both runs — every ladder decision for every
  grounded mention was fully reconstructable; no cache misses.
- **Inconsistent count: 0/0** — no case where a grounded row's replayed ladder
  found 0 hits at all three rungs (would indicate either a stale/shared cache
  entry from a different run, or a config mismatch); none observed.
- **lang assumed "ru" throughout** (`TermMention.lang` default, confirmed via
  `extract.py`'s two `TermMention(...)` construction sites and
  `wiki_eval.py`'s own hardcoded `lang="ru"` at its one other search-entities
  call site) — not per-mention-verified from `pred.jsonl` since that field
  doesn't carry `lang`, but the corpus is 100% RU source text so this is not a
  live risk.
- **Sitelink candidate's own QID was not independently re-derived from the
  cache and cross-checked against `pred.jsonl`'s `qid`** beyond a 5-row spot
  check (all 5 matched exactly) — by construction the sitelink rung yields
  exactly one candidate, so if the row is grounded (`qid != null`) that QID
  must be the sitelink lookup's result; this is a structural guarantee of
  `generate_candidates`, not an assumption specific to this replay.
- Numbers are for config **`111` only** (the config both target runs used);
  not a claim about other ablation configs' sitelink exposure.

Full machine-readable numbers: `sitelink_contamination.json` (same directory).
