"""Additive, idempotent schema migration for a live prod DB (spec S5 §2.4).

There is no migration framework in this project — ``db.py::SCHEMA`` is the
source of truth for FRESH databases (``init_db(reset=True)``), and this module
is the source of truth for bringing an EXISTING (already-populated) database
up to the same shape without a reseed. Every step here is safe to run twice:
``CREATE TABLE IF NOT EXISTS``, a ``PRAGMA table_info`` guard before
``ALTER TABLE ... ADD COLUMN``, and an existence check before any INSERT.

Called from two places: ``app.py`` at startup (before serving requests) and
the ``python -m palimpsest.webapp.migrate`` CLI (manual prod run).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from .. import paths
from ..terminology.grounding.label_first import DEFAULT_GROUNDING_JUDGE_PROMPT
from . import db
from .aggregate import compute_aggregate
from .model_matrix import DEFAULT_CRITERION_MODEL, MATRIX

logger = logging.getLogger(__name__)

TRANSLATOR_PROMPT_FILE = paths.PROMPTS / "translator" / "default.md"
TRANSLATOR_DEFAULT_PARAMS = {"max_tokens": 2048, "temperature": 0.3}
GROUNDING_DEFAULT_PARAMS = {"max_tokens": 512, "temperature": 0}
REFINER_PROMPT_FILE = paths.PROMPTS / "refiner" / "default.md"
# max_tokens=4096 (was 2048): the refiner rewrites a full paragraph in one
# pass, and the demo default model (gemini-3.1-flash-lite, EMNLP sprint
# 2026-07-16) has obligatory reasoning that shares the same token budget —
# 2048 was tight enough to starve visible output on some paragraphs. See
# docs/known_issues.md "qwen as refiner returns empty output" for why the
# model itself moved off qwen the same day.
REFINER_DEFAULT_PARAMS = {"max_tokens": 4096, "temperature": 0.2}

# EMNLP demo sprint (2026-07-11): criteria collapsed to {accuracy, fluency,
# style}; 'terminology' (the LLM-judge scoring dimension, NOT the separate
# Wikidata term-grounding pipeline) and the already-disabled legacy 'cultural'
# row both retire. Weight scheme moves 0.30/0.20/0.15(+0.20 terminology) to
# 0.40/0.30/0.30 — see docs/superpowers/specs/2026-06-30-demo-contracts.md
# rev-6 delta.
_REMOVED_CRITERION_IDS = ("terminology", "cultural")
_CRITERION_WEIGHT_MIGRATION = {  # id -> (old default, new default); only
    "accuracy": (0.30, 0.40),    # touched when a row still carries the OLD
    "fluency": (0.20, 0.30),     # value, so a Settings-edited weight (neither
    "style": (0.15, 0.30),       # old nor new default) is left alone
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _create_target_revision(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS target_revision ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,"
        "text TEXT NOT NULL,"
        "origin TEXT NOT NULL,"
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_target_revision_para ON target_revision(paragraph_id, id)"
    )


def _create_translator_config(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS translator_config ("
        "id INTEGER PRIMARY KEY CHECK (id = 1),"
        "model_name TEXT REFERENCES model(name),"
        "prompt TEXT,"
        "params_json TEXT)"
    )
    row = conn.execute("SELECT 1 FROM translator_config WHERE id=1").fetchone()
    if row is not None:
        return
    # Only seed the default row if its target model already exists — model_name
    # is FK-constrained, and a bare fresh/test DB may not have any model rows
    # yet (e.g. a schema-only fixture). GET /api/translator-config already
    # handles an absent row (mirrors grounding_config's None-row path).
    model_exists = conn.execute(
        "SELECT 1 FROM model WHERE name=?", (DEFAULT_CRITERION_MODEL,)).fetchone()
    if not model_exists:
        return
    if not TRANSLATOR_PROMPT_FILE.exists():
        return
    prompt = TRANSLATOR_PROMPT_FILE.read_text(encoding="utf-8")
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, prompt, json.dumps(TRANSLATOR_DEFAULT_PARAMS)))


def _create_grounding_config(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS grounding_config ("
        "id INTEGER PRIMARY KEY CHECK (id = 1),"
        "model_name TEXT REFERENCES model(name),"
        "prompt TEXT,"
        "params_json TEXT)"
    )
    row = conn.execute("SELECT 1 FROM grounding_config WHERE id=1").fetchone()
    if row is not None:
        return
    # Same FK-safety guard as _create_translator_config: model_name is
    # FK-constrained, so only seed the default row when its target model
    # already exists. GET /api/grounding-config already tolerates an absent
    # row (returns a null/default config, never 500).
    model_exists = conn.execute(
        "SELECT 1 FROM model WHERE name=?", (DEFAULT_CRITERION_MODEL,)).fetchone()
    if not model_exists:
        return
    conn.execute(
        "INSERT INTO grounding_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, DEFAULT_GROUNDING_JUDGE_PROMPT, json.dumps(GROUNDING_DEFAULT_PARAMS)))


def _create_refiner_config(conn: sqlite3.Connection) -> None:
    """Mirrors _create_translator_config exactly — the refiner role (paper: "a
    dedicated refiner LLM integrates aggregated corrections in a single
    pass") is a singleton config table just like the translator's."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS refiner_config ("
        "id INTEGER PRIMARY KEY CHECK (id = 1),"
        "model_name TEXT REFERENCES model(name),"
        "prompt TEXT,"
        "params_json TEXT)"
    )
    row = conn.execute("SELECT 1 FROM refiner_config WHERE id=1").fetchone()
    if row is not None:
        return
    # Same FK-safety guard as _create_translator_config/_create_grounding_config.
    model_exists = conn.execute(
        "SELECT 1 FROM model WHERE name=?", (DEFAULT_CRITERION_MODEL,)).fetchone()
    if not model_exists:
        return
    if not REFINER_PROMPT_FILE.exists():
        return
    prompt = REFINER_PROMPT_FILE.read_text(encoding="utf-8")
    conn.execute(
        "INSERT INTO refiner_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, prompt, json.dumps(REFINER_DEFAULT_PARAMS)))


def _create_glossary(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS glossary ("
        "id INTEGER PRIMARY KEY,"
        "term TEXT, context TEXT, target_equivalent TEXT,"
        "wikidata_url TEXT NOT NULL, wikidata_id TEXT,"
        "UNIQUE (term, context))"
    )


def _add_term_trace_json_column(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "term", "trace_json"):
        # NOT NULL DEFAULT '{}' matches db.py SCHEMA and backfills every
        # existing row with '{}' in the same ALTER TABLE (SQLite fills a
        # constant default into pre-existing rows) — no separate backfill step.
        conn.execute("ALTER TABLE term ADD COLUMN trace_json TEXT NOT NULL DEFAULT '{}'")


def _add_score_revision_column(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "score", "revision_id"):
        conn.execute(
            "ALTER TABLE score ADD COLUMN revision_id INTEGER REFERENCES target_revision(id)")


def _add_document_terms_status_column(conn: sqlite3.Connection) -> None:
    """2026-07-11 EMNLP sprint (live terminology pipeline): 'none'|'running'|
    'done'|'failed', see terminology_live.py. NOT NULL DEFAULT 'none' matches
    db.py SCHEMA and backfills every existing row via the ALTER's DEFAULT —
    same pattern as _add_term_trace_json_column."""
    if not _has_column(conn, "document", "terms_status"):
        conn.execute("ALTER TABLE document ADD COLUMN terms_status TEXT NOT NULL DEFAULT 'none'")


def _backfill_seed_document_terms_status(conn: sqlite3.Connection) -> None:
    """The seeded demo document already has precomputed terms (loaded by
    scripts/load_terms.py, not by the live pipeline) — mark it 'done' so the
    frontend never shows it as pending. Idempotent (a 'done' row is simply
    left unchanged); runs unconditionally, unlike the FK-guarded config
    seeds above, since 'origin=seed' rows are safe to touch regardless of
    whether any model row exists yet."""
    conn.execute("UPDATE document SET terms_status='done' WHERE origin='seed' AND terms_status!='done'")


# Owner picker curation (2026-07-16, UI review #1): keep only "World History —
# Selected Passages" in the picker; hide the other two demo documents. Title
# prefixes, not hardcoded ids — robust across a fresh-seed DB and an existing
# prod DB alike (see _curate_demo_documents below).
_DEMO_DOC_HIDE_TITLE_PREFIXES = ("Mesopotamia", "The Qin State")
_DEMO_DOC_TITLE_SUFFIXES_TO_STRIP = (" (Draft Translation)", " (pilot)")


def _add_document_hidden_column(conn: sqlite3.Connection) -> None:
    """Picker curation flag (2026-07-16, UI review #1) — hides a retired demo
    document from GET /api/documents (the picker list) while leaving it fully
    intact: GET /api/documents/{id} (deep link) still returns it, and its
    score/issue rows are never touched (owner hard invariant against deleting
    predictions, .claude/rules/invariants.md). NOT NULL DEFAULT 0 matches
    db.py SCHEMA and backfills every existing row to visible via the ALTER's
    DEFAULT — same pattern as _add_term_trace_json_column/
    _add_document_terms_status_column above."""
    if not _has_column(conn, "document", "hidden"):
        conn.execute("ALTER TABLE document ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")


def _curate_demo_documents(conn: sqlite3.Connection) -> None:
    """Apply the owner's picker curation decision (2026-07-16, UI review #1):
    hide "Mesopotamia ..." (the original seed.py document) and "The Qin
    State ..." (a create_demo_docs.py upload), keep only "World History —
    Selected Passages" visible. Matches by TITLE, never a hardcoded id — the
    same title strings appear whether the DB came from a fresh seed.py +
    create_demo_docs.py run (titles already clean at the source) or an
    existing prod DB (may still carry a decorative "(Draft Translation)"/
    "(pilot)" suffix predating this fix).

    Idempotent both halves: the suffix-strip only rewrites a title that still
    ends with a known decorative suffix (a no-op once stripped), and hiding
    is a flag flip guarded by `hidden!=1` (a no-op once already hidden).
    NEVER deletes or otherwise touches `score`/`issue` — hiding is purely a
    `document.hidden` flag flip on the `document` row itself."""
    # 1) General suffix strip -- not hardcoded to one document's title, so it
    #    also cleans a pre-fix prod "... (pilot)" row from seed.py, not just
    #    the World History upload's "... (Draft Translation)" title.
    for row in conn.execute("SELECT id, title FROM document").fetchall():
        title = row["title"] or ""
        cleaned = title
        for suffix in _DEMO_DOC_TITLE_SUFFIXES_TO_STRIP:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)]
        if cleaned != title:
            conn.execute("UPDATE document SET title=? WHERE id=?", (cleaned, row["id"]))

    # 2) Hide by title prefix -- flag flip only, never a DELETE.
    for prefix in _DEMO_DOC_HIDE_TITLE_PREFIXES:
        conn.execute(
            "UPDATE document SET hidden=1 WHERE title LIKE ? AND hidden!=1", (f"{prefix}%",))


# Owner cleanup (2026-07-16, UI review #7): the curated demo document's title
# AFTER _curate_demo_documents has run (must run first — this matches the
# already-renamed canonical title, not the pre-rename "(Draft Translation)"
# one). Gated to this ONE document, not all docs, per the owner's request.
_REVISION_CLEANUP_DOC_TITLE = "World History — Selected Passages"


def _prune_orphan_revisions(conn: sqlite3.Connection) -> None:
    """Prune stale, never-scored ``target_revision`` rows for the curated
    demo document's paragraphs only (owner UI review #7: "N hours ago · not
    scored" test-edit revisions cluttering Revision History). Gated by TITLE
    to ``_REVISION_CLEANUP_DOC_TITLE`` — not all documents.

    A revision is pruned iff ALL of: (i) it is not the earliest (seed)
    revision of its paragraph, (ii) it is not the LATEST revision of its
    paragraph — ``db.latest_revision_id`` (MAX(id)) is what the API marks as
    CURRENT in Revision History and ``paragraph.target`` carries that text,
    so pruning it would leave the CURRENT badge pointing at an older row
    whose text no longer matches the live paragraph — AND (iii) no
    ``score.revision_id`` row points at it — i.e. it is a purely orphan
    middle-of-history text edit nobody ever scored. A revision any
    ``score`` row references is never touched, by construction — the query
    that builds the candidate set explicitly excludes every id currently
    referenced by ``score.revision_id`` (checked as a single global set, not
    scoped to this document, so this can never race a scored revision from
    being miscounted). This is the ONLY table with a foreign key into
    ``target_revision`` (``db.py`` SCHEMA) — no other reference to check.

    Predictions are irreproducible (owner hard invariant, .claude/rules/
    invariants.md): this function deletes `target_revision` rows only, never
    `score`/`issue`, and both connections this runs on (``db.connect()`` and
    every ``sqlite3.connect()`` caller in this module's own tests) keep
    ``PRAGMA foreign_keys=ON`` — if a future edit to this function's
    candidate-set logic ever let a still-referenced revision slip through,
    the ``DELETE`` would raise ``IntegrityError`` immediately rather than
    silently orphaning a score row's FK.

    Idempotent: once the orphans for this document are gone, a second run
    finds none left to delete (a no-op) — safe to re-run every deploy."""
    doc = conn.execute(
        "SELECT id FROM document WHERE title=?", (_REVISION_CLEANUP_DOC_TITLE,)).fetchone()
    if doc is None:
        return
    pids = [r["id"] for r in conn.execute(
        "SELECT id FROM paragraph WHERE document_id=?", (doc["id"],))]
    if not pids:
        return
    placeholders = ",".join("?" for _ in pids)
    earliest_ids = {
        r["earliest_id"] for r in conn.execute(
            f"SELECT MIN(id) AS earliest_id FROM target_revision "
            f"WHERE paragraph_id IN ({placeholders}) GROUP BY paragraph_id", pids)}
    latest_ids = {
        r["latest_id"] for r in conn.execute(
            f"SELECT MAX(id) AS latest_id FROM target_revision "
            f"WHERE paragraph_id IN ({placeholders}) GROUP BY paragraph_id", pids)}
    scored_ids = {
        r["revision_id"] for r in conn.execute(
            "SELECT DISTINCT revision_id FROM score WHERE revision_id IS NOT NULL")}
    orphans = [
        r["id"] for r in conn.execute(
            f"SELECT id FROM target_revision WHERE paragraph_id IN ({placeholders})", pids)
        if r["id"] not in earliest_ids and r["id"] not in latest_ids
        and r["id"] not in scored_ids]
    if not orphans:
        return
    ph2 = ",".join("?" for _ in orphans)
    conn.execute(f"DELETE FROM target_revision WHERE id IN ({ph2})", orphans)
    logger.info("pruned %d orphan (never-scored) revision row(s) for document %r",
                len(orphans), _REVISION_CLEANUP_DOC_TITLE)


def _backfill_paragraph_revisions(conn: sqlite3.Connection) -> None:
    """Every paragraph without a single ``target_revision`` row gets one,
    seeded from its current ``target`` text — so a migrated prod DB and a
    freshly-seeded dev/test DB have the same *shape* of history (spec S5
    §2.1 point 7 mirrors this for seed.py)."""
    ts = _now()
    missing = conn.execute(
        "SELECT p.id, p.target FROM paragraph p "
        "LEFT JOIN target_revision r ON r.paragraph_id = p.id "
        "WHERE r.id IS NULL"
    ).fetchall()
    for p in missing:
        conn.execute(
            "INSERT INTO target_revision(paragraph_id,text,origin,created_at) VALUES(?,?,?,?)",
            (p["id"], p["target"], "seed", ts))


def _upsert_model_registry_and_remap(conn: sqlite3.Connection) -> None:
    """Ensure the current 4-row MATRIX exists in `model` and every `criterion`
    row points at a valid model (EMNLP demo sprint, 2026-07-11).
    `INSERT OR IGNORE` — never clobbers an api_key/params an owner already
    edited via Settings on a prior migrate() run; `model`/`criterion` are base
    tables, always present, so this is safe to run first.

    Durability fix (2026-07-16): only remap a criterion whose `model_name` is
    NULL (never configured — use the default) or points at a RETIRED model
    (not in the current MATRIX, e.g. a pre-2026-07-11 row about to be pruned
    by `_prune_obsolete_model_rows`). A criterion an operator deliberately
    pointed at a current-MATRIX model (e.g. gemini) must survive every
    restart — the old `model_name != DEFAULT_CRITERION_MODEL` predicate
    clobbered that choice back to the default on every migrate() run, which
    is every app startup (app.py lifespan)."""
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    for spec in MATRIX.values():
        conn.execute(
            "INSERT OR IGNORE INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
            (spec.name, spec.base_url, or_key if spec.is_openrouter else "",
             json.dumps(spec.default_params)))
    matrix_names = tuple(MATRIX.keys())
    placeholders = ",".join("?" for _ in matrix_names)
    conn.execute(
        f"UPDATE criterion SET model_name=? "
        f"WHERE model_name IS NULL OR model_name NOT IN ({placeholders})",
        (DEFAULT_CRITERION_MODEL, *matrix_names))


def _remap_singleton_config_model_refs(conn: sqlite3.Connection) -> None:
    """translator_config/grounding_config/refiner_config.model_name each FK to
    model(name) — repoint any of them still pointing at a RETIRED (not in the
    current MATRIX) model row to the new registry default, now that the old
    rows are about to be pruned (_prune_obsolete_model_rows). Runs after the
    three _create_*_config steps, so all three tables are guaranteed to exist
    by now.

    Durability fix (2026-07-16): the predicate used to be `model_name !=
    DEFAULT_CRITERION_MODEL`, which reverted an operator's deliberate,
    still-valid model choice (e.g. gemini) back to the default on every
    migrate() run — migrate() runs on every app startup, so a restart/redeploy
    silently undid a Settings-page choice. Only a genuinely retired model
    (NOT IN the current MATRIX) gets repointed now; any current-MATRIX value
    is preserved."""
    matrix_names = tuple(MATRIX.keys())
    placeholders = ",".join("?" for _ in matrix_names)
    for table in ("translator_config", "grounding_config", "refiner_config"):
        conn.execute(
            f"UPDATE {table} SET model_name=? "
            f"WHERE id=1 AND model_name IS NOT NULL AND model_name NOT IN ({placeholders})",
            (DEFAULT_CRITERION_MODEL, *matrix_names))


def _recompute_aggregates_for_remaining_criteria(
        conn: sqlite3.Connection, remaining: list[sqlite3.Row]) -> None:
    """Every score row's frozen `aggregate`/`criteria_key` was computed over
    whatever criterion set was enabled AT SCORING TIME — once terminology/
    cultural are gone, an un-recomputed old value would still (silently)
    weight a criterion that no longer exists, and its `criteria_key` would
    forever read as "a different criterion set" against any fresh evaluate.
    Recompute in place, per paragraph, over the CURRENT (remaining) criteria.

    'seed'/'cache' are each a single pass per paragraph (seed.py writes every
    criterion's row in one loop) — grouping by (paragraph_id, kind) is exact.
    'live' can have MULTIPLE passes over time (partial re-evaluates); replay
    them in created_at order, carrying the latest-known value per surviving
    criterion forward pass-to-pass — the same "latest overridden by fresh
    successes" carry-forward evaluate() itself uses (app.py).
    """
    if not remaining:
        return
    remaining_ids = {r["id"] for r in remaining}
    pids = [r["paragraph_id"] for r in conn.execute("SELECT DISTINCT paragraph_id FROM score")]
    for pid in pids:
        for kind in ("seed", "cache"):
            rows = conn.execute(
                "SELECT * FROM score WHERE paragraph_id=? AND kind=?", (pid, kind)).fetchall()
            values = {r["criterion_id"]: r["value"] for r in rows
                      if r["criterion_id"] in remaining_ids}
            if not values:
                continue
            agg, ckey = compute_aggregate(values, remaining)
            ph = ",".join("?" for _ in values)
            conn.execute(
                f"UPDATE score SET aggregate=?, criteria_key=? "
                f"WHERE paragraph_id=? AND kind=? AND criterion_id IN ({ph})",
                (agg, ckey, pid, kind, *values.keys()))

        live_rows = conn.execute(
            "SELECT * FROM score WHERE paragraph_id=? AND kind='live' ORDER BY created_at, id",
            (pid,)).fetchall()
        running: dict[str, float] = {}
        seen_ts: list[str] = list(dict.fromkeys(r["created_at"] for r in live_rows))
        for ts in seen_ts:
            pass_rows = [r for r in live_rows if r["created_at"] == ts]
            pass_ids = [r["criterion_id"] for r in pass_rows if r["criterion_id"] in remaining_ids]
            for r in pass_rows:
                if r["criterion_id"] in remaining_ids:
                    running[r["criterion_id"]] = r["value"]
            if not pass_ids:
                continue  # this pass touched only a since-removed criterion — nothing of ours here
            agg, ckey = compute_aggregate(running, remaining)
            ph = ",".join("?" for _ in pass_ids)
            conn.execute(
                f"UPDATE score SET aggregate=?, criteria_key=? "
                f"WHERE paragraph_id=? AND kind='live' AND created_at=? AND criterion_id IN ({ph})",
                (agg, ckey, pid, ts, *pass_ids))


def _reduce_to_three_criteria(conn: sqlite3.Connection) -> None:
    """Collapse the criterion set to {accuracy, fluency, style} (EMNLP demo
    sprint, 2026-07-11). Idempotent: every step is guarded by current-state
    checks, so re-running once the removed rows are already gone is a no-op.

    Predictions are irreproducible (owner hard invariant, .claude/rules/
    invariants.md) — score/issue rows for the retired criteria are archived,
    never deleted. 'archived' is the status `_para_issues` (app.py)
    unconditionally drops on every branch — confirmed against its status
    handling and the IssueStatus contract note in demo-contracts.md §1 before
    picking it; 'dismissed' would still surface as inspector history and leak
    a dangling criterionId to the wire once the criterion row is gone.
    """
    placeholders = ",".join("?" for _ in _REMOVED_CRITERION_IDS)
    present = [r["id"] for r in conn.execute(
        f"SELECT id FROM criterion WHERE id IN ({placeholders})", _REMOVED_CRITERION_IDS)]
    if present:
        ph2 = ",".join("?" for _ in present)
        conn.execute(
            f"UPDATE score SET kind='archived' WHERE criterion_id IN ({ph2}) AND kind!='archived'",
            present)
        conn.execute(
            f"UPDATE issue SET status='archived' "
            f"WHERE criterion_id IN ({ph2}) AND status!='archived'",
            present)
        # FK (score/issue.criterion_id -> criterion.id, both default ON DELETE
        # NO ACTION) blocks the parent DELETE while those rows still reference
        # it — by design, they still do (archived, not deleted). PRAGMA
        # foreign_keys is a documented no-op while a transaction is open
        # (sqlite.org/pragma.html#pragma_foreign_keys) — commit first, or the
        # toggle below silently does nothing and DELETE raises
        # IntegrityError instead of succeeding. Re-enabled in a `finally` and
        # re-committed immediately, so the OFF window is as narrow as
        # possible; migrate() only ever runs single-threaded before the app
        # serves its first request (or via the standalone CLI), so no
        # concurrent request can observe FK enforcement being briefly off.
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute(f"DELETE FROM criterion WHERE id IN ({ph2})", present)
            conn.commit()
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    for cid, (old_w, new_w) in _CRITERION_WEIGHT_MIGRATION.items():
        conn.execute(
            "UPDATE criterion SET weight=? WHERE id=? AND weight=?", (new_w, cid, old_w))

    remaining = conn.execute(
        f"SELECT * FROM criterion WHERE id NOT IN ({placeholders})",
        _REMOVED_CRITERION_IDS).fetchall()
    _recompute_aggregates_for_remaining_criteria(conn, remaining)


def _prune_obsolete_model_rows(conn: sqlite3.Connection) -> None:
    """Delete registry rows outside the current 4-model MATRIX, once nothing
    references them any more (criterion/translator_config/grounding_config/
    refiner_config were all repointed to the new default above) — model rows
    are config, not predictions, so deletion (unlike score/issue) is fine.
    The reference re-check is defensive: if some future caller adds a new FK
    to model(name) without updating this list, a still-referenced row is
    silently skipped rather than raising IntegrityError mid-migration."""
    names = tuple(MATRIX.keys())
    placeholders = ",".join("?" for _ in names)
    obsolete = [r["name"] for r in conn.execute(
        f"SELECT name FROM model WHERE name NOT IN ({placeholders})", names)]
    for name in obsolete:
        still_referenced = conn.execute(
            "SELECT 1 FROM criterion WHERE model_name=? "
            "UNION SELECT 1 FROM translator_config WHERE model_name=? "
            "UNION SELECT 1 FROM grounding_config WHERE model_name=? "
            "UNION SELECT 1 FROM refiner_config WHERE model_name=? LIMIT 1",
            (name, name, name, name)).fetchone()
        if still_referenced:
            continue
        conn.execute("DELETE FROM model WHERE name=?", (name,))


def migrate(conn: sqlite3.Connection) -> None:
    """Run every additive step, in order, and commit once at the end."""
    _upsert_model_registry_and_remap(conn)
    _create_target_revision(conn)
    _create_translator_config(conn)
    _create_grounding_config(conn)
    _create_refiner_config(conn)
    _create_glossary(conn)
    _add_term_trace_json_column(conn)
    _add_score_revision_column(conn)
    _backfill_paragraph_revisions(conn)
    _add_document_terms_status_column(conn)
    _backfill_seed_document_terms_status(conn)
    _add_document_hidden_column(conn)
    _curate_demo_documents(conn)
    _prune_orphan_revisions(conn)
    _remap_singleton_config_model_refs(conn)
    _reduce_to_three_criteria(conn)
    _prune_obsolete_model_rows(conn)
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Additively migrate the Glossa-MT demo SQLite DB in place "
                    "(idempotent — safe to run repeatedly against a live prod DB).")
    parser.parse_args()
    conn = db.connect()
    migrate(conn)
    print(f"migrated {db.DB_PATH}")


if __name__ == "__main__":
    main()
