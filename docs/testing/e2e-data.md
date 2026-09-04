# E2E Test Data Manifest — Palimpsest demo

Up-link: [docs/subsystems/webapp.md](../subsystems/webapp.md) · process: global step 6/8 e2e-tester uses **only** the real data named here, driven **through the UI** (never seeded via DB writes or URL params).

## App under test

- Frontend (Vite dev): `http://localhost:5173` — single UI (Variant A), no router. The legacy Variant B and hash router were removed 2026-07-02.
- Backend (FastAPI): `http://localhost:8000`, proxied under `/api`.
- DB: SQLite at `data/demo.db`, populated by `python -m palimpsest.webapp.seed`.

**Session isolation (2026-07-16) — each browser profile is its own ephemeral session.**
Full design: [2026-07-16-session-isolation.md](../superpowers/specs/2026-07-16-session-isolation.md).
The FIRST `/api/*` request from a browser/Playwright profile without a `glossa_sid` cookie
transparently gets one (`Set-Cookie`, same-origin — the Vite dev proxy carries it, no test
change needed) and, on its first DB touch, a lazy `sqlite3`-backup-API clone of `demo.db`
under `data/sessions/<sid>.db`. Practical consequences for e2e runs:

- **Two Playwright profiles running in parallel are automatically isolated** — a document
  created/edited in profile A is invisible to profile B, by construction (each clones
  `demo.db` independently). This is the FEATURE this manifest's journeys can now use to
  verify real multi-reviewer isolation (two profiles, one dismisses an issue / edits
  Settings / refines a paragraph in A, confirm B sees none of it) — not previously testable
  since there was only one shared DB.
- **A single profile's own run is unaffected** — all its requests reuse the SAME cookie, so
  the canonical journeys above (seeded document, upload modal, translate/history/export) all
  still work exactly as documented, just against that profile's own clone instead of the
  literal `data/demo.db` file on disk.
- **A server restart wipes every session clone** (`data/sessions/*`) — a long-running local
  dev session or a restarted backend mid-e2e-run means every profile's in-progress edits are
  gone and it gets a fresh clone on its next request; this mirrors "restart = a fresh stand
  for everyone" and is not a bug to chase if a run spans a backend restart.
- **`scripts/create_demo_docs.py`** (used to seed `data/seed/demo_docs/*.json` uploads like
  "World History — Selected Passages") now needs `--golden-token`/env `GLOSSA_GOLDEN_TOKEN`
  (matching the server's `DEMO_ADMIN_TOKEN`) to land in the canonical `demo.db` any e2e
  profile's clone can see — see [deploy/README.md](../../deploy/README.md) "Session
  isolation". **Without a matching token** (e.g. local dev with `DEMO_ADMIN_TOKEN` unset,
  where the header is a no-op), the script falls back to tracking its own session cookie
  across the process's own requests, so a single `create_demo_docs.py --poll` invocation
  still correctly polls the document it just created — but that document only exists in
  THAT one throwaway session's clone, invisible to a real browser/Playwright profile
  (a different session entirely). For seeding data any e2e profile must see, the server
  needs `DEMO_ADMIN_TOKEN` set and the script needs the matching `--golden-token`; a plain
  no-token run is only useful for smoke-testing the script/pipeline itself.

## Real seed data (single source)

`data/seed/seed_paragraphs.jsonl` — 15 body paragraphs from the book opening (RU source `data/pilot/pilot_original.md`, EN target the `gemma_par_by_par` translation), rebuilt by [scripts/rebuild_seed_texts.py](../../scripts/rebuild_seed_texts.py) as part of [seed-refresh](../superpowers/plans/2026-07-02-seed-refresh.md) (was: 16 curated paragraphs from the pilot run, `gpt-5.4-mini` par-by-par, top-by-issue-density). Seed-refresh Phases A–C are complete: each record carries genuine LLM-judge baselines (`openai/gpt-5.4-mini`) for 4 seeded criteria plus real terminology (haiku-4.5 extract + G6 `label_first` grounding/pairing, 204 terms — see [terminology stage doc](../stages/terminology.md) Status). The `term` table's real difficulty/pairAccuracy verdicts reach the DB via a separate step, `uv run python scripts/load_terms.py` (or `make reseed`, which chains both steps), run **after** `python -m palimpsest.webapp.seed` — `seed.py` alone still writes its placeholder `VERDICTS[i % 3]` rotation for difficulty/pairAccuracy (see [webapp.md](../subsystems/webapp.md) `seed.py` row and [known_issues.md](../known_issues.md)).

**Difficulty distribution (single source of truth for this fact — link here, don't copy the numbers elsewhere).** As of the 2026-07-07 disambiguation pass ([scripts/rebuild_demo.py](../../scripts/rebuild_demo.py) with the live OpenRouter judge, `google/gemini-3.1-flash-lite` @ `provider-9`, over `data/seed/terminology_out.json`): **204 terms, 🟢45 / 🟡90 / 🔴69** (`resolved_by`: `exact_label` 45, `llm_disambiguation` 90, `judge_rejected` 21, `no_candidates` 48 — zero `judge_unavailable`, every escalation carries a real judge decision). Before this pass: 🟢44/🟡63/🔴97 with 8 yellow terms stuck unresolved (`judge_unavailable`/hand-patched `ambiguous_candidates`) — root cause was `data/seed/terminology_terms.jsonl` carrying `lemma == surface` (the raw inflected form) for most mentions, so candidate search missed the demo's own core entities (Mesopotamia/Babylon/Euphrates/Assyria/Sumer) on every non-nominative occurrence; fixed by [scripts/fix_mention_lemmas.py](../../scripts/fix_mention_lemmas.py) (nominative-lemma correction: `data/seed/lemmas.json` + an LLM lemmatizer pass for the surfaces it doesn't cover) before re-running the disambiguation.

Served as one document:

| Field | Value |
|---|---|
| Document title | `Mesopotamia — ancient Near East (pilot)` |
| Language pair | ru → en |
| Paragraphs | 15 |
| Criteria (evaluators) seeded | 4 — accuracy, fluency, style, terminology (Cultural Adaptation dropped wave-4 Б4; `consistency` present in source data but **not** seeded as an evaluator) |
| Issues (seed) | real, from `/evaluate`-generated baselines (see [terminology stage doc](../stages/terminology.md) and [known_issues.md](../known_issues.md) for the advice-guard corpus) |
| Terms | 204, real G6 `label_first` grounding + P1/P3 pairing output, `data/seed/terminology_out.json`, loaded via `scripts/load_terms.py` — difficulty breakdown above (single source: this file) |
| Paragraph 1 aggregate (baseline) | real, from the regenerated 15-paragraph seed (no longer the pre-refresh 6.44/10 figure) |

This is the seeded document (`origin='seed'`), always present and never deletable. There is no auth, no roles. The demo now also supports user-uploaded documents (`origin='upload'`) created live through the upload modal — see the "Upload a custom pair" journey below. The document switcher in the top bar lists both.

**⚠️ Picker curation flag (2026-07-16, owner UI review #1, `docs/superpowers/specs/2026-06-30-demo-contracts.md` "Document picker curation delta").** `GET /api/documents` (the picker list) now excludes `hidden=1` documents; `migrate.py`'s `_curate_demo_documents` hides any document whose title starts with `Mesopotamia` or `The Qin State` — **this seeded document's title matches that first prefix**, so it no longer appears in the landing picker on a curated DB, even though it is still fully present (`origin='seed'`, never deleted, scores/issues intact) and reachable directly via `GET /api/documents/{id}`. The curated picker's sole visible card is "World History — Selected Passages" (a separate `origin='upload'` document loaded via `scripts/create_demo_docs.py data/seed/demo_docs/mesopotamia-2.json`, not documented in this manifest — it was not part of the canonical e2e journey set below). **Journeys 1-7 below, written against the seed pilot document, are STALE as picker-driven journeys** on a curated DB until re-validated: they still work as a direct API/deep-link check, but a real click-through-the-picker e2e run will not find this document's card. Not re-authored here — that call (retarget journeys 1-7 at "World History", add a picker-visibility assertion, or something else) belongs to the next `/verify-pr`/e2e-tester pass, flagged honestly rather than guessed at by this backend-only change.

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
4. Restore a non-current revision: `target` reverts to that text, a NEW `origin='restore'` revision is written (restore is itself tracked, not a rewind), and — restoring does **not** copy the old score — the paragraph shows a "Scores are for a previous version — press Evaluate" stale-hint banner over the *last known* score (not a reset to "not scored") until the next explicit Evaluate. This corrects an earlier version of this line, which claimed the score resets to "not scored"; live behavior (confirmed [prod-stability-iter1 §3](../reports/e2e/prod-stability-iter1-2026-07-16.md), "Restore к более старой ревизии") keeps the last known score visible with the banner — more informative than a bare dash. The History-list refresh itself (fixed in an earlier wave, [wave5-run.md §4.1](../reports/e2e/wave5-run.md)) is confirmed working for Restore; the same staleness pattern applied to Document **Reset** (same paragraph id reused, so a `paragraph.id`-keyed refetch alone never re-fired) was found and fixed in frontend-developer-stability-wave2 via a client-side `documentResetNonce` the History block also keys its refetch on.
5. `export-btn` in the top bar opens `export-menu` with two items, `export-xlsx` and `export-md`; each downloads a file named `{slug}-{doc_id}.{ext}` (verified end-to-end in [wave5-run.md](../reports/e2e/wave5-run.md): xlsx round-trips through `openpyxl` — 15¶+header+meta rows, frozen header, score-colored cells; md is a valid GFM table).

## Campaign fixtures (2026-07-17 e2e mega-campaign)

Deterministic upload payloads for the [mega-campaign spec](../superpowers/specs/2026-07-17-e2e-mega-campaign.md)
scenarios T2/T5/T9, committed under [docs/testing/e2e-campaign/](e2e-campaign/) BEFORE the runs
(provenance requirement). Agents feed them through the upload modal (paste or file), never via curl.

| File | Scenario | Contents |
|---|---|---|
| `t2-zh-source.txt` | T2 | 5 CJK paragraphs (Qin/Han: 秦朝, 长城, 汉朝, 司马迁), CJK punctuation, no word spaces |
| `t2-en-translation.txt` | T2 | aligned EN translation (zh → en pair) |
| `t2-ru-translation.txt` | T2 | aligned RU translation (zh → ru second pass) |
| `t5-ru-source.txt` | T5 | 8 RU paragraphs of museum-temporal traps: Naram-Suen stele (Париж, Лувр), Ishtar Gate (Берлин), Standard of Ur (Лондон), Egyptian vs Greek Фивы, Memphis Egypt vs Tennessee jazz, Ханейское царство, приевфратские земли, ancient Babylon vs the Babylon site museum |
| `t5-en-translation.txt` | T5 | aligned EN translation |
| `gen_t9.py` | T9 | deterministic generator (no randomness) for all `t9-*` files below |
| `t9-ru-source.txt` / `t9-en-translation.txt` | T9 | exactly 40 aligned paragraphs; paragraph 21 exactly 4000 chars (both limits boundary-exact) |
| `t9-neg-41para-ru.txt` / `-en.txt` | T9 | 41 paragraphs — creation must be rejected (maxParagraphs=40) |
| `t9-neg-4001char-ru.txt` / `-en.txt` | T9 | one 4001-char paragraph — creation must be rejected (maxParaChars=4000) |

Expected-QID reference for T5 (checked live 2026-07-17): Париж→Q90, Ханейское царство→Q425405
(label-guess tier), Фивы(Египет)→Q101583, Фивы(Греция)→Q11225429 (corrected during the T5 run:
this line originally said Q41621, which is Haifa — the run's own finding #5), Мемфис(Египет)→Q5715,
Мемфис(Теннесси)→Q16563, Вавилон→Q5684. A modern-museum location term grounded to the modern
city/institution is CORRECT (judge-prompt temporal caveat).

## Out of scope (do not test / do not seed)

- Live model inference on the seeded document (no key — see above).
- The legacy LLM-Comparator viewer and old pipeline branches (untouched, not part of this app).
- DB-seeding shortcuts via URL — drive everything through the UI, including document creation (`POST /api/documents` only via the upload modal, never a raw `fetch`/`curl` from the test).
