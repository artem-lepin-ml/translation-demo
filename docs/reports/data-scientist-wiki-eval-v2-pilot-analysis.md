# Report — wiki-eval v2 pilot analysis (data-scientist)

## Scope

Read-only statistical analysis task on the `dev-demo` demo repo (branch
`claude/ner-translation-config-b0ozsc`), no commits. Compare the NEW 10-article
wiki-eval pilot run (gemini-3.1-flash-lite, v2 pipeline, `--no-sitelink`) against
the OLD 100-article pre-redo run (same model, sitelink rung on), restricted to the
same 10 pilot articles, using the project's canonical `aggregate_corpus_v3`
aggregator:

1. **TASK 1** — apples-to-apples subset comparison table (class × gold_units/TP/FN/FP/R_doc/P_doc,
   old vs new, with deltas), plus the sitelink-rung caveat.
2. **TASK 2** — FN decomposition (never-extracted vs extracted-but-grounding-failed,
   sub-split by failure mode) for both runs on the same 10 articles.
3. **TASK 3** — judge-escalation profile on the NEW pilot from `pred.jsonl`
   (`resolved_by` distribution, escalation share, single-candidate-escalation share).

Deliverable: `docs/reports/wiki-eval-v2-pilot-analysis.md` (English, tables + prose,
every number reproducible by scripts left in the scratchpad) plus this schema-compliant
report.

## Files changed

- **`docs/reports/wiki-eval-v2-pilot-analysis.md`** (new) — the actual analysis
  deliverable: subset-comparison table with caveats, FN decomposition old vs new,
  judge-escalation profile, NOT-done list, 5-line executive summary.
- **This report** (new).
- No other repo file touched; no commits made (task was explicitly read-only/no-commit).
- Scripts (scratchpad, not committed, per task instruction):
  `/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/task1_subset_compare.py`,
  `task2_fn_decomposition.py`, `task3_escalation_profile.py`, plus their
  `task{1,2,3}_output.json` machine-readable outputs.

## Decisions & rationale

- **Reused the project's own `cmd_report` construction logic exactly** (`pred_tuples`
  = records with a truthy `qid`, GT loaded from `gt.jsonl`'s own `gt_tuples` field,
  grouped by article title) instead of re-deriving matching from scratch — verified
  by reproducing the NEW run's own committed `metrics.json` byte-for-byte via
  `aggregate_corpus_v3` before trusting the script for the OLD-run subset and FN work.
- **Sitelink-rung attribution reported as not quantifiable, not estimated.** Checked
  `grounding/candidates.py` (candidate-generation `source` field: `wbsearchentities`/
  `cirrus`/`wikipedia_langlink`) against `predict.py:86-93`, which persists only
  `index/surface/lemma/qid/span_len/resolved_by` to `pred.jsonl` — `source` never
  reaches disk. Confirmed no other pred.jsonl field (nor the OLD run's own
  `resolved_by` distribution) distinguishes sitelink-sourced predictions. Cited the
  retired `sitelink_contamination.py` replay's prior ~1%-of-grounded / ~0.6pp-R_doc
  estimate purely as differently-scoped context, explicitly not as a number
  reproduced by this task (task said not to replay deleted machinery).
- **FN-decomposition matching used `grounding.match.norm`** (casefold + ё→е +
  dash-fold), the same normalizer the production grounding pipeline itself uses for
  exact-label matching — chosen over a hand-rolled normalizer so "extracted" is
  judged by the same notion of surface equivalence the system already uses.
- **FN bucket-classification priority order** (wrong-qid assignment > judge_rejected >
  no_candidates > judge_unavailable/wikidata_unavailable) was chosen because a
  wrong-QID assignment is the most informative/severe failure signal when multiple
  pred records match the same gold anchor surface within an article; this is a
  documented modeling choice, not implied by the task text verbatim.
- **Judge-escalation candidate-count sub-metric reported as NOT COMPUTABLE**, with the
  exact code lines (`label_first.py:286-300` builds the trace; `predict.py:78`
  discards everything but `resolved_by`) cited as evidence rather than asserting it
  from memory — verified by grep before writing the finding.
- **Flagged, not silently absorbed**: the OLD vs NEW comparison conflates the sitelink
  toggle with the entire v2 pipeline rework (prompts, transport, sampling per
  `docs/stages/wiki-eval.md`); OLD's `meta.json` lacking any `generation_params`/
  `grounding_config` block was used as direct evidence it predates that rework, not
  just inferred from dates.
- **Added a pooled "overall" row** in the Task 1 table beyond what was strictly asked
  (class × metrics only) — kept because it's a two-line derivation from already-computed
  class cells and materially aids the executive summary; flagged inline as an addition
  rather than silently presented as part of the literal task spec.

## Open questions

- Owner decision needed on whether the term-class precision drop (43.5% → 34.0%,
  −9.44pp, FP 39→62) warrants a dedicated FP-decomposition follow-up (symmetric to
  Task 2's FN decomposition) before trusting the v2 pipeline's term-class behavior.
- Whether it's worth adding a persisted `n_candidates` (or full candidate list) field
  to `pred.jsonl`/`calls.jsonl` in a future run so Task 3's single-candidate-escalation
  share becomes answerable without a live re-run or a cache replay.
- Whether a proper isolated sitelink-only ablation (same v2 pipeline, only
  `use_sitelink` toggled) is worth commissioning, since the current OLD/NEW pair
  cannot isolate that effect.

## NOT done

- **Sitelink-rung contribution on this 10-article/v3-protocol subset** — not
  quantifiable from any `pred.jsonl` trace field on either run (see Decisions);
  only a differently-scoped historical estimate is cited as context.
- **"Share of judge escalations with exactly 1 candidate" (Task 3)** — not computable
  from any file in the NEW run's output directory; the candidate list is discarded
  before persistence by design. Would require a live re-run with an added field, or a
  cache replay (explicitly out of scope — "don't replay/remove them, machinery
  deleted").
- **No formal significance test beyond per-cell Wilson CIs** (e.g. no paired McNemar
  test across the matched 10-article set) — the already-shown CIs are wide enough
  that this would not change the "not distinguishable from noise" recall conclusion,
  but it was not formally run.
- **No isolated sitelink-only ablation was run or attempted** — Task 1's OLD-vs-NEW
  delta is explicitly flagged as conflating the sitelink toggle with the full v2
  pipeline rework, not corrected for it.
