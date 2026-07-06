"""Spec 2026-07-05-score-history-best: target_revision writes at every mutation
point, revision_id stamped on every score INSERT, best-revision selection
(excluding cache), and the revisions/restore endpoints."""
from __future__ import annotations

import asyncio

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db, precompute

from .conftest import _body


def _mk_doc(client):
    return client.post("/api/documents", json=_body()).json()


# ── revision writes ──────────────────────────────────────────────────────

def test_upload_writes_origin_upload_revision(client):
    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    revs = db.connect().execute(
        "SELECT * FROM target_revision WHERE paragraph_id=?", (pid,)).fetchall()
    assert len(revs) == 1 and revs[0]["origin"] == "upload"
    assert revs[0]["text"] == "Un paragraphe."


def test_patch_paragraph_writes_edit_revision_only_if_changed(client):
    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]

    r = client.patch(f"/api/paragraphs/{pid}", json={"target": "Un paragraphe."})  # no-op
    assert r.status_code == 200
    revs = db.connect().execute(
        "SELECT * FROM target_revision WHERE paragraph_id=? ORDER BY id", (pid,)).fetchall()
    assert len(revs) == 1                        # unchanged text → no new revision

    client.patch(f"/api/paragraphs/{pid}", json={"target": "Changed text."})
    revs = db.connect().execute(
        "SELECT * FROM target_revision WHERE paragraph_id=? ORDER BY id", (pid,)).fetchall()
    assert len(revs) == 2
    assert revs[-1]["origin"] == "edit"
    assert revs[-1]["text"] == "Changed text."


def test_apply_edit_writes_revision(client):
    conn = db.connect()
    doc = client.post("/api/documents", json=_body(
        paragraphs=[{"source": "s", "target": "city states are old"}])).json()
    pid = doc["paragraphs"][0]["id"]
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','http://x','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
                 "VALUES('accuracy','Accuracy','m','p',1,10,0.3,'#888',1)")
    iid = conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
        "suggestion,severity,mqm_category,status,kind,created_at) VALUES(?,?,?,?,?,?,?,?,'open','live',?)",
        (pid, "accuracy", "city states", "s", "e", "polities", "minor", None, "now")).lastrowid
    conn.commit()

    r = client.post(f"/api/paragraphs/{pid}/apply-edit", json={"issueId": str(iid)})
    assert r.status_code == 200, r.text
    revs = conn.execute("SELECT * FROM target_revision WHERE paragraph_id=? ORDER BY id", (pid,)).fetchall()
    assert revs[-1]["origin"] == "apply_edit"
    assert "polities" in revs[-1]["text"]


def test_reset_writes_seed_revision(client):
    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    client.patch(f"/api/paragraphs/{pid}", json={"target": "Edited."})
    r = client.post(f"/api/documents/{doc['id']}/reset")
    assert r.status_code == 200, r.text
    revs = db.connect().execute(
        "SELECT * FROM target_revision WHERE paragraph_id=? ORDER BY id", (pid,)).fetchall()
    assert revs[-1]["origin"] == "seed"
    assert revs[-1]["text"] == "Un paragraphe."


def test_restore_writes_revision_and_updates_target(client):
    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    first_rev_id = db.connect().execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["id"]
    client.patch(f"/api/paragraphs/{pid}", json={"target": "Edited version."})

    r = client.post(f"/api/paragraphs/{pid}/restore", json={"revisionId": first_rev_id})
    assert r.status_code == 200, r.text
    assert r.json()["target"] == "Un paragraphe."
    revs = db.connect().execute(
        "SELECT * FROM target_revision WHERE paragraph_id=? ORDER BY id", (pid,)).fetchall()
    assert revs[-1]["origin"] == "restore"
    assert revs[-1]["text"] == "Un paragraphe."


def test_restore_404_unknown_revision(client):
    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    r = client.post(f"/api/paragraphs/{pid}/restore", json={"revisionId": 999999})
    assert r.status_code == 404


def test_restore_409_revision_of_another_paragraph(client):
    doc = client.post("/api/documents", json=_body(
        paragraphs=[{"source": "s1", "target": "t1"}, {"source": "s2", "target": "t2"}])).json()
    pid0, pid1 = doc["paragraphs"][0]["id"], doc["paragraphs"][1]["id"]
    rev1 = db.connect().execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid1,)).fetchone()["id"]
    r = client.post(f"/api/paragraphs/{pid0}/restore", json={"revisionId": rev1})
    assert r.status_code == 409


def test_revisions_endpoint_lists_newest_first(client):
    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    client.patch(f"/api/paragraphs/{pid}", json={"target": "v2"})
    client.patch(f"/api/paragraphs/{pid}", json={"target": "v3"})
    got = client.get(f"/api/paragraphs/{pid}/revisions").json()
    texts = [r["text"] for r in got["revisions"]]
    assert texts == ["v3", "v2", "Un paragraphe."]
    assert got["revisions"][0]["isCurrent"] is True
    assert got["revisions"][-1]["isCurrent"] is False


# ── revision_id stamping on score INSERT ────────────────────────────────

def test_evaluate_stamps_revision_id(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"m": (1e-6, 1e-6)})
    budget.reset()
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','http://x','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()
    usage = type("U", (), {"cost_usd": 0.0, "prompt_tokens": 1, "completion_tokens": 1, "reasoning_tokens": 0})()
    monkeypatch.setattr(app_mod, "judge_one",
                         lambda *a, **kw: {"value": 8.0, "summary": "ok", "issues": [], "usage": usage})

    class _Dummy:
        class config:
            max_tokens = 512
    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name, params_override=None: _Dummy())

    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    r = client.post(f"/api/paragraphs/{pid}/evaluate")
    assert r.status_code == 200, r.text
    expected_rev = conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["id"]
    row = conn.execute("SELECT revision_id FROM score WHERE paragraph_id=? AND kind='live'", (pid,)).fetchone()
    assert row["revision_id"] == expected_rev


def test_precompute_write_paragraph_stamps_revision_id(client):
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy',1.0,1,10,1)")
    conn.commit()

    async def fake_judge(conn, criterion, source, target, sl, tl, endpoint="precompute"):
        return {"value": 7.0, "summary": "ok", "issues": [], "usage": None}

    doc = client.post("/api/documents", json=_body(precompute=False)).json()
    pid = doc["paragraphs"][0]["id"]
    asyncio.run(precompute.run(doc["id"], fake_judge))
    expected_rev = conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["id"]
    rows = conn.execute("SELECT revision_id FROM score WHERE paragraph_id=?", (pid,)).fetchall()
    assert all(r["revision_id"] == expected_rev for r in rows)


def test_seed_stamps_revision_id(tmp_path, monkeypatch):
    from palimpsest.webapp import db as db_mod, seed as seed_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "seed.db")
    monkeypatch.setattr(db_mod, "_conn", None)
    seed_mod.seed()
    conn = db_mod.connect()
    row = conn.execute(
        "SELECT s.revision_id, r.origin FROM score s JOIN target_revision r ON r.id = s.revision_id "
        "WHERE s.kind='seed' LIMIT 1").fetchone()
    assert row is not None
    assert row["origin"] == "seed"


# ── best-revision selection (excludes cache) ────────────────────────────

def test_best_excludes_cache_kind(client):
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','http://x','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()
    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    rev_id = conn.execute("SELECT id FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["id"]
    conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,aggregate,kind,created_at,revision_id) "
                 "VALUES(?,'accuracy',9.9,9.9,'cache','2026-01-01T00:00:00Z',?)", (pid, rev_id))
    conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,aggregate,kind,created_at,revision_id) "
                 "VALUES(?,'accuracy',6.0,6.0,'live','2026-01-01T00:00:01Z',?)", (pid, rev_id))
    conn.commit()
    got = client.get(f"/api/documents/{doc['id']}").json()
    para = got["paragraphs"][0]
    assert para["best"]["aggregate"] == 6.0      # the cache row (9.9) must not win


def test_best_none_when_no_scored_revision(client):
    doc = _mk_doc(client)
    para = client.get(f"/api/documents/{doc['id']}").json()["paragraphs"][0]
    assert para["best"] is None


def test_best_picks_highest_aggregate_and_marks_current(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"m": (1e-6, 1e-6)})
    budget.reset()
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','http://x','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()

    scores = iter([9.0, 4.0])
    usage = type("U", (), {"cost_usd": 0.0, "prompt_tokens": 1, "completion_tokens": 1, "reasoning_tokens": 0})()
    monkeypatch.setattr(app_mod, "judge_one",
                         lambda *a, **kw: {"value": next(scores), "summary": "ok", "issues": [], "usage": usage})

    class _Dummy:
        class config:
            max_tokens = 512
    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name, params_override=None: _Dummy())

    doc = _mk_doc(client)
    pid = doc["paragraphs"][0]["id"]
    client.post(f"/api/paragraphs/{pid}/evaluate")           # first eval → aggregate 10 (norm to top)
    first_rev = conn.execute("SELECT id FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["id"]
    client.patch(f"/api/paragraphs/{pid}", json={"target": "a worse edit"})
    client.post(f"/api/paragraphs/{pid}/evaluate")           # second eval on NEW revision → lower

    got = client.get(f"/api/documents/{doc['id']}").json()
    best = got["paragraphs"][0]["best"]
    assert best["revisionId"] == first_rev
    assert best["isCurrent"] is False             # the paragraph moved on to a newer revision
