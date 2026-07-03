import pytest

from palimpsest.webapp import db
from tests.conftest import _body


async def _fake_judge(conn, criterion, source, target, source_lang, target_lang):
    return {"value": 8.0, "summary": "ok", "issues": [], "usage": None}


@pytest.fixture()
def scored_client(client, monkeypatch):
    from palimpsest.webapp import app as app_mod
    monkeypatch.setattr(app_mod, "_judge_live", _fake_judge)
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy',1.0,1,10,1)")
    conn.commit()
    return client


def test_first_evaluate_aggregate_prev_null(scored_client):
    doc = scored_client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    ev = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev["aggregatePrev"] is None            # первая оценка → без дельты (решение №7)


def test_second_evaluate_aggregate_prev_set(scored_client):
    doc = scored_client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    first = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    second = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert second["aggregatePrev"] == first["aggregate"]


def test_evaluate_score_dict_includes_criteria_key(scored_client):
    doc = scored_client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    ev = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev["scores"], "evaluate must have produced live scores"
    for score in ev["scores"]:
        assert score["criteriaKey"], "score dict must carry a non-empty criteriaKey"


def test_cache_fallback_carries_aggregate_prev(scored_client, monkeypatch):
    from palimpsest.webapp import app as app_mod

    async def boom(*a, **kw):
        raise RuntimeError("no api key")
    monkeypatch.setattr(app_mod, "_judge_live", boom)
    doc = scored_client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    conn = db.connect()
    conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,aggregate,kind,created_at) "
                 "VALUES(?,'accuracy',6.0,6.0,'cache','2026-07-02T00:00:00')", (pid,))
    conn.commit()
    ev = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev["cached"] is True
    assert ev["aggregatePrev"] is None            # seed/live-строк нет → первая оценка (F4+M8)
