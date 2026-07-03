"""Seed-path guard: planted advice suggestion is emptied and moved to explanation."""
from __future__ import annotations

import json
import sqlite3

from palimpsest.webapp.judge import sanitize_issue


def test_seed_row_shape_after_sanitize():
    out = sanitize_issue({
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Inconsistent term.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
        "severity": "minor",
        "mqmCategory": None,
    })
    assert out["suggestion"] == ""
    assert "Advice: Use 'debt bondage'" in out["explanation"]


def test_seed_inserts_no_advice_suggestion(tmp_path, monkeypatch):
    from palimpsest.webapp import db, seed as seed_mod

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setattr(db, "_conn", None)

    seed_file = tmp_path / "seed.jsonl"
    row = {
        "source": "goroda-gosudarstva",
        "translated": "city states",
        "accuracy": {
            "final_score": 5.0,
            "summary": "s",
            "identified_issues": [{
                "problematic_fragment": "city states",
                "source_fragment": "goroda-gosudarstva",
                "explanation": "Inconsistent term.",
                "suggestion": "Use 'debt bondage', which is the standard term.",
            }],
        },
    }
    seed_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setattr(seed_mod, "SEED_FILE", seed_file)

    seed_mod.seed()

    conn = sqlite3.connect(str(tmp_path / "demo.db"))
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT suggestion, explanation FROM issue WHERE criterion_id='accuracy'").fetchone()
    assert r is not None
    assert (r["suggestion"] or "") == ""
    assert "Advice: Use 'debt bondage'" in r["explanation"]


def test_seed_survives_non_str_suggestion(tmp_path, monkeypatch):
    """A malformed row (suggestion is a JSON number, not a string) must not crash seed()."""
    from palimpsest.webapp import db, seed as seed_mod

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setattr(db, "_conn", None)

    seed_file = tmp_path / "seed.jsonl"
    rows = [
        {
            "source": "malformed-row",
            "translated": "target text",
            "accuracy": {
                "final_score": 5.0,
                "summary": "s",
                "identified_issues": [{
                    "problematic_fragment": "target",
                    "source_fragment": "malformed",
                    "explanation": "Numeric suggestion from a bad provider payload.",
                    "suggestion": 5,
                }],
            },
        },
        {
            "source": "honest-row",
            "translated": "honest target text",
            "accuracy": {
                "final_score": 6.0,
                "summary": "s",
                "identified_issues": [{
                    "problematic_fragment": "honest",
                    "source_fragment": "honest-row",
                    "explanation": "Should read differently.",
                    "suggestion": "correct target text",
                }],
            },
        },
    ]
    seed_file.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(seed_mod, "SEED_FILE", seed_file)

    seed_mod.seed()  # must not raise AttributeError on the non-str suggestion

    conn = sqlite3.connect(str(tmp_path / "demo.db"))
    conn.row_factory = sqlite3.Row
    rows_out = conn.execute(
        "SELECT source_fragment, suggestion FROM issue WHERE criterion_id='accuracy' ORDER BY id"
    ).fetchall()
    assert len(rows_out) == 2
    malformed, honest = rows_out
    assert malformed["suggestion"] == "5"
    assert honest["suggestion"] == "correct target text"
