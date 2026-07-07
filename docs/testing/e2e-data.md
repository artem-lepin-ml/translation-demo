# E2E Test Data Manifest — Palimpsest demo

Up-link: [docs/subsystems/webapp.md](../subsystems/webapp.md) · process: global step 6/8 e2e-tester uses **only** the real data named here, driven **through the UI** (never seeded via DB writes or URL params).

## App under test

- Frontend (Vite dev): `http://localhost:5173` — single UI (Variant A), no router. The legacy Variant B and hash router were removed 2026-07-02.
- Backend (FastAPI): `http://localhost:8000`, proxied under `/api`.
- DB: SQLite at `data/demo.db`, populated by `python -m palimpsest.webapp.seed`.

## Real seed data (single source)

`data/seed/seed_paragraphs.jsonl` — 15 body paragraphs from the book opening (RU source `data/pilot/pilot_original.md`, EN target the `gemma_par_by_par` translation), rebuilt by [scripts/rebuild_seed_texts.py](../../scripts/rebuild_seed_texts.py) as part of [seed-refresh](../superpowers/plans/2026-07-02-seed-refresh.md) (was: 16 curated paragraphs from the pilot run, `gpt-5.4-mini` par-by-par, top-by-issue-density). Seed-refresh Phases A–C are complete: each record carries genuine LLM-judge baselines (`openai/gpt-5.4-mini`) for 4 seeded criteria plus real terminology (haiku-4.5 extract + subagent G3/P3 grounding/pairing, 204 terms — see [terminology stage doc](../stages/terminology.md) Status). The `term` table's real difficulty/pairAccuracy verdicts reach the DB via a separate step, `uv run python scripts/load_terms.py`, run **after** `python -m palimpsest.webapp.seed` — `seed.py` alone still writes its placeholder `VERDICTS[i % 3]` rotation for difficulty/pairAccuracy (see [webapp.md](../subsystems/webapp.md) `seed.py` row and [known_issues.md](../known_issues.md)).

Served as one document:

| Field | Value |
|---|---|
| Document title | `Mesopotamia — ancient Near East (pilot)` |
| Language pair | ru → en |
| Paragraphs | 15 |
| Criteria (evaluators) seeded | 4 — accuracy, fluency, style, terminology (Cultural Adaptation dropped wave-4 Б4; `consistency` present in source data but **not** seeded as an evaluator) |
| Issues (seed) | real, from `/evaluate`-generated baselines (see [terminology stage doc](../stages/terminology.md) and [known_issues.md](../known_issues.md) for the advice-guard corpus) |
| Terms | 204, difficulty 🟢62/🟡31/🔴111 — real G3/P3 output, `data/seed/terminology_out.json`, loaded via `scripts/load_terms.py` |
| Paragraph 1 aggregate (baseline) | real, from the regenerated 15-paragraph seed (no longer the pre-refresh 6.44/10 figure) |

This is the seeded document (`origin='seed'`), always present and never deletable. There is no auth, no roles. The demo now also supports user-uploaded documents (`origin='upload'`) created live through the upload modal — see the "Upload a custom pair" journey below. The document switcher in the top bar lists both.

## Live LLM

`OPENROUTER_API_KEY` is **absent by design** in the demo environment for the seeded document. `POST /api/paragraphs/{id}/evaluate` therefore returns the pre-computed `kind='cache'` scores (the "expected post-fix" uplift) instead of calling a live model. This cache-fallback path **is** the canonical demo behavior to test for the seeded journeys below. The "Upload a custom pair" journey exercises precompute and live `/evaluate` on an uploaded document and needs a real key for its live-scoring states (10–12) — out of scope for the no-key seeded run.

## Canonical user journeys (all must pass)

1. **Load** — open `/`; document with 15 paragraphs renders; each shows aggregate score, criterion underlines, terminology dots, inspector.
2. **Inspect a paragraph** — click a paragraph → inspector opens → Issues tab lists that paragraph's issues with explanation/suggestion/severity; Scores tab lists per-criterion values.
3. **Terminology two-signal** — open Glossary tab and a source-term: `difficulty` dot (🟢 grounded / 🟡 ambiguous / 🔴 not-found) on the RU term; `pairAccuracy` on the RU↔EN pair (null when difficulty=red); Wikidata link present on glossary rows.
4. **Improvement loop (the headline)** — accept a suggested fix on a paragraph → target text updates → re-score runs → aggregate rises and shows ▲delta with a `cached` badge.
5. **Reset** — Reset button → document returns to seed baseline (target text and scores restored; accepted edits gone).
6. **Settings** — 4 evaluators render with model · weight · prompt; model registry shows masked API key (no plaintext secret on screen).
7. **Ranking** — paragraphs sortable by each criterion and by aggregate.

## Journey: upload a custom pair (all must pass)

Data is whatever the tester types or drags into the modal at run time (no fixed fixture — the
feature's whole point is arbitrary user input). Use a short synthetic DE→FR pair for live-scoring
states (10–12) to keep cost near zero. Full design: [upload-design spec §5](../superpowers/specs/2026-07-02-custom-pair-upload-design.md).
States, 1:1 with the spec's e2e checklist (§5.8) — each is at least one screenshot with provenance:

1. Top bar: open `doc-dropdown` — seed + upload docs listed, language-pair badges, delete icon only on `origin='upload'`.
2. Modal step 1, pristine: placeholders visible (language inputs are free-text fields, placeholders "Russian"/"English"), counters read "0 ¶ · 0 chars".
3. Modal step 1: both language text inputs set to the same value (case-insensitive) → "Source and target languages must differ" error, Next disabled.
4. Modal step 1: `.docx` busy state — spinner "Extracting text…", panel buttons disabled.
5. Modal step 1: file error in a panel footer (415 — upload a `.doc`/`.pdf`).
6. Modal step 1: filled with a paragraph-count mismatch (e.g. 7 ¶ vs 9 ¶).
7. Modal step 2: mismatch — red badge, orphan rows highlighted, "Create document" disabled.
8. Modal step 2: after two merges — counts equal, CTA enabled, precompute checkbox with its cost caption.
9. New document rendered: column headers "Original (German)" / "Translation (French)" (typed free-text, or the pilot's "Russian"/"English" via `langLabel`), Terms chip disabled with tooltip.
10. Top bar: "warming k/12 ¶…" badge in `running` state.
11. A paragraph after its first score (precompute): score chip with a value and **no** delta badge.
12. A paragraph after its second score (live, on top of precompute): delta badge "old → new".
13. Glossary tab on the uploaded document: empty-state text about offline terminology.
14. Reset on the uploaded document: confirm → translation reverts to the uploaded text.
15. Delete the upload: confirm dialog → dropdown no longer lists it, seed document is active.

## Journey: AI-translate / revision history / export (wave-5, all must pass)

Uses the same "Upload a custom pair" modal as above, plus the Settings Translator card and the
per-paragraph History block. Full design: [contracts spec §7](../superpowers/specs/2026-06-30-demo-contracts.md#72-newchanged-rest),
[2026-07-05-translator.md](../superpowers/specs/2026-07-05-translator.md),
[2026-07-05-score-history-best.md](../superpowers/specs/2026-07-05-score-history-best.md),
[2026-07-05-export-xlsx.md](../superpowers/specs/2026-07-05-export-xlsx.md).

1. Upload modal, source-only (no `target` pasted): `ai-translate-card` (`data-testid`) shows an "AI-translate" CTA (`ai-translate-cta`) naming the configured translator model; Step 2 is skipped; submit via `upload-submit-translate`.
2. Document opens with a `Translating N/total…` badge; polls until `done` (or `failed` with `errorReason` — no API key / budget exhausted — surfaces a Retry affordance, per `translate.py`'s `_classify_failure`).
3. A paragraph's `revision-history` block (`InspectorPanel`) lists past revisions (`history-row-{id}`), each restorable via `history-restore-{id}`; the highest-scored one is flagged best.
4. Restore a non-current revision: `target` reverts to that text, a NEW `origin='restore'` revision is written (restore is itself tracked, not a rewind), and the paragraph's score resets to "not scored" until the next explicit Evaluate — restoring does **not** copy the old score. **Known bug (wave-5 e2e, [wave5-run.md §4.1](../reports/e2e/wave5-run.md))**: the History list does not always refresh with the new revision immediately after a successful Restore in the same session — a manual reload (or the next `GET /api/paragraphs/{pid}/revisions`) shows the correct, complete list. Not yet fixed; retest after any History-block refetch change.
5. `export-btn` in the top bar opens `export-menu` with two items, `export-xlsx` and `export-md`; each downloads a file named `{slug}-{doc_id}.{ext}` (verified end-to-end in [wave5-run.md](../reports/e2e/wave5-run.md): xlsx round-trips through `openpyxl` — 15¶+header+meta rows, frozen header, score-colored cells; md is a valid GFM table).

## Out of scope (do not test / do not seed)

- Live model inference on the seeded document (no key — see above).
- The legacy LLM-Comparator viewer and old pipeline branches (untouched, not part of this app).
- DB-seeding shortcuts via URL — drive everything through the UI, including document creation (`POST /api/documents` only via the upload modal, never a raw `fetch`/`curl` from the test).
