# python-pro: span-level NER recall/precision before/after gold cleanup (gemini pilot)

## Scope

Task: recompute the span-level (QID-agnostic) NER recall/precision on the 2026-07-10 gemini
pilot (`reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z/`)
against the CLEANED gold, compare to the published baseline (named 93.5% / term 62.1% / overall
87.8%), and commit a small data report. Pure offline replay: no LLM calls, no network. Hard
constraints observed throughout: `gt.jsonl` never modified; nothing under `reports/` (incl.
`pred.jsonl`) written or deleted; branch `claude/ner-translation-config-b0ozsc` never switched.

## Files changed

- `data/eval/wiki/cleanup/tools/span_ner_before_after.py` (new) — the analysis tool. Ports
  Section D of `replay_analysis.py` verbatim (`overlaps()`, `M._classify`-based pooled-surface
  classification, tier filter, dedup-precision variant) rather than reinventing the overlap
  definition. Computes: (1) a baseline-reproduction sanity gate against the pre-cleanup gold
  snapshot (`git show 4c77b7c~1:data/eval/wiki/gt.jsonl`), which must hit the published numbers
  exactly or the script stops; (2) the "after" numbers using current `gt.jsonl` restricted to
  kept pilot articles, minus the live entries of `anchor_exclusions_draft.json` applied
  in-memory only. Deterministic — verified two runs produce byte-identical JSON output (written
  only to the session scratchpad, never under `reports/`).
- `docs/reports/wiki-eval-v2-span-ner-before-after-cleanup.md` (new) — the data-first English
  report: pilot-article kept/replaced status table, baseline-reproduction gate result, before/after
  recall and precision tables with denominators, per-article excluded-anchor counts (all/tier-0
  split), and an honest caveats section (draft/unapproved exclusions, precision lower-bound
  caveat inherited from the original report, small sample size, no unit-class reclassification
  observed).
- Commit `3ce02c0` — `docs(wiki-eval): span-level NER metrics before/after gold cleanup`, pushed
  to `origin/claude/ner-translation-config-b0ozsc` (push succeeded on first attempt, no retries
  needed).

## Decisions & rationale

- **Baseline gold snapshot = `4c77b7c~1`.** That is the commit immediately before the first gold
  change (the IPA-anchor drop); the published report's own commit (`61bd46e`) is later in history
  but never touched `gt.jsonl` itself, so `4c77b7c~1` is the exact snapshot the report used.
  Verified this snapshot reproduces the published cells exactly (400/428, 59/95, 459/523) before
  proceeding, per the task's mandatory sanity gate.
- **Verified the "gold identical pre/post IPA-fix for this pilot" claim directly**, not by
  assumption: diffed `gt_tuples` tuple-for-tuple (not just counts) across `4c77b7c~1`, `4c77b7c`,
  and current `gt.jsonl` for all 10 pilot titles — all three snapshots are byte-identical for
  this pilot's articles. This is a load-bearing finding: it means the entire "after" delta in
  this report comes solely from the still-unapproved draft exclusions, not from either already-
  landed gold commit. Flagged prominently as caveat #2 in the report rather than left implicit.
- **No candidate-replay machinery needed.** The original `replay_analysis.py` uses an offline
  `WikidataClient` subclass for Sections A/B/C (QID disambiguation analysis), but Section D
  (span-level, QID-agnostic) only needs `index`/`span_len` straight from `pred.jsonl` records —
  confirmed by reading the replay loop (it just carries `index`/`span_len` through unchanged from
  `pred_records`). Skipping that machinery avoids loading the Wikidata cache and keeps the new
  tool lighter, while still reusing every piece of D's own logic verbatim.
- **Exclusion matching identity** = `(token_index, anchor_text, qid, span_len)` scoped per
  article title, per the draft file's own documented identity convention. Verified all 46
  matched exclusion entries for pilot articles actually exist in current `gt.jsonl` (0
  unmatched) before trusting the subtraction.
- **Checked for classification/partial-removal side effects** of applying exclusions: confirmed
  (a) no gold unit's named/term class changed as a result of surface-set shrinkage, and (b) every
  removed tier-0 anchor was its unit's *only* anchor (full-unit removal, not partial) — both
  verified programmatically, not assumed, and both called out as caveat #5 (not guaranteed to
  generalize to other article subsets).
- **Report is English**, per explicit task instruction and per CLAUDE.md's documentation-language
  convention (`docs/` is English; only owner-facing chat/HTML delivery is Russian) — this is a
  `docs/reports/` data report in the same family as the original `wiki-eval-v2-pilot-ner-vs-
  disambig.md`, not an HTML/Artifact delivery under the 8-step Verify/Finish template.
- **Commit staged exactly the two intended files** (verified via `git status --porcelain` before
  and after `git add`) — no incidental changes to `gt.jsonl`, `reports/`, or anything else.

## Open questions

- The draft exclusions in `anchor_exclusions_draft.json` are still pending owner approval; this
  report is a what-if analysis on top of that draft, not a claim that the numbers are final. If
  the owner amends the draft (adds/removes exclusions), these before/after numbers would need a
  rerun — the committed tool makes that a one-command re-run.
- Whether the "no reclassification / no partial-unit removal" property holds for the other 90
  articles' exclusions (only this pilot's 7 affected articles / 20 tier-0 anchors were checked)
  is untested — explicitly scoped out in the report's caveats, not silently assumed to generalize.

## NOT done

- Did not touch the 90 non-pilot articles' exclusion effects — out of scope per the task (pilot
  only).
- Did not apply `anchor_exclusions_draft.json` to `gt.jsonl` on disk — by design, the task
  requires in-memory application only; the draft remains DRAFT.
- Did not open a PR — task explicitly said "No PR," only push the branch.
- Did not re-run Sections A/B/C (QID disambiguation decomposition) under the new gold — out of
  scope; the task asked specifically for span-level (Section D) metrics only.
