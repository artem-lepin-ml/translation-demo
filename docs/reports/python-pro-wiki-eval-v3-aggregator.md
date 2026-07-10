# Wiki-eval protocol-v3 aggregator: production code + regression anchors + cleanup

Agent: `python-pro`. Spec: [2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md) §4.5 + §7.
Branch: `claude/ner-translation-config-b0ozsc` (shared worktree, parallel lanes — see Scope).

## Scope

Implement the production v3 set-based document-level aggregator (spec §4.5,
decision Р9) as an **additive-only** change to `metrics.py`/`report.py` (the
old mention-level machinery stays until another lane rewires
`scripts/wiki_eval.py` off it), add regression-anchor tests against two
committed `pred.jsonl` runs, and execute the safe subset of spec §7's cleanup
(tier-data file moves, dead-script deletion, derived-cache deletion). Owned
paths only: `metrics.py`, `report.py`, `tests/test_wiki_metrics_v3.py`, the
listed file moves/deletions, small doc-path updates. Explicitly out of scope
(other lanes): `scripts/wiki_eval.py`, `scripts/term_pipeline.py`,
`extract.py`, `grounding/`, `test_wiki_eval_runner.py`, `test_terminology.py`.
No commit made (staging only, per task instructions).

## Files changed

- `src/palimpsest/terminology/evaluation/metrics.py` — additive: `ArticleUnits`
  (TypedDict), `_classify()`, `aggregate_corpus_v3()`. +118/-0 lines
  (`git diff` confirms zero deletions — no existing function touched).
- `src/palimpsest/terminology/evaluation/report.py` — additive:
  `_V3_CLASS_LABELS`, `_v3_cell_td()`, `render_html_v3()`. +62/-0 lines.
- `tests/test_wiki_metrics_v3.py` — new file, 9 tests: 7 synthetic-fixture
  (tier filter, mixed-case ambiguity, FP-own-surface classification, mention
  dedup, empty-pred zero-recall, Wilson-cell shape, `protocol` key) + 2
  regression anchors on committed `pred.jsonl` runs + 1 gold-invariant check.
  Guarded with `pytest.mark.skipif` on missing data files.
- `git mv docs/experiments/2026-07-05-model-comparison/drafts/tier_assignment.json data/eval/wiki/tier_assignment.json`
  and same for `tier_defs.json`.
- `git rm scripts/sitelink_contamination.py scripts/sitelink_clean_full_metrics.py scripts/replay_sitelink_contamination.py`
  (verified via repo-wide grep: no `.py` file outside `scripts/` itself
  imports any of the three).
- `git rm -r docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay/`
  (8 files: `.wikidata_cache.{deepseek,gemini,qwen}...jsonl` candidate caches,
  `.wikidata_cache.label_exists.{deepseek,gemini,gpt-5.4}...jsonl` label
  caches, `deepseek.json`/`gemini.json` source-replay maps) +
  `git rm docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json`.
- Doc path updates: **none required** — grepped `docs/stages/`,
  `data/eval/wiki/README.md`, `docs/README.md` for the old
  `drafts/tier_{assignment,defs}.json` paths; zero matches.

## Decisions & rationale

- **Verified the aggregation logic against the anchor numbers before writing
  production code**, not after: wrote a throwaway scratchpad script
  reproducing the exact spec §4.5 algorithm over the raw `gt.jsonl` +
  `pred.jsonl` data, ran it, and got exact matches for both runs
  (`n_ambiguous_gold_units=114`, `n_gold_mentions_dropped_by_tier=785`, all
  8 tp/fn/fp/gold_units cells) on the first attempt. This is why the
  production function and tests needed zero iteration — the algorithm as
  specified is unambiguous and the anchors are internally consistent.
- **Tier filter asymmetry is deliberate, documented in the docstring**: the
  filter drops non-zero-tier QIDs from the *gold* side only; a prediction on
  a filtered-out QID still counts as FP. This keeps `P_doc` a conservative
  lower bound (matches the module's existing `P3` precision philosophy)
  rather than quietly forgiving predictions on the same grounds gold was
  pruned. Verified with a synthetic test
  (`test_tier_filter_drops_gold_but_prediction_on_same_qid_is_still_fp`).
- **FP classification uses the pred unit's OWN surfaces, not any gold
  information** (spec-mandated, since the QID isn't in the gold map for an
  FP by definition) — separate synthetic test.
- **`ArticleUnits` has no slice maps** (`resolved_by_of`/`stratum_of`/`type_of`
  from `ArticleTuples`), because protocol v3 has no stratum/resolved_by
  slicing per spec Р9 — kept the TypedDict minimal rather than reusing
  `ArticleTuples` and ignoring three of its five keys.
- **`sitelink-clean-full-metrics.json` deleted despite living one directory
  above `drafts/`** (task text said "under drafts/"): the task named the
  exact filename explicitly and it's unambiguously the same "derived
  sitelink-replay artifact" category as everything else in this cleanup
  step, so I treated the directory-level detail as imprecise task wording
  rather than a hard boundary and deleted it anyway.
- **No doc edits for the tier-file move**: the task's own grep instructions
  (`docs/stages/`, `data/eval/wiki/README.md`, `docs/README.md`) turned up
  zero stale references, so there was nothing to fix. I did not
  proactively add new documentation entries for the two moved files in
  `data/eval/wiki/README.md`'s "Other files in this directory" list, since
  the task scoped this to *fixing references*, not authoring new docs, and
  CLAUDE.md's "no speculative work" convention argues against it.
- **Left `docs/paper/sections/eval-metrics-terminology.tex` and
  `docs/reports/*.md` untouched** even though they reference the old
  `drafts/tier_assignment.json` path: these are provenance/historical prose
  (describing what was computed and where, at the time), not the three
  named living docs, and the `.tex` file's header explicitly documents
  numbers-provenance for a specific historical run — rewriting it would
  misrepresent what was actually done at that time.
- **`render_html_v3` kept deliberately minimal** per the task ("Keep it
  minimal"): one table (named/term rows × gold_units/TP/FN/FP/R_doc/P_doc),
  two counter lines, reusing the existing `_CSS`/`_cell_class`/`_fmt_value`/
  `_fmt_ci` helpers rather than inventing new styling.

## Open questions

- `docs/stages/wiki-eval.md` still references the three deleted sitelink
  scripts (confirmed via grep) — spec §7 assigns "UPDATE
  docs/stages/wiki-eval.md (rewrite for v3 + new prompts/params)" as its own
  broader item, which reads as a separate lane's job (likely `docs-keeper`),
  not folded into this "small doc path updates" task. Flagging so the
  orchestrator confirms someone owns it before merge — right now that doc
  has dead references.
- `docs/paper/sections/eval-metrics-terminology.tex`'s header comment cites
  `drafts/tier_assignment.json` as provenance for the *sitelink-clean*
  numbers (3265/621) that this same file's own comment says are being
  superseded by the raw-pred v3 anchors — that reconciliation (updating the
  paper section's provenance note to reflect the new raw numbers, or
  explicitly keeping both figures) is a paper-writing decision outside this
  task's scope.

## NOT done

- Did not touch `scripts/wiki_eval.py`, `scripts/term_pipeline.py`,
  `extract.py`, `grounding/`, `test_wiki_eval_runner.py`,
  `test_terminology.py` — explicitly off-limits (owned by other lanes).
- Did not delete the old mention-level machinery (`match_m1`/`match_m2`,
  `p1`/`p2`/`p3`, `aggregate`, `aggregate_corpus`) in `metrics.py`/
  `matching.py`/`report.py` — per the explicit sequencing constraint, that
  deletion happens in a later phase once `scripts/wiki_eval.py` is rewired
  off it.
- Did not run/fix the full `pytest tests/ -q` suite to green: it currently
  fails to even collect (`tests/test_wiki_eval_runner.py` →
  `ImportError: cannot import name 'DEFAULT_NER_PROMPT' from
  palimpsest.terminology.extract`, another lane mid-edit) and, with that
  file ignored, has 3 pre-existing failures in `tests/test_terminology.py`
  (category field removed from `extract.py` by the same other lane). Both
  confirmed cross-lane via `git diff --stat` on my two owned files showing
  0 deletions.
- Did not commit anything (moves/deletions staged only, per task
  instructions — "DO NOT COMMIT").
- Did not add `SUPERSEDED` markers to the 15 old run directories (spec §5.5)
  — out of scope for this task (post-landing step for the new runs, not
  part of §4.5/§7's safe subset assigned here).

## Run artifacts

- Scoped tests: `PYTHONPATH=src uv run --no-sync python3 -m pytest
  tests/test_wiki_metrics.py tests/test_wiki_metrics_v3.py
  tests/test_wiki_report.py tests/test_wiki_matching.py -q` →
  `50 passed in 0.51s`.
- Full suite minus the cross-lane-blocked file:
  `pytest tests/ -q --ignore=tests/test_wiki_eval_runner.py` →
  `3 failed, 515 passed in 13.63s` (all 3 failures in
  `tests/test_terminology.py`, cross-lane).
- Anchor verification (independent scratchpad script, run before writing
  production code): both runs' tp/fn/fp/gold_units and the two counters
  matched the spec-given expected values exactly on the first run.
