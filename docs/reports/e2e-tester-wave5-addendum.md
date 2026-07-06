# e2e-tester report — wave5 addendum (post-fix supplementary run)

## Scope

Short (~20 min) supplementary browser e2e run on branch `claude/emlp-2026-website-fixes-muih1x`,
closing the gaps listed in `docs/reports/e2e/wave5-run.md` §7 (`.md`-strip, windows-1251 fallback,
`.docx` extraction, drag-and-drop highlight) and verifying two commits that landed after the main
wave-5 run: `3f8aedf` (real Wikidata grounding enrichment of the seed glossary) and `17fc4a3`
(fix round: history refresh, friendly 409 message, straight quotes, stem-merge grouping fix).

Fresh isolated environment: `PALIMPSEST_DB=.../scratchpad/e2e2.db`, seeded via
`python -m palimpsest.webapp.seed` + `scripts/load_terms.py` (204 real terms), backend on
`127.0.0.1:8131` with `DEMO_STATIC_DIR=frontend/dist` (dist rebuilt after the fix commits).
Driven via `playwright-cli` (Chromium), session `wave5add`.

## Files changed

- `docs/reports/e2e/wave5-run.md` — appended `## Addendum 2026-07-06 (post-fix run)` section
  (purely additive, `git diff --stat` shows +113/-0).
- `docs/reports/e2e/shots/wave5-addendum/01..09-*.png` — 9 new screenshots (new directory).
- Scratch fixtures (not committed, live under session scratchpad
  `/tmp/claude-0/.../scratchpad/upload_fixtures/`): `sample.md`, `win1251_sample.txt`,
  `sample.docx` — all `GENERATED:` provenance per the report, task explicitly instructed
  generating these.

## Decisions & rationale

- Used the existing seeded document only (per the e2e data manifest, `docs/testing/e2e-data.md`)
  for the Glossary checks — no invented term data; QIDs/candidates pulled from
  `data/seed/terminology_out.json` via the live API to pick concrete, real repro targets
  (Mesopotamia → Q11767, Тигр/Тигра merge, Евфрата as the ambiguous-candidates example) before
  driving the same thing through the UI.
- For the drag-and-drop check, a first attempt with an empty `DataTransfer` (no `items`/`files`)
  did not trigger React's `onDragEnter` handler at all — documented this as a real technical
  detail (not a bug) rather than silently faking success. Adding a real `File` via
  `dt.items.add(new File(...))` before dispatching `dragenter`/`dragover` made the synthetic event
  work correctly and the `va-upload-drop-active` class + placeholder swap appeared exactly per
  `UploadModal.tsx`.
- Found and root-caused two issues beyond the checklist, both reported with code-level citations:
  1. **New bug (MEDIUM)**: term "Евфрата" (4 mentions, same lemma) still renders as **2 separate
     Glossary rows** post-fix, because 3 mentions are `grounded: null` while 1 mention was
     wrongly `llm_disambiguation`-resolved to Q1728989 "Karasu River" (a minor Euphrates
     tributary, not the Euphrates itself — the real Euphrates QID isn't even among the 5
     candidates, a known grounding-recall gap). Grouping is by `(lemma, entity)` per spec, so
     differing `qid` splits the row — same visible symptom as the original Тигр/Тигра complaint,
     different root cause.
  2. **SUSPECTED**: the Glossary legend documents 4 distinct grounding-trace states, but
     `resolveBadge()` in `frontend/src/demo/variant-a/glossary-grouping.ts:82-124` has no `case`
     for `resolved_by: "judge_unavailable"` (used by 3 of the "Евфрата" mentions) — it falls
     through to the `default` branch and renders `○ no candidates` even though 5 real candidates
     exist, when the legend's own definition says that state should be `◇ LLM rejected all`.

## Open questions

- Whether `term.traceJson` for "Евфрата" actually reaches the frontend non-empty (with
  `resolved_by: "judge_unavailable"`) or is stripped to `{}` somewhere in the DB/API layer — not
  verified end-to-end (would need a DB column dump); the `resolveBadge` switch-fallthrough theory
  is the more likely explanation per the code but not 100% confirmed against the wire payload.
- Whether the "Евфрата" row-split (item 1 above) is acceptable-by-design (group-by-entity was an
  explicit spec choice) or should be treated as a real regression against the owner's original
  complaint — left as an owner decision, both readings stated in the report.

## NOT done (explicit)

- Did not re-run the full wave5 34-scenario matrix — this was a targeted supplementary run per
  the task's explicit scope (§7 gaps + 2 named commits only).
- Did not test live LLM re-grounding/re-evaluation (no `OPENROUTER_API_KEY` in this sandbox,
  same constraint as the main wave5 run — documented there, not re-litigated here).
- Did not investigate whether other `resolved_by` values besides `judge_unavailable` are also
  unhandled in the `resolveBadge` switch (only spot-checked the one instance found via the
  ambiguous-term check).

Full addendum with the check/verdict table, all 9 screenshot refs and GENERATED-data provenance
is in `docs/reports/e2e/wave5-run.md` under `## Addendum 2026-07-06 (post-fix run)`.
