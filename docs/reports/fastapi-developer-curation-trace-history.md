# fastapi-developer — grounding trace strategy, document picker curation, revision cleanup

Worktree: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`, branch `feat/emnlp-demo-sprint`.
Lane: backend only (`src/palimpsest/webapp/**`, `src/palimpsest/terminology/grounding/candidates.py`, tests, doc-parity). No frontend files touched (confirmed via `git status` — the frontend diffs present belong to a concurrent agent).

## Scope

Three independent tasks from the owner's screenshot review of the live picker/Revision History:

1. **Task #4** — label each grounding query's search strategy (`prefix`/`cirrus`/`sitelink`) in `GroundingTrace.queries[]` so a 5-call trace for a 2-word mention reads as an escalation ladder, not repetition.
2. **Task #1** — hide "Mesopotamia …" and "The Qin State …" from the document picker, keep only "World History — Selected Passages" visible, without deleting anything.
3. **Task #7** — prune orphan "not scored" `target_revision` rows for that one curated document, never touching a revision any `score` row references.

## Files changed

Backend:
- [src/palimpsest/terminology/grounding/candidates.py](../../src/palimpsest/terminology/grounding/candidates.py) — `"strategy"` key on every `queries[]` entry.
- [src/palimpsest/webapp/db.py](../../src/palimpsest/webapp/db.py) — `document.hidden INTEGER NOT NULL DEFAULT 0` in fresh-DB `SCHEMA`.
- [src/palimpsest/webapp/migrate.py](../../src/palimpsest/webapp/migrate.py) — `_add_document_hidden_column`, `_curate_demo_documents`, `_prune_orphan_revisions` (+ module `logger`), wired into `migrate()` in that order.
- [src/palimpsest/webapp/app.py](../../src/palimpsest/webapp/app.py) — `list_documents` (`GET /api/documents`) adds `WHERE hidden=0`; `GET /api/documents/{id}` unchanged.
- [src/palimpsest/webapp/seed.py](../../src/palimpsest/webapp/seed.py) — seed document title cleaned (`"... (pilot)"` suffix dropped); `hidden` left at its schema default, matching the existing `terms_status` precedent (migrate() is the single decider for both).
- [data/seed/demo_docs/mesopotamia-2.json](../../data/seed/demo_docs/mesopotamia-2.json) — title cleaned at the source (`"... (Draft Translation)"` dropped).
- [scripts/create_demo_docs.py](../../scripts/create_demo_docs.py) — stale `app.py` line-number reference in the docstring corrected (unrelated drift noticed while reading the file).

Tests (all new/added, all green):
- [tests/test_terminology.py](../../tests/test_terminology.py) — 1 new test (`test_candidates_query_strategy_labels_escalation_ladder`).
- [tests/test_document_curation.py](../../tests/test_document_curation.py) — 8 new tests (app-level filtering + migrate-level curation, idempotency, score/issue non-interference).
- [tests/test_revision_cleanup.py](../../tests/test_revision_cleanup.py) — 7 new tests (the exact required `[seed, orphan, scored] → [seed, scored]` scenario, idempotency, title-gating, FK safety, full-pipeline ordering).

Docs (doc-parity, same change):
- [docs/stages/terminology.md](../../docs/stages/terminology.md) — `queries[]` shape note extended with `strategy`.
- [docs/superpowers/specs/2026-06-30-demo-contracts.md](../../docs/superpowers/specs/2026-06-30-demo-contracts.md) — 3 new dated delta sections: "Grounding-trace strategy label delta", "Document picker curation delta", "Revision-history cleanup delta".
- [docs/subsystems/webapp.md](../../docs/subsystems/webapp.md) — `migrate.py` row + "Revision history & best" section updated.
- [docs/testing/e2e-data.md](../../docs/testing/e2e-data.md) — flag note: journeys 1-7 (written against the now-hidden seed document) are stale as picker-driven steps on a curated DB; NOT re-authored here (out of this task's scope, explicitly handed to the next e2e pass).

## Decisions & rationale

**Task #4 — strategy labeling.** Exactly 4 places append to `queries[]`; 3 map 1:1 to distinct `mechanism` values (`wbsearchentities`→`prefix`, `cirrus`→`cirrus`, `wikipedia_wikibase_item`→`sitelink`) as the task specified. The 4th site — the `_widen()` helper used by the non-baseline `search_mode="alt-names"/"label-guess"` widening tiers — also calls `wd.search_entities` (the same `wbsearchentities` backend), so I labeled it `"prefix"` too rather than leaving it without a `strategy` key. Rationale: the frontend contract is "values are exactly `prefix|cirrus|sitelink`" — leaving one call site without the key would force a 4th undefined case in the UI for no reason, and the label is mechanically accurate (same backend, different derived query form). `kind` still distinguishes the tier (`"alt"`/`"label_guess"`) from `strategy` (the backend) — two independent axes, not a collision.

**Task #1 — where `hidden` gets set.** I deliberately did **not** hardcode `hidden=1` on `seed.py`'s own INSERT. I initially did, then reverted after finding the exact precedent already in this codebase: `seed.py` also doesn't set `document.terms_status='done'` directly — `migrate.py`'s `_backfill_seed_document_terms_status` is the sole place that finalizes it, every app startup, for a freshly-seeded DB exactly as for a migrated prod one. I followed that same pattern for `hidden`: `_curate_demo_documents` (title-prefix match, idempotent) is the single source of truth; `seed.py` only cleans its title at the source. This avoids duplicating curation logic/constants across two files.

**Task #1 — title match, not id.** `_curate_demo_documents` matches `title LIKE 'Mesopotamia%'` / `'The Qin State%'`, and separately strips `" (Draft Translation)"`/`" (pilot)"` suffixes generically (not hardcoded to one document) before the hide step — so it's correct whether it runs against a freshly-seeded DB (titles already clean) or an existing prod DB (may still carry the old decorative suffix). Verified the exact real title strings by reading `data/seed/demo_docs/{mesopotamia-2,qin-state}.json` rather than guessing — `mesopotamia-2.json`'s title is actually **"World History — Selected Passages (Draft Translation)"** (the filename is misleading), `qin-state.json`'s is **"The Qin State — Ancient China"**.

**Task #1 — a real consequence, flagged not hidden.** `docs/testing/e2e-data.md`'s canonical journeys 1-7 are written against the seed pilot document, which is now hidden from the picker by this same title rule (its title starts with "Mesopotamia"). The document is still present, never deleted, still reachable by deep link — but a real picker click-through e2e run will no longer find its card. I added an explicit flag note to the manifest rather than silently rewriting the journeys against "World History" (I have no verified data about that document's paragraph count/criteria/issue content, and redesigning the e2e strategy is outside a backend-only task's mandate — it belongs to the next `/verify-pr`/e2e-tester pass).

**Task #7 — ordering matters.** `_prune_orphan_revisions` is gated by an *exact* title match to the canonical curated title, so it must run strictly after `_curate_demo_documents` (which performs the rename) in `migrate()`'s step order — verified with a dedicated end-to-end test (`test_full_migrate_pipeline_prunes_after_curation_rename`) that seeds a document with the **pre-rename** title and confirms both the rename and the prune still apply correctly through the full pipeline.

**Task #7 — safety construction, not just an FK catch.** The candidate-deletion set explicitly excludes every id present in `SELECT DISTINCT revision_id FROM score WHERE revision_id IS NOT NULL` — a scored revision is never even attempted, by construction — with `PRAGMA foreign_keys=ON` as a second, independent line of defense (proven directly in `test_target_revision_fk_enforced_deleting_a_scored_revision_directly_raises`, which shows that even a raw un-gated `DELETE` on a scored revision would raise `IntegrityError` under this schema).

## Open questions

None blocking. One judgment call worth the owner's attention: e2e journeys 1-7 in `docs/testing/e2e-data.md` need re-targeting at "World History — Selected Passages" (or an explicit "picker now starts on this document" rewrite) at the next e2e pass — flagged in the manifest itself, not resolved here.

## NOT done (explicit)

- **Did not rewrite `docs/testing/e2e-data.md` journeys 1-7** against the new visible document — flagged only, per the reasoning above.
- **Did not run a real browser/e2e pass** — this was a backend-only task; only `pytest` was run (see below). No LLM/network calls were made anywhere (all Wikidata/LLM interactions in tests use fakes/mocks, per the task's mock-only constraint).
- **Did not touch `frontend/`** — out of lane per the task's explicit instruction; the frontend `git status` diffs present belong to a concurrent agent.
- **Did not run `create_demo_docs.py`** against any server (would require a live app + network) — its JSON payload source files were edited directly instead.
- Did not modify `POST /api/documents` / `CreateDocumentBody` to accept a `hidden` field — deliberately out of scope; only `migrate.py`'s title-matched curation step decides `hidden` state, per the task's own instruction ("Match by TITLE... not hardcoded id").

## Test run (ran, not simulated)

```
$ .venv/bin/python -m pytest -q
598 passed in 5.53s
```

Before this change the suite was at 582 passed (598 − 16 new: 1 in `test_terminology.py`, 8 in `test_document_curation.py`, 7 in `test_revision_cleanup.py`); 0 failures, 0 skips, no flakes across two repeated runs. `ruff check` run on every touched/new file — all NEW lines are clean; a handful of pre-existing `E501`/`B008`/`UP017` violations in `app.py`/`seed.py`/`db.py`/`migrate.py`/`candidates.py` predate this change (confirmed via `git diff` — not on any line I added) and were left alone per the "no surrounding cleanup" convention.

## Confirmation: no score/issue row is ever deleted

Checked explicitly, both by code construction and by test:
- `_curate_demo_documents` (migrate.py) only ever runs `UPDATE document SET title=...` / `UPDATE document SET hidden=1 ...` — no `DELETE` statement touches `document`, `score`, or `issue` anywhere in this function. Proven by `test_curate_demo_documents_never_touches_scores_or_issues` (byte-for-byte `dict()` comparison of the `score`/`issue` rows before and after, plus row-count assertions).
- `_prune_orphan_revisions` (migrate.py) only ever runs `DELETE FROM target_revision WHERE id IN (...)` — never touches `score` or `issue`, and the candidate set is built to exclude every revision any `score.revision_id` references, before the `DELETE` is even issued. Proven by `test_prune_orphan_revisions_keeps_seed_and_scored_only` (score row untouched + count stays 1) and `test_target_revision_fk_enforced_deleting_a_scored_revision_directly_raises` (schema-level proof).
- `GET /api/documents` filtering (`app.py`) is a pure `SELECT ... WHERE hidden=0` — read-only, no mutation.
