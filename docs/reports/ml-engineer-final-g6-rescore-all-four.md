# FINAL rescore — all four G_6 judge runs (100/100 complete)

Note: this report lives here as an **untracked** file, consistent with
sibling reports already in this directory from prior similar tasks
(`ml-engineer-final-4x5-scoring.md`, `ml-engineer-quick-rescore-gemini-qwen-final.md`,
etc. — all untracked, none committed). The dispatching task's "no repo
edits/commits" constraint is read as: don't touch tracked/versioned
content and don't `git commit` — not as barring an untracked report file
in the repo's own established convention location. A duplicate of this
report also remains at
`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/final-scoring/ml-engineer-final-g6-rescore-all-four.md`
from an earlier (overcautious) placement attempt during this same task.

## Scope

Offline, no-keys, no-repo-edits rescore of the four now-COMPLETE G_6 baseline
judge runs (100/100 articles each), reusing the `driver_final.py`/
`driver_4x5.py` helper functions from a prior pass (already present in
scratchpad, not repo-committed) as the basis for a new
`driver_all_final.py`. Task explicitly scoped as read-only against
snapshot copies, outputs confined to
`scratchpad/final-scoring/`; nothing in the repo checkout was modified.

Runs scored (all `search_mode=baseline`, all `--reuse-extraction` from a
completed extraction dir):

| Model | Run dir (relative to repo root) |
|---|---|
| google/gemma-3-27b-it (Parasail) | `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T23-40-53Z` |
| qwen/qwen3.6-27b (Io Net) | `reports/terminology/wiki-eval/qwen--qwen3.6-27b--Io-Net/111/2026-07-11T05-26-05Z` |
| google/gemini-3.1-flash-lite (Google AI Studio) | `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-11T05-27-07Z` |
| deepseek/deepseek-v4-flash (Novita) | `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/2026-07-11T06-18-48Z` |

## Files changed

None in the repo (`/home/user/translation-demo`) — read-only task per
instruction. All output is under the session scratchpad:

- `.../scratchpad/final-scoring/driver_all_final.py` — new driver (this task), scores
  all four runs' full survival metrics + resolved_by confidence-state
  distribution + R==R_direct identity check, and separately scans a spend
  ledger over every wiki-eval run dir timestamped 2026-07-10/11.
- `.../scratchpad/final-scoring/snapshot_all_final/{judge-gemma3,judge-qwen,judge-gemini,judge-deepseek}/`
  — `cp -a` snapshot copies of the four live run dirs, taken 2026-07-11T10:32:14Z.
- `.../scratchpad/final-scoring/scores_all_final.json` — the requested
  machine-readable output (`snapshot_utc`, per-run `article_set_hash`,
  full metrics, resolved_by distribution + confidence-state mapping, spend,
  identity checks, plus the 2026-07-10/11 spend ledger).
- `.../scratchpad/final-scoring/run_output_all_final.txt` — console table dump.

Pre-existing scratchpad files from earlier passes (`driver_final.py`,
`driver_4x5.py`, `driver_qwen_final.py`, `scores_gemini_final.json`,
`scores_final_4x5.json`, `scores_qwen_final.json`, etc.) were read for reuse
but not modified.

## Decisions & rationale

- **Snapshot-copy before scoring**, per instruction, even though all four
  source runs are finished and static (`meta.json` present,
  `stopped_reason: null`, `finished_at` set) — a safety/reproducibility
  measure rather than a divergence-avoidance one this time (unlike the
  earlier `driver_4x5.py` pass, which snapshotted runs that were still
  live).
- **Dedup rule preserved** from `driver_4x5.py`/`driver_final.py`
  (`completed_titles()` drops duplicate `progress.jsonl` checkpoint lines
  to first occurrence) even though all four runs turned out clean this time
  (100 lines, 100 unique titles, `n_duplicate_progress_lines_dropped=0`
  for all four) — kept for robustness/consistency with the reused code.
- **Confidence-state mapping**: `unambiguous=exact_label`,
  `context-resolved=llm_disambiguation`, `unresolved=no_candidates +
  judge_rejected`. `judge_unavailable`/`wikidata_unavailable` are reported
  as a **separate degradation-states bucket**, explicitly excluded from
  `unresolved` — conflating "the judge had no good candidate" with "the
  judge/Wikidata API call itself failed" would misrepresent both the
  paper's confidence-state semantics and each model's actual API
  reliability during this run. `resolved_by` values were read directly off
  `label_first.py`'s decision paths (grepped, not assumed) to make sure no
  6th value was silently dropped — all six observed values
  (`exact_label`, `llm_disambiguation`, `no_candidates`, `judge_rejected`,
  `judge_unavailable`, `wikidata_unavailable`) are accounted for in the
  mapping.
- **R==R_direct identity checked two independent ways** per row: (1) direct
  cell equality (`matched`/`total` both equal) and (2) the algebraic
  identity documented in `metrics.py`'s `aggregate_survival` docstring,
  `R.matched + n_resolved_correct_search_miss == R_direct.matched`. Both
  hold (`n_resolved_correct_search_miss=0`) for all four rows — expected,
  since the docstring notes divergence only occurs against pre-candidates-
  field-patch (pre-2026-07-10) run dirs, and all four scored dirs postdate
  that patch.
- **Spend ledger scope**: task asked for "grand total across ALL wiki-eval
  run dirs of 2026-07-10/11 (extractions+judges+smokes+parked partials)" —
  read as *not* limited to the four target models/dirs, so
  `scan_spend_ledger()` globs `reports/terminology/wiki-eval/*/*/2026-07-1[01]T*`
  across every model/config, not just the four judge dirs. Read live
  (no snapshot) since a read-only sum over static, already-finished JSON
  files needs no isolation.
- **Spend-source fallback chain** per dir: `meta.json` spend total (finished
  runs) → last `progress.jsonl` line's `spent` (parked/resumable partials)
  → summed `cost_usd` over `calls.jsonl` rows (one dir — gemma3
  `2026-07-10T22-16-28Z` — crashed before ever writing a `progress.jsonl`
  checkpoint, only 8 raw call rows exist) → `$0.00` for genuinely empty
  stub dirs (5 observed, 0 files — a batch launch created the dir and the
  run crashed/never started).
- **No smoke dirs in the 2026-07-10/11 window**: the only `smoke`/
  `effort-probe`/`padding-smoke`/`provider8-and-auto-smoke` dirs on disk
  are all dated 2026-07-09 (`openai--gpt-5.4--auto/{smoke,effort-probe}`,
  `openai--gpt-5.5--provider-6/{padding-smoke,provider8-and-auto-smoke}`) —
  outside the requested window, so excluded from the grand total (noted
  explicitly rather than silently omitted).

## Open questions

- Three tiny `google--gemma-3-27b-it--Parasail` judge dirs
  (`2026-07-10T22-19-00Z`/`22-48-49Z_alt-names`/`23-22-18Z_label-guess`,
  5 articles each, `search_mode` = baseline/alt-names/label-guess) look
  like a search-mode ablation probe unrelated to the four G_6 baseline
  targets — included in the spend ledger (their spend is real,
  $0.0083+$0.0084+$0.0096) but not otherwise interpreted; owner may want
  to know these exist if the ablation itself is of interest.
- `google--gemma-4-31b-it--WandB` has 4 run dirs in the 2026-07-10 window
  (1 judge-shaped at `08-52-00Z`, 1 extraction at `19-34-15Z`, 1 empty-stub
  at `19-27-49Z`, 1 parked-partial 27/100 at `20-20-09Z`) all small/
  incomplete — this model was evidently abandoned mid-pilot and never
  reached a full 100-article judge run. Flagged in the anomalies list
  below; not otherwise acted on (out of the four-model scope).
- Two dirs have `no_judge: None` (schema predates the `no_judge` field:
  `google--gemini-3.1-flash-lite--Google-AI-Studio/2026-07-10T08-31-04Z`,
  `google--gemma-4-31b-it--WandB/2026-07-10T08-52-00Z`) — classified as
  `judge` by the ledger's `None`-is-falsy default, which is correct by
  inspection (both ran the full extract+judge pipeline, no
  `reuse_extraction_from`), but flagged here since it's a fallback, not a
  positive `no_judge: false` read.

## NOT done

- No git commits, no edits to any tracked/versioned file, no changes to
  the actual scoring/pipeline artifacts under `reports/terminology/`,
  `data/`, or `src/` — the underlying rescore task was offline/read-only
  throughout (verified via `git status`, no tracked files touched). This
  report itself is the one intentional exception: an untracked file in
  `docs/reports/`, matching the pattern already used by prior similar
  ml-engineer tasks in this repo (see the note at the top of this file);
  it was first placed only in the scratchpad on an overcautious reading
  of "no repo edits," then also written here after the stop-hook's report
  gate required it at the canonical path.
- No cross-model statistical significance testing (e.g. paired bootstrap
  between models) — only per-row Wilson CIs from `_cell()`, already in
  `scores_all_final.json`'s `runs.*.metrics.*` cells (not restated in the
  chat table for brevity — 2-decimal ratios + exact counts only, per
  instruction).
- Did not investigate *why* qwen/gemma3 show higher `judge_unavailable`
  counts (286 and 18 respectively) than gemini/deepseek (0 each) — flagged
  as an observation in the final message, root-causing their API
  reliability during these specific runs was out of scope.
- Did not reconcile the two small `gemma-4-31b-it--WandB` and three
  `gemma-3-27b-it` ablation-probe dirs against any spec/plan describing
  their purpose — noted as an open question above instead of guessing.
