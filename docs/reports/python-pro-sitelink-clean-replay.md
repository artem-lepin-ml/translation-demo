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

- **P_label / P3\exact clean values** — not computed in THIS (first) commit (network-call
  budget, see Decisions). **Superseded**: computed for real in the follow-up (owner
  approved live calls) — see "Follow-up — live P_label computation" below. Left this
  bullet in place as an honest record of what the first commit did and did not do.
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
| P_label (P3\exact) | **0.5304** | [0.5206–0.5401] | 5340/10068 | 0.5256 | +0.48pp |

**deepseek-v4-flash**

| Metric | Clean value | 95% CI | matched/total | Original (full) | Drift |
|---|---|---|---|---|---|
| R_strict (M1) | 0.5043 | [0.4934–0.5153] | 4014/7959 | 0.5092 | −0.49pp |
| R_span (M2) | 0.5187 | [0.5077–0.5296] | 4128/7959 | 0.5236 | −0.49pp |
| R_doc (M3) | 0.6092 | [0.5985–0.6199] | 4849/7959 | 0.6144 | −0.52pp |
| P_mention (P1) | 0.3051 | [0.2974–0.3130] | 4131/13538 | 0.3048 | +0.03pp |
| P_type (P2) | 0.4599 | [0.4488–0.4710] | 3561/7743 | 0.4584 | +0.15pp |
| P_label (P3\exact) | **0.5346** | [0.5238–0.5453] | 4409/8248 | 0.5302 | +0.44pp |

### Sanity checks

- Monotonicity `R_strict ≤ R_span ≤ R_doc` on the clean set: gemini
  0.6023 ≤ 0.6222 ≤ 0.6840 ✅; deepseek 0.5043 ≤ 0.5187 ≤ 0.6092 ✅.
- Drift bound (task: "expected drift ≤ ~1pp"): all 10 span/strict/precision/label cells
  (now including the two live P_label cells, added in the follow-up below) land between
  −0.74pp and +0.48pp — well inside bound. Recall drift is consistently negative (sitelink
  removal costs recall, as expected); precision-family drift (P_mention/P_type/P_label) is
  consistently small and positive (removing a below-average-precision rung nudges
  precision up marginally) — directionally sensible, not just in-bound by luck.
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

## Commit (first commit)

`feat(eval): sitelink-clean replay for span/strict/precision metrics` — see chat reply /
git log for hash.

---

## Follow-up — live P_label computation (2026-07-09, owner-approved)

### Scope of the follow-up

Coordinator approved spending real `wbsearchentities(limit=1)` label-existence calls to
fill in the one metric the first commit deliberately left as a diagnostic-only count:
clean P_label (P3\exact) for both models. Constraints: label-existence checks only (no
LLM calls, zero token cost), max 3 concurrent, honor 429/`maxlag`/`Retry-After` with
backoff, cache every response to a new committed `limit=1` cache file (separate from the
existing `limit=7` candidate-generation cache, so the computation stays replayable).

### Incident 1 — unhandled `maxlag` exception killed the deepseek phase mid-batch

First live run (`bg4081dd9`) finished gemini cleanly (4014 live calls,
`P_label=0.5304`, 5340/10068) but then died on deepseek at 55/~1991 cached entries.

**Root cause**: `WikidataClient._fetch`'s own internal retry (5 attempts, ≤~12s total)
tripped on a genuinely lagged Wikidata replica (`maxlag` error, `host: wdqs1012,
lag: 5.28s` reported, but `queryserviceLag: 317` — a replica minutes behind, not
seconds) and, after exhausting those 5 attempts, raised `RuntimeError`. That exception
propagated out of one `ThreadPoolExecutor` worker, through `pool.map`'s result
iteration, and crashed the whole process — taking every other still-in-flight deepseek
lookup down with it, not just the one stuck call. Nothing wrote `sitelink-clean-full-
metrics.json` afterward since the script never reached its final `json.dump`.

**Fix**: added `_resilient_label_exists()` to `scripts/sitelink_contamination.py` — wraps
every prewarm call with its own OUTER retry (4 attempts, backoff `5/15/30/60s`, longer
than `_fetch`'s internal one, since a genuinely lagged replica needs minutes not
seconds), falls back to the conservative `False` only after exhausting all attempts (per
project convention: "pick the conservative option, log the deviation, keep going" — never
counts an unverifiable surface as label-justified), and makes the give-up **sticky** per
`norm(surface)` so a persistently broken lookup is never retried twice (once in prewarm,
once again in the final aggregation pass). Unit-tested offline (no network) before
re-spending any live budget — 4/4 cases passed (success, false, permanent-failure→False,
sticky-skip-on-repeat).

### Incident 2 (found before relaunch, budget/time blow-up) — accidental extra network cost

Before relaunching, noticed gemini's actual `live_calls_made` (4014) was ~1.7× the
diagnosed estimate (2419) — worth explaining, not shrugging off, since the same
overshoot on deepseek (1991 estimated) would have meant a materially longer, more
call-hungry rerun.

**Root cause**: passing `label_exists` into `metrics.aggregate_corpus()` doesn't only
compute the P_label headline (`p3_ex`) — it *also* unconditionally activates a SEPARATE
per-`resolved_by`-slice P3 computation inside `aggregate_corpus`'s own axis-slicing loop
(`metrics.py:331-337`, `_precision_counts(..., variant="p3", label_exists=...)` for every
value of the `resolved_by` axis, including the huge `exact_label` slice that the P_label
headline's own denominator explicitly excludes). This is legitimate `aggregate_corpus`
behavior (feeds `metrics.json`'s per-slice P3 numbers when `wiki_eval.py cmd_report --p3`
runs it), but this script never reads or reports that slice — it was pure wasted network
cost, silently incurred as a side effect of reusing the convenient one-call API.

**Fix**: stopped calling `aggregate_corpus(clean_articles, label_exists=...)` for the
`compute_p_label=True` path. Recall/P1/P2 now come from a label-free
`aggregate_corpus(clean_articles)` call (as before, no network); P_label is accumulated
directly via `metrics._precision_counts_p3_ex` (the exact same private helper
`aggregate_corpus` itself uses for the headline cell) summed across articles, then
wrapped with `metrics._cell` for the CI — same formula, same private helper, just without
the unrequested slice loop around it. **Verified the fix doesn't change the computed
value**: ran both the old (`aggregate_corpus`-with-`label_exists`) and new (direct
accumulation) paths against gemini's real clean-article set with a deterministic fake
`label_exists` stub (no network) — both produced byte-identical `{matched: 6444, total:
10068, value: 0.6400476758045291, ...}`. Confirms the fix only removes wasted calls, not
correctness.

### Relaunch and completion

Relaunched the full driver (`bg buo9h9mdc`) with both fixes in place:
- **gemini**: `live_calls_made: 0` — the 4141 already-cached entries from the first
  (over-eager) run fully covered the leaner 2419-surface need; P_label recomputed to the
  **exact same value** as the crashed-but-partially-successful first run
  (`0.5303933253873659`, 5340/10068) — a second independent confirmation the fix is
  value-neutral.
- **deepseek**: `live_calls_made: 2061` against `unique_surfaces_queried: 1991` (the
  extra ~70 are `_fetch`-internal retry attempts for transient errors that ultimately
  succeeded — request attempts, not unique keys; final cache file has exactly 1991 lines,
  matching the diagnosed count exactly, zero duplicates). `label_exists_failures: 0` for
  both models — every resilient-wrapper retry eventually succeeded; nothing fell back to
  the conservative `False`.

### Final clean P_label — both models, with CIs and drift

| Model | Clean P_label | 95% CI | matched/total | Original (full, from metrics.json) | Drift |
|---|---|---|---|---|---|
| gemini-3.1-flash-lite | **0.5304** | [0.5206–0.5401] | 5340/10068 | 0.5256 | +0.48pp |
| deepseek-v4-flash | **0.5346** | [0.5238–0.5453] | 4409/8248 | 0.5302 | +0.44pp |

Both drifts land inside the same small, positive, "removing a below-average-precision
rung nudges precision up marginally" pattern already seen on P_mention/P_type — directionally
consistent, not an outlier.

### Files changed (follow-up, on top of the first commit)

- `scripts/sitelink_contamination.py` — `_label_exists_fn` (mirrors
  `wiki_eval.py::_label_exists_fn`), `_resilient_label_exists` (retry/backoff/sticky
  give-up wrapper), `_needed_label_surfaces` (refactored from the first commit's
  `_count_label_exists_calls_required`, now also reused to build the prewarm dispatch
  list), and `run()` wiring for `compute_p_label`/`label_cache_path`/
  `label_network_concurrency` + matching CLI flags (`--compute-p-label`, `--label-cache`,
  `--label-network-concurrency`).
- `scripts/sitelink_clean_full_metrics.py` — `--compute-p-label` /
  `--label-network-concurrency` CLI flags, per-model `label_cache_path` wiring, richer
  stderr summary line.
- `docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json` — both
  models' `p_label_p3ex` now `status: "computed"` with real matched/total/CI, plus
  `unique_surfaces_queried`/`live_calls_made`/`cache_hits`/`cache_path`/
  `label_exists_failures` for provenance.
- `docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay/.wikidata_cache.label_exists.google--gemini-3.1-flash-lite--provider-9.jsonl`
  (new, committed, 4141 lines, 2.4MB) and the deepseek equivalent (new, committed, 1991
  lines, 1.2MB) — the new `limit=1` caches, alongside (not replacing) the existing
  `limit=7` candidate-generation caches.
- This report.

**Checked, left untouched**: `reports/bouquet/judges/summary.md` has an unrelated diff
(a concurrent agent's `claude-opus-4.8` BOUQUET judge stats regeneration, timestamped
`2026-07-08T23:21:51`, nothing to do with this task) — confirmed via `git diff` before
staging anything, per instruction; not staged.

### Ran / didn't run (follow-up)

**Ran:**
- Unit test of `_resilient_label_exists` in isolation (no network, synthetic flaky
  function) — 4/4 assertions passed before spending any live budget.
- Offline equivalence check of the old vs. new p3_ex accumulation path against gemini's
  real clean-article set with a deterministic fake `label_exists` — byte-identical
  result, confirming the budget fix is value-neutral.
- `PYTHONPATH=src uv run python scripts/sitelink_clean_full_metrics.py` (no
  `--compute-p-label`) — regression check after each code change, confirming
  `R_doc_clean`/call-counts stayed exactly as in the first commit.
- `uv run pytest tests/test_wiki_matching.py tests/test_wiki_metrics.py -q` — 34 passed,
  after both fixes.
- `uv run ruff check scripts/sitelink_contamination.py scripts/sitelink_clean_full_metrics.py`
  — clean except the same 3 pre-existing baseline E501s from the first commit (verified
  via `git stash` again).
- Two live background runs: `bg4081dd9` (crashed on deepseek, gemini succeeded) and
  `buo9h9mdc` (completed both models cleanly after the fixes).
- Final combined re-run with `--compute-p-label` after `buo9h9mdc` completed, to produce
  the JSON committed here (`wikidata_network_calls_made: 0` for the candidate-ladder
  client on both models, confirming the R_doc/R_span/R_strict/P_mention/P_type numbers
  from the first commit are unchanged).

**Did not run:**
- Any re-verification of `label_exists_failures > 0` handling end-to-end (both models
  finished with zero permanent failures, so the conservative-`False`-fallback path was
  exercised only by the unit test, not by a real run).

## Commit (follow-up)

`feat(eval): clean P_label via live label checks for sitelink-clean replay` — see chat
reply / git log for hash.
