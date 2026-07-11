# python-pro report — wiki-eval survival-stage factorized metrics

## Scope

Extend the wiki-eval corpus aggregator (`src/palimpsest/terminology/evaluation/metrics.py`)
with the survival-stage FACTORIZED metrics needed for the paper's
`tab:grounding-results` table (R_NER · R_search · A_disamb → R, plus a
conservative pooled precision P), and wire them into the existing
`scripts/wiki_eval.py report` CLI so a run dir can be scored end-to-end.
Code was written to the task's own spec (no separate plan doc existed or was
requested); this report documents what was implemented and why.

Out of scope by the task's own definition: editing
`docs/paper/sections/table-c-grounding.tex` itself (the LaTeX table) — the
task asked for the aggregator + CLI path only.

## Files changed

- `/home/user/translation-demo/src/palimpsest/terminology/evaluation/metrics.py`
  — new `aggregate_survival()` (sibling of `aggregate_corpus`, not an
  extension — different per-article input shape), `_effective_gold_entities()`,
  `_overlaps()`, `PredMention`/`SurvivalArticleUnits`/`ExclusionId` types.
- `/home/user/translation-demo/src/palimpsest/terminology/evaluation/report.py`
  — additive survival section in `render_html` (fires only when
  `result["survival"]` is present; the existing named/term table markup is
  byte-unchanged).
- `/home/user/translation-demo/scripts/wiki_eval.py` — `cmd_report` now also
  builds `SurvivalArticleUnits` per article, calls `aggregate_survival`, and
  writes the result under `metrics.json`'s new `"survival"` key; new
  `--exclusions` flag (default `data/eval/wiki/anchor_exclusions.json`);
  `_load_excluded_gold_identities` helper; `EXCLUSIONS_PATH` constant.
- `/home/user/translation-demo/tests/test_wiki_metrics.py` — 15 new tests
  (synthetic fixtures + one real-data regression anchor).
- `/home/user/translation-demo/docs/stages/wiki-eval.md` — new "Survival-stage
  factorized metrics" section (formulas, gold population, provenance),
  updated CLI interface block, new Status entry with real-data validation
  numbers.

Commit `0fcc0e6` on `claude/ner-translation-config-b0ozsc`
(`feat(wiki-eval): factorized survival metrics (R_NER·R_search·A_disamb,
pooled P) in aggregator`), pushed clean (fetch+push succeeded on the first
attempt, no rebase needed, verified `git log` matches
`origin/claude/ner-translation-config-b0ozsc`). Staged only the 5 files
above by explicit path — `git status` before staging showed a dozen
untracked run-dir/cache files from a concurrently-running ml-engineer agent;
none were added.

## Decisions & rationale

- **Sibling function, not an extension of `aggregate_corpus`.** The task's
  read-first note called `aggregate_corpus` "current corpus metrics incl.
  exclusions handling," but at HEAD it does not read
  `anchor_exclusions.json` at all (confirmed by grep and by
  `search_miss_analysis.py`'s own docstring: "this is NOT baked into
  wiki_eval.py's own cmd_report"). Its output is also named/term-split,
  while the task wants pooled-only. Given the genuinely different input
  shape (un-deduplicated predicted mentions with per-mention candidate
  lists, title-scoped exclusion filtering) the task's own escape hatch
  ("add a sibling function if cleaner") applied; `_cell`/`wilson_ci`
  primitives are still shared, `aggregate_corpus`'s own fields/behavior are
  byte-unchanged (verified: existing `aggregate_corpus` tests still pass
  unmodified).
- **R computed as `n_disamb_correct / n_gold_entities` directly, not as
  `R_NER.value * R_search.value * A_disamb.value`.** Algebraically these are
  identical whenever every intermediate stage has a well-defined
  (non-zero-denominator) rate, since disamb-correct ⊆ search-survived ⊆
  recognized ⊆ gold (strictly nested populations). The direct-count form
  stays correct even when an intermediate stage is 0/0 (e.g. nothing
  recognized), where the float-product form would poison the result with
  `None`. Cross-checked with a dedicated unit test
  (`test_survival_r_factorization_identity_matches_direct_product`) that
  covers all four pipeline outcomes (not_extracted / no_candidates /
  retrieval_miss / candidates_hit) in one fixture and asserts the two
  computation paths agree to float tolerance.
- **R vs. R_direct exposed separately, with an exact reconciliation
  identity** (`R_direct["matched"] == R["matched"] +
  n_resolved_correct_search_miss`), rather than a hard runtime assertion
  inside `aggregate_survival`. Structurally, on any run produced after the
  2026-07-10 candidates-field patch, `LabelFirstGrounding.ground()`
  guarantees `chosen_qid` is always picked from the exact `candidates` list
  recorded in `pred.jsonl`, so R and R_direct MUST agree exactly — verified
  against a real post-patch run dir
  (`google--gemma-3-27b-it--Parasail/111/2026-07-10T18-22-43Z`, 100
  articles): `R == R_direct` exactly (0.32167555819008103 both),
  `n_resolved_correct_search_miss=0`. The one real divergence source is an
  older run dir whose `pred.jsonl` predates that patch and never recorded a
  `candidates` key at all — reproduced on real data via
  `google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z`
  (judge-enabled, 95/100 titles overlap the current corpus): `R_search=0`,
  `R=0` vs. `R_direct=0.734`, `n_resolved_correct_search_miss=3554` — exactly
  equal to `R_direct`'s matched count, confirming the reconciliation
  identity holds on real, not just synthetic, data.
- **Overlap semantics ported, not imported.** `search_miss_analysis.py`
  defines `overlaps()` as a local, un-importable formula (it's an ad hoc
  `data/eval/wiki/cleanup/tools/` script, not a library module) — every
  sibling script in that directory already carries its own verbatim copy
  per that directory's own established convention. `metrics._overlaps` is a
  byte-identical port of the same formula
  (`a_index < b_index+b_len and b_index < a_index+a_len`), not a
  re-derivation; `search_miss_analysis.py` itself was left untouched
  (out of scope, and touching an ad hoc offline tool wasn't requested).
- **P's "repeat-link" treatment**: predicted `(article, qid)` pairs dedup
  before the TP/FP split, so a repeated correct link is never
  double-counted as extra TP, and a repeated incorrect link is never
  double-penalized as extra FP — verified by
  `test_survival_precision_repeat_link_dedups_to_one_entity` (both a TP and
  an FP case, 1x vs. 2x/3x repeats, identical `_cell` output). P remains a
  conservative lower bound purely because Wikipedia's linking convention
  (first-mention-only, often only-once-per-article) means a correctly
  grounded entity that editors simply never linked has no gold counterpart
  and is FP regardless of repeat status — documented explicitly in both the
  docstring and the stage doc so this isn't mistaken for a repeat-link
  penalty.
- **`cmd_report` extended in place, no new subcommand.** The task explicitly
  said "a report/CLI path ... if one already renders corpus metrics from a
  run dir (check cmd_report)" — `cmd_report` already is that CLI ("offline
  recompute: metrics.json + report.html from persisted pred + gt"), so
  extending it satisfies "plus a CLI to score a run dir" without a
  parallel/speculative new entry point.
- **`meta.json` provenance (`search_mode`/`reuse_extraction_from`/
  `no_judge`) needed no new plumbing.** `cmd_report` already merges the
  run's own `meta.json` into the report `meta` dict wholesale
  (`meta = {**run_meta, **meta}`), and those fields are already top-level
  keys in `meta.json` when a run used them — so they reach the survival
  section's output "meta" automatically via the pre-existing merge, without
  any survival-specific code.

## Open questions

- The paper's actual `docs/paper/sections/table-c-grounding.tex` table still
  shows only R_doc/P_doc (named/term split) — updating it to show the new
  factorized breakdown (or adding a second table) is a follow-up the owner
  should scope explicitly; not attempted here per the task's stated
  deliverable boundary.
- No run dir in this checkout has BOTH a disambiguation judge AND the
  candidates field simultaneously (every post-patch complete run found was
  `no_judge=true`; every judge-enabled run found predates the patch). The
  full 3-stage factorization with a genuinely non-degenerate A_disamb is
  therefore validated on real data only through synthetic fixtures plus the
  `no_judge=true` run (where A_disamb collapses to the exact-label-only
  regime, since no LLM disambiguation ever fires). A fresh judge-enabled
  post-patch run — expected once the parallel `run`/`ablate` campaign
  mentioned in the stage doc's Status section lands — would be the first
  real end-to-end validation of A_disamb specifically.

## NOT done

- Did not modify `docs/paper/sections/table-c-grounding.tex` (out of scope,
  see above).
- Did not modify `data/eval/wiki/cleanup/tools/search_miss_analysis.py` or
  any other offline `cleanup/tools/` script — left untouched; the overlap
  formula was ported into `metrics.py`, not shared via import, matching
  that directory's own existing convention.
- Did not run a fresh paid `wiki_eval.py run`/`ablate` invocation to produce
  a judge-enabled + post-patch run dir — no LLM calls were made in this
  task; all validation used existing committed run dirs plus synthetic
  fixtures, and a scratch copy of two run dirs in
  `/tmp/claude-0/.../scratchpad` (never staged/committed, deleted after use)
  for CLI smoke-testing.
- Did not touch any of the concurrently-appearing untracked files from the
  ml-engineer agent's judge-phase runs (`reports/terminology/wiki-eval/*`
  new dirs, `reports/terminology/wikidata_cache_*.jsonl`,
  `docs/reports/data-scientist-wiki-eval-miss-categorization-aggregation.md`)
  — confirmed via `git status` before and after staging that only the 5
  files this task authored were added.
