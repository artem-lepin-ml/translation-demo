import asyncio

import pytest

from palimpsest.webapp import db, precompute
from tests.conftest import _body


async def _fake_judge(conn, criterion, source, target, source_lang, target_lang, endpoint="evaluate"):
    assert endpoint == "precompute"
    return {"value": 7.0, "summary": "ok",
            "issues": [{"targetFragment": "t", "sourceFragment": "s", "explanation": "e",
                        "suggestion": "sg", "severity": "minor", "mqmCategory": None}],
            "usage": None}


def _mk_doc(client, n=2):
    paras = [{"source": f"s{i}", "target": f"t{i}"} for i in range(n)]
    return client.post("/api/documents", json=_body(paragraphs=paras)).json()


@pytest.fixture()
def scored_client(client):
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy',1.0,1,10,1)")
    conn.commit()
    return client


def test_precompute_writes_seed_and_cache(scored_client):
    doc = _mk_doc(scored_client)
    asyncio.run(precompute.run(doc["id"], _fake_judge))
    conn = db.connect()
    seed = conn.execute("SELECT COUNT(*) c FROM score WHERE kind='seed'").fetchone()["c"]
    cache = conn.execute("SELECT COUNT(*) c FROM score WHERE kind='cache'").fetchone()["c"]
    issues = conn.execute("SELECT COUNT(*) c FROM issue WHERE kind='seed' AND status='open'").fetchone()["c"]
    assert seed == 2 and cache == 2 and issues == 2       # 2 абзаца × 1 критерий
    assert precompute.status_for(doc["id"]) == {"status": "done", "done": 2, "planned": 2, "succeeded": 2}


def test_skip_already_scored_paragraph(scored_client):
    doc = _mk_doc(scored_client)
    pid = doc["paragraphs"][0]["id"]
    conn = db.connect()
    conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,kind,created_at) "
                 "VALUES(?,'accuracy',9,'live','now')", (pid,))
    conn.commit()
    asyncio.run(precompute.run(doc["id"], _fake_judge))
    seeds = conn.execute("SELECT COUNT(*) c FROM score WHERE paragraph_id=? AND kind='seed'",
                         (pid,)).fetchone()["c"]
    assert seeds == 0                                     # пропущен, деньги не потрачены


def test_toctou_recheck_discards_results(scored_client):
    doc = _mk_doc(scored_client, n=1)
    pid = doc["paragraphs"][0]["id"]

    async def racing_judge(conn, criterion, source, target, sl, tl, endpoint="evaluate"):
        # имитируем live /evaluate, успевший записаться ВО ВРЕМЯ LLM-вызова
        conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,kind,created_at) "
                     "VALUES(?,'accuracy',9,'live','now')", (pid,))
        conn.commit()
        return await _fake_judge(conn, criterion, source, target, sl, tl, endpoint)

    asyncio.run(precompute.run(doc["id"], racing_judge))
    conn = db.connect()
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM score WHERE paragraph_id=?", (pid,))]
    assert kinds == ["live"]                              # прогрев ничего не перекрыл (решение №9)


def test_all_calls_fail_status_done_but_zero_succeeded(scored_client):
    """When every judge call fails (e.g. missing API key), the run still ends in
    'done' (not 'stopped' — that's reserved for the sub-cap), but 'succeeded'
    stays 0 so the frontend can tell 'ran and produced nothing' apart from a
    real success (BUG-5 seam)."""
    async def failing_judge(conn, criterion, source, target, sl, tl, endpoint="precompute"):
        raise RuntimeError("no api key")

    doc = _mk_doc(scored_client, n=2)
    asyncio.run(precompute.run(doc["id"], failing_judge))
    status = precompute.status_for(doc["id"])
    assert status == {"status": "done", "done": 2, "planned": 2, "succeeded": 0,
                       "error_reason": "no_api_key"}


def test_sub_cap_stops_run(scored_client, monkeypatch):
    monkeypatch.setattr(precompute, "_CALL_CAP", 1)
    from palimpsest.webapp import budget
    budget._STATE.pop("precompute_calls", None)
    doc = _mk_doc(scored_client, n=3)
    asyncio.run(precompute.run(doc["id"], _fake_judge))
    assert precompute.status_for(doc["id"])["status"] == "stopped"


def test_precompute_false_status_skipped(scored_client):
    doc = scored_client.post("/api/documents", json=_body()).json()  # precompute=False в _body
    got = scored_client.get(f"/api/documents/{doc['id']}").json()
    assert got["precompute"] == {"status": "skipped", "done": 0, "planned": 0, "succeeded": 0}


def test_delete_mid_run_cancels_task_no_further_judge_calls(scored_client):
    """DELETE must cancel the in-flight precompute task: after DELETE returns,
    no further judge calls should happen (spend-after-delete guard)."""
    doc = _mk_doc(scored_client, n=5)
    counter = {"calls": 0}

    async def slow_judge(conn, criterion, source, target, sl, tl, endpoint="precompute"):
        counter["calls"] += 1
        await asyncio.sleep(0.05)
        return {"value": 7.0, "summary": "ok", "issues": [], "usage": None}

    async def scenario():
        task = asyncio.create_task(precompute.run(doc["id"], slow_judge))
        precompute._tasks[doc["id"]] = task
        await asyncio.sleep(0.01)              # let the first call start

        r = scored_client.delete(f"/api/documents/{doc['id']}")
        assert r.status_code == 204
        precompute.cancel(doc["id"])

        calls_at_delete = counter["calls"]
        await asyncio.sleep(0.2)                # give a rogue task time to keep spending
        return calls_at_delete, counter["calls"]

    calls_at_delete, calls_after = asyncio.run(scenario())
    assert calls_after == calls_at_delete, "no further judge calls after DELETE returns"


def test_delete_pops_status(scored_client):
    doc = _mk_doc(scored_client, n=5)

    async def slow_judge(conn, criterion, source, target, sl, tl, endpoint="precompute"):
        await asyncio.sleep(0.05)
        return {"value": 7.0, "summary": "ok", "issues": [], "usage": None}

    async def scenario():
        task = asyncio.create_task(precompute.run(doc["id"], slow_judge))
        precompute._tasks[doc["id"]] = task
        await asyncio.sleep(0.01)
        scored_client.delete(f"/api/documents/{doc['id']}")
        precompute.cancel(doc["id"])
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert precompute.status_for(doc["id"]) is None


def test_recycled_id_impossible_after_delete(scored_client):
    """AUTOINCREMENT prevents SQLite's default id-reuse after a DELETE."""
    doc1 = _mk_doc(scored_client, n=1)
    scored_client.delete(f"/api/documents/{doc1['id']}")
    doc2 = _mk_doc(scored_client, n=1)
    assert doc2["id"] > doc1["id"]


def test_create_response_precompute_false_status_skipped_immediately(scored_client):
    """The 201 body itself (not just a subsequent GET) must already carry the
    skipped status — status is set before the response dict is built."""
    paras = [{"source": f"s{i}", "target": f"t{i}"} for i in range(2)]
    r = scored_client.post("/api/documents", json=_body(paragraphs=paras, precompute=False))
    assert r.status_code == 201
    assert r.json()["precompute"] == {"status": "skipped", "done": 0, "planned": 0, "succeeded": 0}


def test_create_response_precompute_true_status_running_immediately(scored_client):
    """The 201 body must already show status=running with the planned count,
    not None (before run() has had a chance to execute)."""
    paras = [{"source": f"s{i}", "target": f"t{i}"} for i in range(5)]
    r = scored_client.post("/api/documents", json=_body(paragraphs=paras, precompute=True))
    assert r.status_code == 201
    got = r.json()["precompute"]
    assert got["status"] == "running"
    assert got["done"] == 0
    assert got["planned"] == 5
