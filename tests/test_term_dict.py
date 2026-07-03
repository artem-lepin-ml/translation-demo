"""_term_dict whitelists verdict enum columns (pair_accuracy/difficulty)
against {green, yellow, red}. An out-of-enum DB value would otherwise drive
a dead `verdict-<value>`/`difficulty-<value>` CSS class silently — coerce to
null (neutral) instead.
"""
from __future__ import annotations

from palimpsest.webapp import db

from .conftest import _body


def test_out_of_enum_pair_accuracy_serializes_to_null(client):
    doc = client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]

    conn = db.connect()
    conn.execute(
        "INSERT INTO term(paragraph_id,source_surface,source_lemma,context,char_start,char_end,"
        "difficulty,target_surface,pair_accuracy) VALUES(?,?,?,?,?,?,?,?,?)",
        (pid, "Ein", "ein", "", 0, 3, "green", "A", "grey"),
    )
    conn.commit()

    r = client.get(f"/api/documents/{doc['id']}")
    assert r.status_code == 200
    term = next(t for t in r.json()["paragraphs"][0]["terms"] if t["sourceSurface"] == "Ein")
    assert term["pairAccuracy"] is None
    assert term["difficulty"] == "green"


def test_out_of_enum_difficulty_serializes_to_null(client):
    doc = client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]

    conn = db.connect()
    conn.execute(
        "INSERT INTO term(paragraph_id,source_surface,source_lemma,context,char_start,char_end,"
        "difficulty,target_surface,pair_accuracy) VALUES(?,?,?,?,?,?,?,?,?)",
        (pid, "Ein", "ein", "", 0, 3, "purple", "A", "green"),
    )
    conn.commit()

    r = client.get(f"/api/documents/{doc['id']}")
    assert r.status_code == 200
    term = next(t for t in r.json()["paragraphs"][0]["terms"] if t["sourceSurface"] == "Ein")
    assert term["difficulty"] is None
    assert term["pairAccuracy"] == "green"
