# Wiki-eval v2 pilot analysis — gemini-3.1-flash-lite, 10-article subset

Data-scientist analysis. Read-only on repo data, no commits. Scripts that reproduce
every number below live in the scratchpad (not committed — see "Reproducibility" at
the end of each section):

- `task1_subset_compare.py` — TASK 1 (apples-to-apples subset comparison)
- `task2_fn_decomposition.py` — TASK 2 (FN decomposition, old vs new)
- `task3_escalation_profile.py` — TASK 3 (judge-escalation profile)

Inputs:
- NEW pilot: `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z/pred.jsonl` (10 articles, v2 pipeline, `--no-sitelink`)
- OLD full run: `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z/pred.jsonl` (100 articles, pre-redo pipeline, sitelink rung on), restricted here to the same 10 titles
- Gold: `data/eval/wiki/gt.jsonl` (first 10 lines = pilot set), tier: `data/eval/wiki/tier_assignment.json`
- Aggregator: `palimpsest.terminology.evaluation.metrics.aggregate_corpus_v3` (same code path as `scripts/wiki_eval.py cmd_report`, verified below)

**Pilot titles (10):** KV35YL, XXVII династия, XXX династия, Абдмилькат, Азиатская экспедиция (336—334 до н. э.), Академия Цзися, Амударьинский клад, Арахозия, Армия империи Хань, Арслантепе (Мелид).

**Sanity check (before anything else):** recomputing `aggregate_corpus_v3` over the NEW run's 10 articles reproduces its committed `metrics.json` byte-for-byte on every `tp`/`fn`/`fp`/`gold_units` cell — confirms the subset-construction logic in the scripts matches `cmd_report` exactly.

---

## TASK 1 — apples-to-apples subset comparison

### Important caveat before reading the table

**This is not a clean sitelink-only ablation — the OLD and NEW runs differ in the whole v2 pipeline rework, not just `--no-sitelink`.** Per `docs/stages/wiki-eval.md`, the 2026-07-10 rework changed: the NER system/user prompt (English, `{surface, lemma}` schema replacing the old prompt), full-sentence judge context, the protocol-v3 set-based aggregator, the transport (standard OpenRouter vs. the retired CloseRouter gateway), and per-model vendor sampling (temperature/top_p/reasoning effort — the OLD run's `meta.json` has no `generation_params`/`grounding_config` block at all, confirming it predates that machinery). The sitelink toggle is one ingredient among several; deltas below should be read as "v2 pipeline vs. pre-redo pipeline on this subset," not as an isolated sitelink effect.

**Sitelink rung quantification — not possible from these pred.jsonl records.** `GroundingConfig.use_sitelink` is confirmed off in the NEW run (`grounding_config.use_sitelink: false` in its `meta.json`) and on in the OLD run (pre-redo default). But `resolved_by` in pred.jsonl (`exact_label` / `llm_disambiguation` / `no_candidates` / `judge_rejected` / `judge_unavailable`) reflects only the **grounding-decision** stage, not which **candidate-generation rung** produced the candidates — the `source` field that distinguishes `wbsearchentities` / `cirrus` / `wikipedia_langlink` (`grounding/candidates.py:66-84`) is generated but never written to a pred record (`predict.py:86-93` keeps only `index/surface/lemma/qid/span_len/resolved_by`). No other field in the OLD run's 1,147 pilot-subset pred records (full distribution: `exact_label` 369, `llm_disambiguation` 533, `judge_rejected` 110, `no_candidates` 133, `judge_unavailable` 2) distinguishes sitelink-sourced predictions either. This cannot be quantified from the trace fields actually present, as anticipated by the task — the retired `scripts/sitelink_contamination.py` replay (deleted, `docs/reports/python-pro-sitelink-clean-replay.md`) previously measured the sitelink rung at **~1% of grounded predictions**, contributing **≈0.6pp of full-corpus R_doc** (protocol-v2 M3 metric, all 100 articles, gemini config 111: 0.6902 → 0.6840 clean) — cited only as prior-work context for scale, not as a number reproduced here (different protocol, different corpus subset, machinery deleted).

### Comparison table

| Class | Run | gold_units | TP | FN | FP | R_doc | P_doc |
|---|---|---:|---:|---:|---:|---:|---:|
| named | OLD | 302 | 253 | 49 | 105 | 0.8377 [0.792, 0.875] | 0.7067 [0.658, 0.752] |
| named | NEW | 302 | 255 | 47 | 106 | 0.8444 [0.799, 0.881] | 0.7064 [0.657, 0.751] |
| named | **Δ (NEW−OLD)** | 0 | +2 | −2 | +1 | **+0.66pp** | **−0.03pp** |
| term | OLD | 77 | 30 | 47 | 39 | 0.3896 [0.288, 0.501] | 0.4348 [0.324, 0.552] |
| term | NEW | 77 | 32 | 45 | 62 | 0.4156 [0.312, 0.527] | 0.3404 [0.253, 0.441] |
| term | **Δ (NEW−OLD)** | 0 | +2 | −2 | +23 | **+2.60pp** | **−9.44pp** |
| **overall (pooled)** | OLD | 379 | 283 | 96 | 144 | 0.7467 | 0.6628 |
| **overall (pooled)** | NEW | 379 | 287 | 92 | 168 | 0.7573 | 0.6308 |
| **overall (pooled)** | **Δ** | 0 | +4 | −4 | +24 | **+1.05pp** | **−3.20pp** |

(`n_ambiguous_gold_units=15`, `n_gold_mentions_dropped_by_tier=50` — identical for both runs, since they share the same GT/tier input.)

### Reading it

- **Recall moves up slightly** on this 10-article subset (+0.66pp named, +2.60pp term, +1.05pp pooled) — directionally consistent with "v2 pipeline recovers a bit more," but every 95% Wilson CI above overlaps its counterpart heavily (e.g. term R_doc: OLD [28.8%, 50.1%] vs NEW [31.2%, 52.7%]). At n=10 articles / 77 term gold units, **none of these recall deltas are statistically distinguishable from noise.**
- **Term-class precision drops sharply** (43.5% → 34.0%, −9.44pp), driven by FP rising from 39 to 62 while TP only rose by 2. Named-class precision is flat. This is the one delta large enough to be worth a flag rather than dismissing as noise — see Critical findings below.
- **Record volume differs too**: OLD run's 10-title subset has 1,147 pred records vs NEW's 1,203 (both runs extract+ground independently; the NEW run also grounds more term-class FPs specifically, not just more records overall).

**Reproducibility:** `PYTHONPATH=src uv run --no-sync python3 <scratchpad>/task1_subset_compare.py` — full JSON written to `<scratchpad>/task1_output.json`.

---

## TASK 2 — FN decomposition (extraction coverage × grounding success)

For every gold `(article, QID)` unit missed by a run, gold anchor surfaces for that QID/article are collected from `gt_tuples`, then every pred.jsonl record for that article (including `qid=null` ones) is checked for a normalized surface/lemma match (casefold + ё→е + dash-fold via `grounding.match.norm`). "Never extracted" = no matching record at all. "Extracted, grounding failed" = at least one matching record exists, sub-split by that mention's own outcome.

### NEW pilot (v2, `--no-sitelink`) — 92 FN units total

| Class | Bucket | n | share |
|---|---|---:|---:|
| named (n_fn=47) | extracted: judge chose a DIFFERENT qid | 20 | 42.6% |
| named | never_extracted | 14 | 29.8% |
| named | extracted: exact_label to a different qid | 5 | 10.6% |
| named | extracted: judge_rejected (no qid) | 4 | 8.5% |
| named | extracted: no_candidates (no qid) | 4 | 8.5% |
| term (n_fn=45) | never_extracted | 33 | 73.3% |
| term | extracted: judge chose a DIFFERENT qid | 4 | 8.9% |
| term | extracted: judge_rejected (no qid) | 3 | 6.7% |
| term | extracted: exact_label to a different qid | 3 | 6.7% |
| term | extracted: no_candidates (no qid) | 2 | 4.4% |

### OLD run (pre-redo, sitelink-on), same 10 articles — 96 FN units total

| Class | Bucket | n | share |
|---|---|---:|---:|
| named (n_fn=49) | extracted: judge chose a DIFFERENT qid | 19 | 38.8% |
| named | never_extracted | 17 | 34.7% |
| named | extracted: judge_rejected (no qid) | 5 | 10.2% |
| named | extracted: exact_label to a different qid | 5 | 10.2% |
| named | extracted: no_candidates (no qid) | 2 | 4.1% |
| named | extracted: judge_unavailable (no qid) | 1 | 2.0% |
| term (n_fn=47) | never_extracted | 33 | 70.2% |
| term | extracted: judge chose a DIFFERENT qid | 5 | 10.6% |
| term | extracted: judge_rejected (no qid) | 4 | 8.5% |
| term | extracted: exact_label to a different qid | 3 | 6.4% |
| term | extracted: no_candidates (no qid) | 2 | 4.3% |

### Reading it

- **The dominant recall bottleneck differs sharply by class, and this pattern is stable across both runs**: for **named** entities, ~60% of misses are extraction successes that fail at grounding (mostly the judge picking the wrong QID among plausible candidates); for **term** (common-noun) misses, ~70-73% are never extracted at all — extraction coverage, not grounding, is the term-class bottleneck.
- The two runs' bucket shares are close (e.g. named "judge chose a different qid": 38.8% old vs 42.6% new; term "never_extracted": 70.2% old vs 73.3% new) — the v2 rework did not qualitatively change *where* recall is lost, consistent with Task 1's small, CI-overlapping deltas.
- "Judge chose a DIFFERENT qid" is the single largest identifiable failure mode for named entities in both runs (19-20 units, ~39-43% of named FN) — a disambiguation-quality problem, not a coverage problem, and the best-leverage target if grounding recall is to be improved further.

**Reproducibility:** `PYTHONPATH=src uv run --no-sync python3 <scratchpad>/task2_fn_decomposition.py` — full per-unit detail (including which pred record matched and why) written to `<scratchpad>/task2_output.json`.

---

## TASK 3 — judge-escalation profile (NEW pilot)

From all 1,203 NEW pilot pred.jsonl records (`resolved_by` distribution over every mention that went through grounding, not only grounded ones):

| resolved_by | n | share of all mentions |
|---|---:|---:|
| llm_disambiguation | 573 | 47.6% |
| exact_label | 373 | 31.0% |
| no_candidates | 162 | 13.5% |
| judge_rejected | 95 | 7.9% |

- **Grounded** (`qid` truthy = `exact_label` + `llm_disambiguation`) = 946/1203 = **78.6%**.
- **Judge escalations** (`resolved_by` ∈ {`llm_disambiguation`, `judge_rejected`, `judge_unavailable`} — per `label_first.py`'s decision table, escalation happens whenever ≥2 exact matches or candidates-present-with-0-exact) = 668/1203 = **55.5%** of all mentions, split 573 llm_disambiguation (85.8% of escalations) / 95 judge_rejected (14.2%) / 0 judge_unavailable.

### "Share of judge escalations with exactly 1 candidate" — NOT computable from pred.jsonl

Checked and confirmed by reading source, not assumed: `GroundingResult.trace` does carry a full `candidates` list per mention (`grounding/label_first.py:286-300`), but `evaluation/predict.py:78-93` (`predict_tuples`) reads only `(result.trace or {}).get("resolved_by")` out of that trace before writing each pred.jsonl record — the candidate list itself is discarded and never reaches pred.jsonl. `calls.jsonl` (the per-call `CallLogger`, spec Р8) logs only call metadata (tokens, cost, latency, `content_len`) — not judge prompt/candidate content either. No file in this run's directory (`calls.jsonl`, `progress.jsonl`, `gate_check_result.json`, `meta.json`) carries a per-mention candidate count. Computing it would require either a live re-run with an added persisted field, or replaying `generate_candidates()` against the run's Wikidata state — the same category of machinery as the retired `sitelink_contamination.py`, explicitly out of scope per the task instruction not to replay deleted machinery. **Reported as not done rather than estimated.**

**Reproducibility:** `PYTHONPATH=src uv run --no-sync python3 <scratchpad>/task3_escalation_profile.py` — output written to `<scratchpad>/task3_output.json`.

---

## NOT done / known gaps

1. Sitelink-rung contribution on this specific 10-article subset/protocol — not quantifiable from pred.jsonl trace fields (Task 1 caveat); only a differently-scoped prior estimate (~1% of grounded, ~0.6pp full-corpus R_doc, protocol-v2/100-article) is available as context.
2. "Judge escalations with exactly 1 candidate" (Task 3) — not computable from any file in the NEW run's output directory; candidate-list is dropped before persistence by design (`predict.py`).
3. No statistical-significance test beyond the per-cell Wilson CIs already in `aggregate_corpus_v3`'s output was run (e.g. no paired McNemar test across the matched 10-article set) — the CIs already shown are wide enough that this would not change the "not distinguishable from noise" conclusion for recall, but it was not formally run.
4. Because the OLD and NEW runs differ in the full v2 pipeline (prompts, transport, sampling), not only `--no-sitelink`, Task 1's deltas cannot be attributed to the sitelink toggle specifically — flagged above, not re-derived with an isolated ablation (would require a live re-run).

---

## Executive summary (5 lines)

1. On the matched 10-article pilot subset, v2-pipeline recall is marginally higher than the pre-redo pipeline (pooled R_doc 74.7% → 75.7%, +1.05pp) but every per-class Wilson CI overlaps heavily — not statistically distinguishable at this sample size.
2. Precision drops materially for term-class predictions (43.5% → 34.0%, −9.44pp) driven by FP rising 39→62; named-class precision is flat (70.7% → 70.6%) — this is the one delta worth flagging, not dismissing as noise.
3. FN decomposition is stable across both runs and reveals two distinct bottlenecks: named-entity misses are dominated by grounding failures (~39-43% "judge chose a different QID"), while term misses are dominated by extraction coverage (~70-73% "never extracted").
4. The OLD-vs-NEW comparison is not an isolated sitelink ablation — the whole v2 pipeline (prompts, transport, sampling) changed simultaneously — and the sitelink rung's own contribution cannot be quantified from pred.jsonl trace fields on either run.
5. Two requested sub-metrics were genuinely not computable from the available artifacts and are reported as such rather than estimated: per-record sitelink attribution, and the share of judge escalations with exactly 1 candidate (both require data never persisted to pred.jsonl/calls.jsonl).
