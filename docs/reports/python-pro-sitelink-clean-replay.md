# Report — sitelink-clean replay extended to all metrics (paper Table C)

## Scope

Extend the committed sitelink-circularity replay so Table C can cite sitelink-clean
values for R_span (M2), R_strict (M1), and precision (P_mention/P_type), not only
R_doc (M3), for `gemini-3.1-flash-lite` and `deepseek-v4-flash` (config `111`). Pure
cache replay only — no LLM calls, no live network beyond what the run's own committed
Wikidata cache already answers.

## Files changed

- [scripts/sitelink_contamination.py](../../scripts/sitelink_contamination.py) — extended
  `run()` to build `metrics.ArticleTuples` per article (adding `resolved_by_of`/
  `stratum_of`/`type_of`, previously unused by this script) and call
  `metrics.aggregate_corpus()` on both the full and sitelink-clean prediction sets. This
  reuses the *exact* micro-average recall/precision/Wilson-CI code path
  `scripts/wiki_eval.py cmd_report` uses to build each run's own `metrics.json`, rather
  than hand-rolling a second matcher. Added: `recall_full`/`recall_clean` (m1/m2/m3, each
  with CI), `precision_full`/`precision_clean` (p1/p2, each with CI), a `p_label_p3ex`
  diagnostic (see Decisions below), and a `wikidata_network_calls_made` counter with a
  hard `run(..., allow_network=False)` guard that now **raises** rather than silently
  mixing cached and live data on any cache miss (new `--allow-network` CLI flag to
  override). Old top-level keys (`R_doc_full`, `R_doc_clean`, `R_doc_delta`,
  `recall_units_lost`, `unique_forms_replayed`, `source_counts`, …) are unchanged in
  shape and value — purely additive.
- [scripts/sitelink_clean_full_metrics.py](../../scripts/sitelink_clean_full_metrics.py)
  (new, sibling) — thin driver with no matching/CI logic of its own: calls the extended
  `run()` for both finished model-comparison runs against their own already-warm
  per-model caches under `drafts/sitelink_replay/`, and writes the combined JSON.
- [docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json](../experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json)
  (new) — the run output, one entry per model.
- This report.
- [docs/reports/python-pro-ner-wikidata-table-c-extraction.md](python-pro-ner-wikidata-table-c-extraction.md)
  committed as-is at the owner's instruction (the prior extraction report this one
  extends; not authored by this task, not modified).

**Not touched**, per task scope: `reports/bouquet/`, any
`reports/terminology/wiki-eval/anthropic--claude-opus-4.8*` path, or any other file
already modified/untracked by a concurrent agent in this worktree
(`configs/bouquet_judges.yaml`, `docs/stages/wiki-eval.md`, `reports/bouquet/judges/summary.md`,
`scripts/bouquet_judge_rerun.py`, `scripts/wiki_eval.py`,
`docs/reports/ml-engineer-grounding-run-opus48.md`, and three new
`reports/bouquet/judges/*/` dirs) — confirmed via `git status` before staging and
`git add` scoped to only this task's five files.

## Decisions & rationale

- **Identified the correct "committed replay script".** Two similarly-named scripts
  exist: `scripts/sitelink_contamination.py` (argparse CLI, `WikidataClient` +
  `generate_candidates` live-replay against an on-disk cache) and
  `scripts/replay_sitelink_contamination.py` (hand-rolled ladder replication, imports a
  `build_cache_index` helper from a **different, no-longer-existent session's**
  `/tmp` scratchpad path, and reads `reports/terminology/wikidata_cache.<model>.jsonl`
  caches that were never committed — dead code in this checkout). Confirmed which one is
  canonical via `docs/stages/wiki-eval.md`'s own citation ("`scripts/sitelink_contamination.py`
  … gives clean R_doc 0.684 (gemini) / 0.609 (deepseek)") and by matching its
  `--cache`-default naming convention (`.wikidata_cache.<model-slug>.jsonl`) against the
  already-committed cache files under `drafts/sitelink_replay/` — exact match. Extended
  `sitelink_contamination.py`; left `replay_sitelink_contamination.py` untouched (out of
  scope, and not safe to guess at fixing blind).
- **Reused `metrics.aggregate_corpus` instead of hand-rolling M1/M2/precision matching.**
  The pre-extension script only called `matching.match_m3` directly. Extending it to also
  cover M1/M2/P1/P2 by hand would duplicate logic `metrics.py` already implements
  correctly (Wilson CI, micro-average across articles, precision dedup). Building
  `ArticleTuples` dicts (`resolved_by_of`, `stratum_of`, `type_of` per article, mirroring
  `scripts/wiki_eval.py::cmd_report`'s same-named helpers) and calling
  `aggregate_corpus()` on the full and clean prediction sets gives every new metric with
  CI in one call, and — as a bonus — makes the *full* (non-clean) numbers this script now
  produces an exact-match sanity check against each run's own committed `metrics.json`
  (see Run artifacts).
- **P_label (P3\exact) is explicitly NOT computed — stopped and reported per task
  instruction, not silently approximated.** `P_label` = `metrics.py`'s `p3_ex`, which
  needs `label_exists(surface)` — a live `wbsearchentities(surface, lang="ru", limit=1)`
  call per unmatched, non-`exact_label` prediction surface
  (`scripts/wiki_eval.py::_label_exists_fn`). This is a **different cache-key shape**
  (`limit=1`) than the `limit=7` candidate-generation ladder this script replays; I
  grepped every committed `.jsonl`/`.json` in the repo for a `limit=1` `wbsearchentities`
  key and found none — this genuinely cannot be answered from any cache in the repo. I
  quantified the gap precisely instead of guessing: reused the real
  `metrics._precision_counts_p3_ex` accounting with a call-counting stub (not a real
  `label_exists`) to get an **exact** count of unique surfaces that would need a live
  call — 2,419 (gemini) / 1,991 (deepseek). That is squarely inside "thousands of calls"
  territory against a rate-limited public API (`maxlag`/429 backoff already present in
  `WikidataClient`), so per the task's explicit stop condition I did not make them. The
  diagnostic is preserved in the output JSON (`p_label_p3ex.status = "not_computed"` +
  the exact count) so a future run can decide whether to spend that budget.
- **Added a hard zero-network-calls assertion, not just a manual check.**
  `WikidataClient.n_network_calls` already existed (cache-hit vs. live-call counter,
  unused by the pre-extension script). `run()` now checks it right after the replay and
  raises `RuntimeError` on any nonzero count unless `allow_network=True` is passed
  explicitly — so "pure cache replay" is enforced by the script itself on every future
  invocation, not just true by inspection this one time.
- **Did not touch `gemini.json`/`deepseek.json` under `drafts/sitelink_replay/`.** The
  task named one new output path
  (`docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json`); I
  wrote only there. The two pre-existing per-model files (R_doc-only, already cited by
  `docs/stages/wiki-eval.md` and the prior extraction report) are unmodified — re-running
  `sitelink_contamination.py --out` against those exact paths would now also embed the
  new keys (the format is additive-compatible), but I did not re-run against those paths,
  to avoid touching files outside the requested scope.

## Open questions

- Should `drafts/sitelink_replay/{gemini,deepseek}.json` eventually be *regenerated*
  (same `--out` path, now via the extended script) so they carry the richer metrics too,
  superseding the new side-by-side `sitelink-clean-full-metrics.json`? Left to the
  paper-integration owner — not done here since the task named a distinct new output
  path and I did not want to overwrite artifacts other docs already cite by their current
  (R_doc-only) shape.
- Is spending ~2,400 + ~2,000 live, rate-limited Wikidata calls to fill in P_label
  acceptable for the paper's timeline? If yes, `sitelink_contamination.py` already has
  everything needed (`_label_exists_fn`-equivalent wiring would need porting from
  `scripts/wiki_eval.py`, plus `--allow-network` or a dedicated `--p3` opt-in) — not
  built here since it was explicitly out of scope ("stop and report").
- `docs/stages/wiki-eval.md` has uncommitted changes from a concurrent agent in this same
  worktree at the time of this task; I did not add a doc-parity pointer to the new
  full-metrics JSON there to avoid clobbering that in-flight edit. Worth a follow-up once
  that lands.

## NOT done

- **P_label / P3\exact clean values** — not computed (network-call budget, see Decisions).
  Reported as an exact "calls needed" diagnostic instead of a number.
- **R_all/R_term tier filtering for the new metrics** — the task only asked for
  full-corpus (all 7,959 GT tuples) R_span/R_strict/precision; tier-filtered clean
  variants (as exist for R_doc in the prior extraction report, sourced from a
  non-reproducible scratch run of a different, now-broken script) were not requested and
  not built here.
- **`drafts/sitelink_replay/{gemini,deepseek}.json` regeneration** — left untouched, see
  Decisions.
- Did not attempt to fix or resurrect `scripts/replay_sitelink_contamination.py` (the
  dead-code sibling with the stale `/tmp` import) — out of scope, not asked for.

## Extended replay results — clean vs original, all metrics (2026-07-09)

Both runs: `use_sitelink=False` clean replay via the same run's own committed candidate
cache (`docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay/.wikidata_cache.*.jsonl`),
**zero live Wikidata calls** (`wikidata_network_calls_made: 0` for both — confirmed in
the output JSON, not just asserted).

### Anchor reproduction (exact)

| Model | Target R_doc clean | Got | Match |
|---|---|---|---|
| gemini-3.1-flash-lite | 0.684 (5444/7959) | 0.684006 (5444/7959) | ✅ exact |
| deepseek-v4-flash | 0.609 (4849/7959) | 0.609247 (4849/7959) | ✅ exact |

### Internal sanity check — FULL (non-clean) numbers vs. each run's own `metrics.json`

Every one of these is an exact `matched`/`total` match (not just "close"):

| Model | Cell | This script | metrics.json |
|---|---|---|---|
| gemini | recall m1/m2/m3 | 4852/7959, 5011/7959, 5493/7959 | same |
| gemini | precision p1/p2 | 5014/16709, 4219/9349 | same |
| deepseek | recall m1/m2/m3 | 4053/7959, 4167/7959, 4890/7959 | same |
| deepseek | precision p1/p2 | 4170/13680, 3600/7854 | same |

This confirms the `aggregate_corpus`-based extension reproduces the harness's own
methodology exactly, before any sitelink filtering is applied.

### Clean (sitelink-off) headline table

**gemini-3.1-flash-lite**

| Metric | Clean value | 95% CI | matched/total | Original (full) | Drift |
|---|---|---|---|---|---|
| R_strict (M1) | 0.6023 | [0.5915–0.6130] | 4794/7959 | 0.6096 | −0.73pp |
| R_span (M2) | 0.6222 | [0.6115–0.6328] | 4952/7959 | 0.6296 | −0.74pp |
| R_doc (M3) | 0.6840 | [0.6737–0.6941] | 5444/7959 | 0.6902 | −0.62pp |
| P_mention (P1) | 0.3002 | [0.2933–0.3073] | 4955/16505 | 0.3001 | +0.01pp |
| P_type (P2) | 0.4523 | [0.4421–0.4624] | 4163/9205 | 0.4513 | +0.10pp |
| P_label (P3\exact) | **not computed** — 2,419 live calls needed, none made | — | — | 0.5256 | n/a |

**deepseek-v4-flash**

| Metric | Clean value | 95% CI | matched/total | Original (full) | Drift |
|---|---|---|---|---|---|
| R_strict (M1) | 0.5043 | [0.4934–0.5153] | 4014/7959 | 0.5092 | −0.49pp |
| R_span (M2) | 0.5187 | [0.5077–0.5296] | 4128/7959 | 0.5236 | −0.49pp |
| R_doc (M3) | 0.6092 | [0.5985–0.6199] | 4849/7959 | 0.6144 | −0.52pp |
| P_mention (P1) | 0.3051 | [0.2974–0.3130] | 4131/13538 | 0.3048 | +0.03pp |
| P_type (P2) | 0.4599 | [0.4488–0.4710] | 3561/7743 | 0.4584 | +0.15pp |
| P_label (P3\exact) | **not computed** — 1,991 live calls needed, none made | — | — | 0.5302 | n/a |

### Sanity checks

- Monotonicity `R_strict ≤ R_span ≤ R_doc` on the clean set: gemini
  0.6023 ≤ 0.6222 ≤ 0.6840 ✅; deepseek 0.5043 ≤ 0.5187 ≤ 0.6092 ✅.
- Drift bound (task: "expected drift ≤ ~1pp"): all 8 span/strict/precision cells land
  between −0.74pp and +0.15pp — well inside bound. Recall drift is consistently negative
  (sitelink removal costs recall, as expected); precision drift is consistently small and
  slightly positive (removing a below-average-precision rung nudges precision up
  marginally) — directionally sensible, not just in-bound by luck.
- All figures above independently re-derived and cross-checked via a standalone script
  (not just eyeballed from the JSON) — see "ran" below.

### Ran / didn't run

**Ran:**
- `PYTHONPATH=src uv run python scripts/sitelink_clean_full_metrics.py` — full replay for
  both models, wrote the combined JSON. `wikidata_network_calls_made: 0` for both.
- A standalone verification script (post-hoc, not committed) that: (a) diffed
  `recall_full`/`precision_full` against each run's own committed `metrics.json` —
  exact match on every cell; (b) checked the two R_doc anchors to the exact
  matched/total counts given in the task; (c) checked monotonicity; (d) computed and
  bound-checked all 8 full→clean drift deltas. Output: `ALL CHECKS PASSED`.
- `uv run pytest tests/test_wiki_matching.py tests/test_wiki_metrics.py -q` — 13 + 21
  passed, confirming the reused `matching.py`/`metrics.py` code this script now depends
  on more heavily is itself still green.
- `uv run ruff check scripts/sitelink_contamination.py scripts/sitelink_clean_full_metrics.py`
  — the new sibling script is fully clean; the extended script has 3 pre-existing E501s
  (verified via `git stash` — present in the file before this task's edits) and zero new
  ones (the one line my edit added over 100 chars was reformatted to comply).

**Did not run:**
- Any live Wikidata network call (P_label) — by design, see Decisions/NOT done.
- A full repo-wide test/lint pass — out of scope for a targeted script extension; ran the
  directly-relevant test files and linted only the files this task touched.

## Commit

`feat(eval): sitelink-clean replay for span/strict/precision metrics` — hash filled in
after commit (see chat reply).
