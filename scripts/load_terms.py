#!/usr/bin/env python3
"""Replace the webapp's mock terms with real pipeline output.

Maps each seed paragraph (by exact source text) to its webapp paragraph row,
deletes that paragraph's existing ``term`` rows, and inserts the real Term[] from
``data/seed/terminology_out.json``. Run after ``python -m palimpsest.webapp.seed``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = os.environ.get("PALIMPSEST_DB", str(ROOT / "data/demo.db"))
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
OUT = ROOT / "data/seed/terminology_out.json"


def main() -> int:
    seed_rows = {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}
    out = json.loads(OUT.read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # map DB paragraph.source → paragraph id
    db_by_source = {r["source"]: r["id"] for r in conn.execute("SELECT id, source FROM paragraph")}
    inserted, paras = 0, 0
    for seed_id, terms in out.items():
        src = seed_rows[int(seed_id)]["source"]
        pid = db_by_source.get(src)
        if pid is None:
            print(f"  ! no DB paragraph matches seed id {seed_id}", file=sys.stderr)
            continue
        conn.execute("DELETE FROM term WHERE paragraph_id=?", (pid,))
        for t in terms:
            g = t["grounded"]
            conn.execute(
                "INSERT OR REPLACE INTO term(paragraph_id,source_surface,source_lemma,context,"
                "char_start,char_end,difficulty,grounded_json,candidates_json,target_surface,"
                "pair_accuracy,recommended,note,trace_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, t["sourceSurface"], t["sourceLemma"], t["context"], t["charStart"], t["charEnd"],
                 t["difficulty"], json.dumps(g) if g else None, json.dumps(t["candidates"]),
                 t["targetSurface"], t["pairAccuracy"], t["recommended"], t.get("note", ""),
                 json.dumps(t.get("trace") or {})),
            )
            inserted += 1
        paras += 1
    conn.commit()
    n = conn.execute("SELECT COUNT(*) c FROM term").fetchone()["c"]
    by_diff = {r["difficulty"]: r["c"] for r in conn.execute("SELECT difficulty, COUNT(*) c FROM term GROUP BY difficulty")}
    conn.close()
    print(f"loaded {inserted} real terms into {paras} paragraphs; term table now has {n} rows")
    print(f"  difficulty: {by_diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
