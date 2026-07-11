"""Content-fingerprint clone cache (EMNLP demo-video follow-up).

A ``translate:false`` upload whose (source, target) pairs match an existing
``terms_status='done'`` document byte-for-byte (whitespace-run normalized)
instantly inherits its terms/scores/issues instead of launching
precompute/terminology_live — see "Content clone cache" in
docs/subsystems/webapp.md.

The clone source is built via direct SQL inserts (no fake LLM harness
needed — the whole point of this feature is that no LLM call happens).
"""
from __future__ import annotations

import json

import pytest

from palimpsest.webapp import db, precompute, terminology_live

from .conftest import _body

CRITERION_ID = "accuracy"
SOURCE_TS = "2026-07-11T00:00:00+00:00"


def _seed_criterion(conn, cid: str = CRITERION_ID) -> None:
    conn.execute(
        "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
        "VALUES(?,?,?,?,?,?,?,?,1)",
        (cid, cid.title(), None, "prompt body", 1.0, 10.0, 1.0, "#4d8dff"))
    conn.commit()


def _seed_processed_doc(conn, pairs, *, source_lang="ru", target_lang="en",
                         terms_status="done", aggregate=7.78) -> int:
    """Direct-insert a fully-processed document: one term + one seed score +
    one open issue per paragraph. This is the clone SOURCE, built the way a
    real precompute+terminology_live run would have left the DB, without
    spending any LLM call."""
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at,terms_status) "
        "VALUES(?,?,?,'user',0,'upload',?,?)",
        ("Clone source", source_lang, target_lang, SOURCE_TS, terms_status)).lastrowid
    for idx, (source, target) in enumerate(pairs):
        pid = conn.execute(
            "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
            (doc_id, idx, source, target, target)).lastrowid
        rev_id = db.write_revision(conn, pid, target, "upload", SOURCE_TS)
        grounded = json.dumps({"qid": "Q1", "label": target, "description": "x",
                                "url": "https://www.wikidata.org/wiki/Q1"})
        conn.execute(
            "INSERT INTO term(paragraph_id,source_surface,source_lemma,context,char_start,char_end,"
            "difficulty,grounded_json,candidates_json,target_surface,pair_accuracy,recommended,note,trace_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, source[:4], source[:4], source, 0, min(4, len(source)), "green",
             grounded, "[]", target, "green", None, "a term", "{}"))
        conn.execute(
            "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,"
            "created_at,revision_id) VALUES(?,?,?,?,?,?,'seed',?,?)",
            (pid, CRITERION_ID, 8.0, "good baseline", aggregate, CRITERION_ID, SOURCE_TS, rev_id))
        conn.execute(
            "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
            "suggestion,severity,mqm_category,status,kind,created_at) VALUES(?,?,?,?,?,?,?,?,'open','seed',?)",
            (pid, CRITERION_ID, target[:3], source[:3], "explanation text", "", "minor", None, SOURCE_TS))
    conn.commit()
    return doc_id


@pytest.fixture()
def launches(monkeypatch):
    """Record precompute.launch/terminology_live.launch calls instead of
    letting create_document actually schedule background asyncio tasks —
    same no-real-background-task convention as test_terminology_live.py's
    _no_auto_launch fixture, but call-recording instead of a plain no-op so
    tests can assert whether a launch happened."""
    calls = {"precompute": [], "terminology_live": []}
    monkeypatch.setattr(precompute, "launch", lambda *a, **kw: calls["precompute"].append(a))
    monkeypatch.setattr(terminology_live, "launch", lambda *a, **kw: calls["terminology_live"].append(a))
    return calls


def _boom(*_a, **_kw):
    pytest.fail("must not be called for a cloned document")


PAIRS = [("Hello world.", "Bonjour le monde."), ("Second paragraph here.", "Deuxième paragraphe ici.")]


def test_clone_on_identical_content_instant_terms_and_no_launch(client, monkeypatch):
    conn = db.connect()
    _seed_criterion(conn)
    source_id = _seed_processed_doc(conn, PAIRS)

    monkeypatch.setattr(precompute, "launch", _boom)
    monkeypatch.setattr(terminology_live, "launch", _boom)

    body = _body(sourceLang="ru", targetLang="en", precompute=True,
                 paragraphs=[{"source": s, "target": t} for s, t in PAIRS])
    r = client.post("/api/documents", json=body)
    assert r.status_code == 201
    doc = r.json()

    assert doc["termsStatus"] == "done"
    assert doc["precompute"] == {"status": "skipped", "done": 0, "planned": 0, "succeeded": 0}
    assert len(doc["paragraphs"]) == 2
    for para in doc["paragraphs"]:
        assert len(para["terms"]) == 1
        assert len(para["scores"]) == 1
        assert len(para["issues"]) == 1
        assert para["aggregate"] == 7.78                 # frozen aggregate column, copied verbatim
        assert para["scoresBaseline"] is not None         # kind='seed' copied -> counts as baseline too
        assert para["best"]["aggregate"] == 7.78
        assert para["best"]["isCurrent"] is True           # revision_id remapped to the new paragraph's own

    # DB-level count parity with the source document.
    new_pids = [p["id"] for p in doc["paragraphs"]]
    src_pids = [r["id"] for r in conn.execute(
        "SELECT id FROM paragraph WHERE document_id=? ORDER BY idx", (source_id,))]
    for new_pid, src_pid in zip(new_pids, src_pids, strict=True):
        for table in ("term", "score", "issue"):
            n_new = conn.execute(f"SELECT COUNT(*) n FROM {table} WHERE paragraph_id=?", (new_pid,)).fetchone()["n"]
            n_src = conn.execute(f"SELECT COUNT(*) n FROM {table} WHERE paragraph_id=?", (src_pid,)).fetchone()["n"]
            assert n_new == n_src == 1, f"{table} count mismatch: new={n_new} src={n_src}"

    # GET reconfirms the persisted state (not just the 201 response).
    got = client.get(f"/api/documents/{doc['id']}").json()
    assert got["termsStatus"] == "done"
    assert len(got["paragraphs"][0]["terms"]) == 1


def test_clone_normalizes_whitespace_runs(client, launches):
    conn = db.connect()
    _seed_criterion(conn)
    # source doc has a double space + the upload has a single space -> same
    # normalized fingerprint (design bullet 1: "normalize whitespace runs").
    _seed_processed_doc(conn, [("Hello  world.", "Bonjour   le monde.")])

    body = _body(sourceLang="ru", targetLang="en", precompute=False,
                 paragraphs=[{"source": "Hello world.", "target": "Bonjour le monde."}])
    r = client.post("/api/documents", json=body)
    assert r.status_code == 201
    assert r.json()["termsStatus"] == "done"
    assert launches["precompute"] == [] and launches["terminology_live"] == []


def test_different_content_takes_normal_path(client, launches):
    conn = db.connect()
    _seed_criterion(conn)
    _seed_processed_doc(conn, PAIRS)

    different = [("Completely different source.", "Completely different target.")]
    body = _body(sourceLang="ru", targetLang="en", precompute=False,
                 paragraphs=[{"source": s, "target": t} for s, t in different])
    r = client.post("/api/documents", json=body)
    assert r.status_code == 201
    doc = r.json()

    assert doc["termsStatus"] == "running"                # normal (non-cloned) path
    assert doc["paragraphs"][0]["terms"] == []
    assert doc["paragraphs"][0]["scores"] == []
    assert launches["terminology_live"] != [], "terminology_live.launch must run for a non-cloned upload"


def test_paragraph_count_mismatch_takes_normal_path(client, launches):
    conn = db.connect()
    _seed_criterion(conn)
    _seed_processed_doc(conn, PAIRS)                      # 2 paragraphs

    # same first two pairs PLUS an extra third paragraph -> count differs ->
    # the fingerprint (a JSON array over ALL pairs) can never collide.
    extra = [*PAIRS, ("A third paragraph.", "Un troisième paragraphe.")]
    body = _body(sourceLang="ru", targetLang="en", precompute=False,
                 paragraphs=[{"source": s, "target": t} for s, t in extra])
    r = client.post("/api/documents", json=body)
    assert r.status_code == 201
    doc = r.json()

    assert doc["termsStatus"] == "running"
    assert all(p["terms"] == [] for p in doc["paragraphs"])
    assert launches["terminology_live"] != []


def test_clone_source_must_be_terms_done(client, launches):
    """A content-identical document that itself is not yet fully processed
    (terms_status='running') must never be used as a clone source (design
    bullet 3)."""
    conn = db.connect()
    _seed_criterion(conn)
    _seed_processed_doc(conn, PAIRS, terms_status="running")

    body = _body(sourceLang="ru", targetLang="en", precompute=False,
                 paragraphs=[{"source": s, "target": t} for s, t in PAIRS])
    r = client.post("/api/documents", json=body)
    assert r.status_code == 201
    doc = r.json()

    assert doc["termsStatus"] == "running"                # own fresh 'running', NOT a clone
    assert doc["paragraphs"][0]["terms"] == []
    assert launches["terminology_live"] != []


def test_translate_true_never_clones(client, launches):
    """translate:true uploads are exempt from cloning outright (design
    bullet 2) — targets are empty at creation time, so there is nothing
    meaningful to fingerprint yet regardless of what matches by source text
    alone."""
    conn = db.connect()
    _seed_criterion(conn)
    _seed_processed_doc(conn, PAIRS)

    body = _body(sourceLang="ru", targetLang="en", translate=True, precompute=True,
                 paragraphs=[{"source": PAIRS[0][0], "target": ""}])
    r = client.post("/api/documents", json=body)
    assert r.status_code == 201
    doc = r.json()

    assert doc["termsStatus"] == "none"                   # untouched at creation -> proves no clone happened
    assert doc["precompute"] == {"status": "skipped", "done": 0, "planned": 0, "succeeded": 0}
    assert launches["terminology_live"] == []              # deferred to post-translate, not launched here
