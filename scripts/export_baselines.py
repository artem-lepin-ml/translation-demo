"""Export judge baselines from the throwaway webapp DB into the seed JSONL (Phase B).

Reads the most recent ``score``/``issue`` rows (``kind='live'``, written by a
local ``/evaluate`` run over the 15 rebuilt paragraphs) and writes them into
``data/seed/seed_paragraphs.jsonl`` as the new baseline criterion blocks.
Read-only against the DB; only the seed JSONL is modified.

Matching is by exact ``paragraph.source`` text (same convention as
``scripts/load_terms.py:db_by_source``) — the seed JSONL and the DB paragraph
rows come from the same rebuild, so source text is a reliable join key.

Run: ``PALIMPSEST_DB=<throwaway.db> uv run python scripts/export_baselines.py``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = os.environ.get("PALIMPSEST_DB", str(ROOT / "data/demo.db"))
SEED_FILE = ROOT / "data/seed/seed_paragraphs.jsonl"

CRITERIA = ("accuracy", "fluency", "style", "cultural", "terminology")


def _latest_scores(conn: sqlite3.Connection, pid: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM score WHERE paragraph_id=? AND kind='live' "
        "ORDER BY created_at DESC, id DESC",
        (pid,),
    ).fetchall()
    latest: dict[str, sqlite3.Row] = {}
    for r in rows:
        latest.setdefault(r["criterion_id"], r)
    return latest


def _open_issues(conn: sqlite3.Connection, pid: int, criterion_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM issue WHERE paragraph_id=? AND criterion_id=? "
        "AND kind='live' AND status='open' ORDER BY id",
        (pid, criterion_id),
    ).fetchall()
    return [
        {
            "problematic_fragment": r["target_fragment"],
            "source_fragment": r["source_fragment"],
            "explanation": r["explanation"],
            "suggestion": r["suggestion"],
        }
        for r in rows
    ]


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    seed_records = [json.loads(line) for line in SEED_FILE.read_text("utf-8").splitlines() if line.strip()]
    db_by_source = {r["source"]: r["id"] for r in conn.execute("SELECT id, source FROM paragraph")}

    missing_criteria: list[tuple[int, str]] = []
    for record in seed_records:
        pid = db_by_source.get(record["source"])
        if pid is None:
            print(f"  ! no DB paragraph matches seed id {record['id']}", file=sys.stderr)
            continue
        latest = _latest_scores(conn, pid)
        for crit in CRITERIA:
            row = latest.get(crit)
            if row is None:
                missing_criteria.append((record["id"], crit))
                continue
            record[crit] = {
                "identified_issues": _open_issues(conn, pid, crit),
                "criteria_assessment": "",
                "summary": row["summary"] or "",
                "final_score": row["value"],
            }

    if missing_criteria:
        print(f"  ! missing scores for {len(missing_criteria)} (id, criterion) pairs:", file=sys.stderr)
        for rid, crit in missing_criteria:
            print(f"      id={rid} criterion={crit}", file=sys.stderr)

    with SEED_FILE.open("w", encoding="utf-8") as f:
        for record in seed_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"exported baselines for {len(seed_records)} paragraphs, {len(missing_criteria)} missing")
    return 1 if missing_criteria else 0


if __name__ == "__main__":
    raise SystemExit(main())
