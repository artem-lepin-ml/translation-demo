#!/usr/bin/env python3
"""Adapter: write the real Term[] pipeline output into seed JSONL (Phase C6).

Reads ``data/seed/terminology_out.json`` (keyed by seed ``id``) and
``data/seed/seed_paragraphs.jsonl``, and for each paragraph overwrites only
``terminology.identified_terms`` with
``[{source_term, translation_used, domain}, ...]`` built from the real
Term[]. All other fields — ``source``, ``translated``, the criterion blocks
(``accuracy``/``fluency``/``style``/``cultural``/``consistency``), the
existing ``terminology.identified_issues``/``criteria_assessment``/
``summary``/``final_score`` (Phase B baselines) — are left untouched.

This makes ``seed.py``'s mock term-rotation path (``_seed_terms``, VERDICTS
``[i%3]``) draw from real pipeline data for the demo document instead of
placeholders. It stays dead code for any document *without* a matching
``terminology_out.json`` entry — not touched here.

Run after ``scripts/rebuild_demo.py``: ``uv run python
scripts/load_terms_into_seed.py``.
"""
from __future__ import annotations

import json

from palimpsest import paths

SEED_FILE = paths.DATA / "seed" / "seed_paragraphs.jsonl"
TERMS_FILE = paths.DATA / "seed" / "terminology_out.json"


def build_identified_terms(terms: list[dict]) -> list[dict]:
    return [
        {
            "source_term": t["sourceSurface"],
            "translation_used": t.get("targetSurface"),
            "domain": t.get("note", ""),
        }
        for t in terms
    ]


def main() -> None:
    rows = [json.loads(line) for line in SEED_FILE.open(encoding="utf-8")]
    terms_by_id = json.loads(TERMS_FILE.read_text(encoding="utf-8"))

    updated = 0
    for row in rows:
        terms = terms_by_id.get(str(row["id"]))
        if terms is None:
            continue
        row["terminology"]["identified_terms"] = build_identified_terms(terms)
        updated += 1

    with SEED_FILE.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    total_terms = sum(len(r["terminology"]["identified_terms"]) for r in rows)
    print(f"wrote identified_terms into {updated}/{len(rows)} paragraphs, {total_terms} terms total")


if __name__ == "__main__":
    main()
