# Data-scientist report — wiki-eval v2 pilot: retrieval vs disambiguation decomposition

Internal agent report (harness reporting protocol). The actual analytical deliverable
requested by the orchestrator is a separate, exact-filename file — see "Files changed" below;
this report is the process/decisions record, not a duplicate of that content.

## Scope

Decompose the gemini-3.1-flash-lite 10-article wiki-eval v2 pilot's recall and precision
errors into NER/retrieval failures vs disambiguation failures, purely offline: no LLM calls,
no network access, Wikidata candidate retrieval replayed strictly from the committed cache
file (`reports/terminology/wikidata_cache.jsonl`). Required first a reconciliation gate against
given v3-aggregator counts, then four analyses (A FN decomposition, B oracle recall, C FP
decomposition, D — an owner addition mid-task — span-level QID-agnostic NER quality), on the
pilot's `pred.jsonl` (1203 records) against `data/eval/wiki/gt.jsonl` (10-title subset) and
`data/eval/wiki/tier_assignment.json`.

## Files changed

- **Created & committed:** `docs/reports/wiki-eval-v2-pilot-ner-vs-disambig.md` (the exact
  filename the task specified as the sole deliverable) — commit `61bd46e` on
  `claude/ner-translation-config-b0ozsc`, pushed to origin. Contains method, reconciliation gate
  result, replay sanity percentages, tables A/B/C/D, and a limitations section.
- **Created, NOT committed (scratch only, per task's isolation instruction):**
  `/tmp/.../scratchpad/ner_vs_disambig/replay_analysis.py` and `replay_output.json` — the
  script that produces every number in the report, and its full JSON output. Kept in the
  session scratchpad, not the repo, so it is reproducible but does not compete with the
  committed deliverable.
- **Read-only, untouched (verified via `git status`/no modification):** the pilot run
  directory, `gt.jsonl`, `tier_assignment.json`, `wikidata_cache.jsonl`, and all `src/` code
  (reused, not modified) — `git status --short` before commit showed only the one new report
  file as untracked, confirming nothing else in the working tree was touched.
- **This file** (new, this report).

## Decisions & rationale

1. **Reconciliation gate run first, against both the task's hardcoded expectations and the
   run's own committed `metrics.json`.** Both matched exactly (named tp=255 fn=47 fp=106
   gold_units=302; term tp=32 fn=45 fp=62 gold_units=77; n_ambiguous_gold_units=15;
   n_gold_mentions_dropped_by_tier=50) — proceeded per the task's explicit instruction to stop
   on any mismatch.
2. **Exact TP/FN/FP unit sets extracted by replicating `aggregate_corpus_v3`'s own per-article
   loop**, not by rewriting its classification logic — reused `M._classify` (the actual private
   helper) directly, and verified self-consistency by re-summing the extracted sets back to the
   gate's own counts.
3. **Offline replay via `OfflineWikidataClient(WikidataClient)`** — overrides only `_fetch` (to
   answer from the pre-loaded in-memory cache dict or raise) and `_store` (hard-disabled, so a
   bug could never append to the real cache file). Reused `generate_candidates()` and
   `GroundingConfig`/`TermMention` unmodified; deliberately did not reimplement any retrieval
   semantics. Result: 0/1203 cache misses, both sanity checks (chosen-qid-in-candidates,
   no_candidates-implies-empty-set) at 100% — full, not partial, replay coverage.
4. **`disambig_miss` (A) and `disambig_swap` (C) sub-classification use a hand-authored
   priority rule** when a unit has multiple eligible overlapping mentions (e.g. exact_label
   wrong-pick takes priority over llm_disambiguation wrong-pick over judge_rejected). Documented
   explicitly in the report's method section as a convention I authored for this analysis, not
   an existing codebase primitive — flagged rather than presented as canonical.
5. **Section D (owner mid-task addition) reused the same overlap machinery from A/C** rather
   than building parallel logic. Ambiguous gold anchors were classed via the same per-unit
   `gold_class` lookup already built for the reconciliation step (an ambiguous unit's individual
   anchors inherit the unit's pooled "named" class) — chosen specifically so D's class split
   stays consistent with A/B/C's, per the coordinator's "mirroring v3" instruction, rather than
   re-deciding class per single anchor's own capitalization (which would have been a plausible
   but inconsistent alternative).
6. **D precision's severe-lower-bound caveat (gold links only first mentions) is stated
   prominently, with a dedup variant computed** (group by `(article, norm(lemma-or-surface))`)
   specifically because the raw number without that caveat would be misleading on its own.

## Open questions

- Whether the ~100% cache-hit / 100% sanity-match result would hold on the full 100-article
  corpus or other models/configs — this pilot is a single 10-article, single-model sample, and
  the report says so explicitly (limitation #6 in the deliverable).
- Whether the coordinator wants a formal significance test (e.g. bootstrap CIs) added on top of
  the raw bucket counts, given some subclasses are small (term `disambig_miss` n=2) — flagged as
  not run, not decided either way.
- Whether the `R_oracle_overlap` < `TP + disambig_miss` wrinkle (2 named / 5 term units) merits
  a deeper per-unit trace in a follow-up — explained mechanistically in the report but not
  individually enumerated.

## NOT done

- No LLM calls and no network calls were made, as required — verified structurally (network
  path hard-raises in `OfflineWikidataClient._fetch`) and empirically (0 cache misses logged).
- Did not modify or re-derive anything in the read-only pilot run directory, `gt.jsonl`, or
  `wikidata_cache.jsonl` — confirmed via `git status --short` before/after.
- Did not commit the scratch replay script/JSON to the repository — per the task's explicit
  "commit ONLY that report file" instruction, only
  `docs/reports/wiki-eval-v2-pilot-ner-vs-disambig.md` was `git add`ed and committed.
- Did not run a statistical-significance test beyond the raw counts/Wilson CIs already inside
  `aggregate_corpus_v3`'s own output (see Open questions).
- Did not attempt to disentangle Section D's precision shortfall between "genuinely spurious
  extraction" and "correct but unannotated by Wikipedia's sparse linking" — stated as
  indistinguishable from this pilot's gold data alone.
