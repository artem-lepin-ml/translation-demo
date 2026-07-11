"""Unit tests for the live terminology pipeline (terminology_live.py):
happy path (NER -> ground -> pair -> term rows + status transitions), the
async disambiguation-judge bridge, per-paragraph failure handling (overall
'failed' only when nothing succeeded), idempotent resume, the translate-doc
launch hook, and the removed terms stub route.

No real network/LLM calls: the LLM is a fake client_for()/grounding_judge_live
closure, WikidataClient is monkeypatched to a fake with the same shape as
tests/test_terminology.py's _FakeWD.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db, terminology_live, translate

from .conftest import _body

# ── fakes ────────────────────────────────────────────────────────────────

class _FakeWD:
    """No-network WikidataClient stand-in. ``hits``/``entities`` are keyed by
    the exact query string terminology_live's caller will search for."""

    def __init__(self, hits: dict | None = None, entities: dict | None = None, *_a, **_kw):
        self.n_calls = 0
        self._hits = hits or {}
        self._entities = entities or {}

    def search_entities(self, term, lang="ru", limit=7):
        return list(self._hits.get(term, []))

    def search_cirrus(self, term, limit=7):
        return []

    def wikipedia_wikibase_item(self, title, lang="ru"):
        return None

    def get_entities(self, qids, **kw):
        return {q: self._entities[q] for q in qids if q in self._entities}


def _entity(qid, label_en, label_ru, enwiki=None):
    return {
        "id": qid,
        "labels": {"en": {"value": label_en}, "ru": {"value": label_ru}},
        "aliases": {"en": [], "ru": []},
        "descriptions": {"en": {"value": "a test entity"}},
        "sitelinks": ({"enwiki": {"title": enwiki}} if enwiki else {}),
    }


class _FakeResult:
    def __init__(self, content):
        self.content = content
        self.usage = type("U", (), {"cost_usd": 0.0001, "prompt_tokens": 10,
                                     "completion_tokens": 5, "reasoning_tokens": 0})()


class _FakeClient:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user):
        self.calls.append((system, user))
        idx = min(len(self.calls) - 1, len(self._replies) - 1)
        content = self._replies[idx]
        if isinstance(content, Exception):
            raise content
        return _FakeResult(content)

    config = type("Cfg", (), {"max_tokens": 2048})()


def _client_for_factory(client: _FakeClient):
    def client_for(conn, name, params=None):
        return client
    return client_for


async def _judge_picks(qid: str):
    async def judge(conn, prompt, endpoint="grounding"):
        return {"qid": qid, "reason": "test"}
    return judge


def _seed_grounding_config(conn, model="fake/model"):
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 (model, "https://openrouter.ai/api/v1", "k", "{}"))
    conn.execute(
        "INSERT INTO grounding_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (model, "p", json.dumps({"max_tokens": 512, "temperature": 0})))
    conn.commit()


def _mk_doc(client, paragraphs, **over):
    body = _body(sourceLang="ru", targetLang="en", precompute=False, paragraphs=paragraphs, **over)
    return client.post("/api/documents", json=body).json()


@pytest.fixture(autouse=True)
def _no_network_budget(monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"fake/model": (1e-6, 1e-6)})
    budget.reset()


@pytest.fixture(autouse=True)
def _no_auto_launch(monkeypatch):
    """create_document's own auto-launch (terminology_live.launch /
    translate.launch) must not race a real background task against test
    assertions — every test below drives terminology_live.run()/
    translate.run_translation() explicitly instead, same convention as
    tests/test_precompute.py and tests/test_translator.py."""
    monkeypatch.setattr(terminology_live, "launch", lambda *a, **kw: None)
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)


NER_ONE_TERM = '[{"surface":"Вавилон","lemma":"Вавилон","category":"place"}]'
NER_AMBIGUOUS_TERM = '[{"surface":"Тутмос","lemma":"Тутмос","category":"person"}]'
NER_EMPTY = "[]"


# ── happy path: exact-label green, no judge call needed ────────────────────

def test_run_writes_term_rows_and_transitions_to_done(client):
    monkeypatched_wd = _FakeWD(
        hits={"Вавилон": [{"id": "Q23522"}]},
        entities={"Q23522": _entity("Q23522", "Babylon", "Вавилон", enwiki="Babylon")},
    )

    def _wd_factory(*a, **kw):
        return monkeypatched_wd

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(terminology_live, "WikidataClient", _wd_factory)
        conn = db.connect()
        _seed_grounding_config(conn)
        doc = _mk_doc(client, [{"source": "Вавилон был велик.", "target": "Babylon was great."}])
        assert doc["termsStatus"] == "running"  # create_document flipped it synchronously

        fake_client = _FakeClient([NER_ONE_TERM])
        client_for = _client_for_factory(fake_client)
        judge = asyncio.run(_judge_picks("Q23522"))
        asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    pid = doc["paragraphs"][0]["id"]
    rows = conn.execute("SELECT * FROM term WHERE paragraph_id=?", (pid,)).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["source_surface"] == "Вавилон"
    assert row["difficulty"] == "green"             # exact-label match — no judge call needed
    assert row["target_surface"] == "Babylon"
    assert row["pair_accuracy"] == "green"
    assert fake_client.calls[0][0] == terminology_live.NER_SYSTEM_PROMPT  # frozen prompt, verbatim

    got = client.get(f"/api/documents/{doc['id']}").json()
    assert got["termsStatus"] == "done"


# ── the async disambiguation-judge sync/thread bridge ───────────────────────

def test_run_disambiguation_judge_bridge_resolves_yellow(client):
    wd = _FakeWD(
        hits={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
        entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                  "Q2": _entity("Q2", "Thutmose II", "Тутмос")},
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(terminology_live, "WikidataClient", lambda *a, **kw: wd)
        conn = db.connect()
        _seed_grounding_config(conn)
        doc = _mk_doc(client, [{"source": "Тутмос правил.", "target": "Thutmose II ruled."}])

        fake_client = _FakeClient([NER_AMBIGUOUS_TERM])
        client_for = _client_for_factory(fake_client)
        judge = asyncio.run(_judge_picks("Q2"))        # judge disambiguates to Thutmose II
        asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    pid = doc["paragraphs"][0]["id"]
    row = conn.execute("SELECT * FROM term WHERE paragraph_id=?", (pid,)).fetchone()
    assert row["difficulty"] == "yellow"
    grounded = json.loads(row["grounded_json"])
    assert grounded["qid"] == "Q2"                  # the FAKE judge's choice was honored end-to-end
    assert row["pair_accuracy"] == "green"           # "Thutmose II" located verbatim in the target


# ── per-paragraph failure handling ──────────────────────────────────────────

def test_run_no_grounding_config_fails_every_paragraph_status_failed(client):
    doc = _mk_doc(client, [{"source": "Вавилон.", "target": "Babylon."}])
    # grounding_config deliberately left unset -> _extract_mentions_live raises
    # RuntimeError("grounding_config not set") for every paragraph.
    client_for = _client_for_factory(_FakeClient([NER_ONE_TERM]))
    judge = asyncio.run(_judge_picks("Q1"))
    asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    got = client.get(f"/api/documents/{doc['id']}").json()
    assert got["termsStatus"] == "failed"
    assert got["paragraphs"][0]["terms"] == []


def test_run_partial_failure_still_ends_done(client):
    wd = _FakeWD(hits={"Вавилон": [{"id": "Q23522"}]},
                 entities={"Q23522": _entity("Q23522", "Babylon", "Вавилон")})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(terminology_live, "WikidataClient", lambda *a, **kw: wd)
        conn = db.connect()
        _seed_grounding_config(conn)
        doc = _mk_doc(client, [
            {"source": "Вавилон был велик.", "target": "Babylon was great."},
            {"source": "Второй абзац.", "target": "Second paragraph."},
        ])
        # first paragraph parses fine, second gets a malformed (non-JSON) reply
        fake_client = _FakeClient([NER_ONE_TERM, "not json at all"])
        client_for = _client_for_factory(fake_client)
        judge = asyncio.run(_judge_picks("Q23522"))
        asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    got = client.get(f"/api/documents/{doc['id']}").json()
    assert got["termsStatus"] == "done"             # NOT failed — at least one paragraph succeeded
    assert len(got["paragraphs"][0]["terms"]) == 1
    assert got["paragraphs"][1]["terms"] == []  # malformed-reply paragraph skipped, not crashed


# ── idempotent resume ────────────────────────────────────────────────────────

def test_run_skips_paragraph_that_already_has_terms(client):
    conn = db.connect()
    _seed_grounding_config(conn)
    doc = _mk_doc(client, [{"source": "Вавилон был велик.", "target": "Babylon was great."}])
    pid = doc["paragraphs"][0]["id"]
    conn.execute(
        "INSERT INTO term(paragraph_id,source_surface,source_lemma,context,char_start,char_end,"
        "difficulty,grounded_json,candidates_json,target_surface,pair_accuracy,recommended,note,"
        "trace_json) VALUES(?,'Existing','Existing','ctx',0,8,'green',NULL,'[]','X','green',NULL,"
        "'','{}')", (pid,))
    conn.commit()

    fake_client = _FakeClient([NER_ONE_TERM])
    client_for = _client_for_factory(fake_client)
    judge = asyncio.run(_judge_picks("Q1"))
    asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    assert fake_client.calls == []                  # NER never called — paragraph already had terms
    rows = conn.execute("SELECT source_surface FROM term WHERE paragraph_id=?", (pid,)).fetchall()
    assert [r["source_surface"] for r in rows] == ["Existing"]
    got = client.get(f"/api/documents/{doc['id']}").json()
    assert got["termsStatus"] == "done"


# ── try_start atomic guard ───────────────────────────────────────────────────

def test_try_start_transitions_none_to_running_exactly_once(client):
    doc = _mk_doc(client, [{"source": "s", "target": "t"}])
    conn = db.connect()
    conn.execute("UPDATE document SET terms_status='none' WHERE id=?", (doc["id"],))
    conn.commit()

    assert terminology_live.try_start(conn, doc["id"]) is True
    row = conn.execute("SELECT terms_status FROM document WHERE id=?", (doc["id"],)).fetchone()
    assert row["terms_status"] == "running"
    assert terminology_live.try_start(conn, doc["id"]) is False    # already running — no-op


def test_try_start_returns_false_for_seed_document_already_done(client):
    conn = db.connect()
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,"
        "created_at,terms_status) VALUES('Seed','ru','en','user',0,'seed','now','done')").lastrowid
    conn.commit()
    assert terminology_live.try_start(conn, doc_id) is False   # never re-runs for the seed document


# ── translate-doc launch hook ────────────────────────────────────────────────

def test_translate_run_calls_terms_launch_on_success(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"fake/model": (1e-6, 1e-6)})
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 ("fake/model", "http://fake", "k", "{}"))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        ("fake/model", "Translate {source_lang} into {target_lang}.", "{}"))
    conn.commit()
    doc = client.post("/api/documents", json=_body(
        sourceLang="ru", targetLang="en", precompute=False, translate=True,
        paragraphs=[{"source": "src", "target": ""}])).json()

    class _TClient:
        config = type("Cfg", (), {"model": "fake/model", "max_tokens": 256})()

        def complete(self, system, user):
            return _FakeResult("translated")

    calls = []

    def client_for(conn, name, params_override=None):
        return _TClient()

    def terms_launch(doc_id, cf):
        calls.append((doc_id, cf))

    asyncio.run(translate.run_translation(doc["id"], client_for, terms_launch))
    assert calls == [(doc["id"], client_for)]


def test_translate_run_skips_terms_launch_when_all_failed(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"fake/model": (1e-6, 1e-6)})
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 ("fake/model", "http://fake", "k", "{}"))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        ("fake/model", "Translate {source_lang} into {target_lang}.", "{}"))
    conn.commit()
    doc = client.post("/api/documents", json=_body(
        sourceLang="ru", targetLang="en", precompute=False, translate=True,
        paragraphs=[{"source": "src", "target": ""}])).json()

    class _FailingClient:
        config = type("Cfg", (), {"model": "fake/model", "max_tokens": 256})()

        def complete(self, system, user):
            raise ValueError("deterministic failure")

    calls = []

    def client_for(conn, name, params_override=None):
        return _FailingClient()

    def terms_launch(doc_id, cf):
        calls.append((doc_id, cf))

    asyncio.run(translate.run_translation(doc["id"], client_for, terms_launch))
    assert calls == []                    # translation failed entirely — terms never launched


def test_terms_launch_after_translate_uses_try_start_guard(client, monkeypatch):
    """app._terms_launch_after_translate bundles try_start + launch — a
    second call for a document whose terms already ran must not re-launch."""
    doc = _mk_doc(client, [{"source": "s", "target": "t"}])
    conn = db.connect()
    conn.execute("UPDATE document SET terms_status='done' WHERE id=?", (doc["id"],))
    conn.commit()

    launched = []
    monkeypatch.setattr(terminology_live, "launch", lambda *a, **kw: launched.append(a))
    app_mod._terms_launch_after_translate(doc["id"], lambda *a, **kw: None)
    assert launched == []                 # already 'done' — try_start refused the transition


# ── removed stub route ───────────────────────────────────────────────────────

def test_terms_stub_route_removed(client):
    doc = _mk_doc(client, [{"source": "s", "target": "t"}])
    pid = doc["paragraphs"][0]["id"]
    r = client.post(f"/api/paragraphs/{pid}/terms")
    assert r.status_code == 404
