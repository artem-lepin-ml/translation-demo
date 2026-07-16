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
import time

import pytest

from palimpsest.llm.client import LLMClient, LLMConfig
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

    # `timeout` mirrors LLMConfig.timeout's real default (30.0, llm/client.py)
    # -- terminology_live._effective_ner_timeout reads client.config.timeout,
    # so a fake missing this attribute would AttributeError, not just
    # silently use a wrong value.
    config = type("Cfg", (), {"max_tokens": 2048, "timeout": 30.0})()


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
NER_HANA_TERM = '[{"surface":"Ханейское царство","lemma":"Ханейское царство","category":"place"}]'


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


# ── label-guess tier (live wiring, owner-approved 2026-07-17) ───────────────
# Enables candidates.py's "label-guess" search_mode in the live pipeline: when
# lemma/surface/cirrus/sitelink all find 0 candidates, one extra LLM call
# guesses the entity's exact Wikidata label before the mention is given up as
# no_candidates. Reference case: the paper's own Figure 1, «Ханейское
# царство» (canonical Wikidata label «Хана» / "Kingdom of Hana", Q425405).

def test_run_label_guess_tier_resolves_no_candidates_mention(client):
    """All deterministic tiers find 0 hits for the raw surface/lemma; the
    label-guess tier's guessed label ("Хана") reaches search and resolves a
    mention that used to die as no_candidates. The guessed label doesn't
    lexically match the surface, so this also exercises the disambiguation
    judge escalation on top of the label-guess widened candidate."""
    wd = _FakeWD(
        hits={"Хана": [{"id": "Q425405"}]},          # only the GUESSED label has a hit
        entities={"Q425405": _entity("Q425405", "Hana", "Хана", enwiki="Hana")},
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(terminology_live, "WikidataClient", lambda *a, **kw: wd)
        conn = db.connect()
        _seed_grounding_config(conn)
        doc = _mk_doc(client, [{"source": "Ханейское царство было соседом Мари.",
                                 "target": "The Kingdom of Hana bordered Mari."}])

        guess_reply = json.dumps({"label_ru": "Хана", "label_en": None})
        fake_client = _FakeClient([NER_HANA_TERM, guess_reply])
        client_for = _client_for_factory(fake_client)
        judge = asyncio.run(_judge_picks("Q425405"))  # guessed label != surface, judge escalates
        asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    pid = doc["paragraphs"][0]["id"]
    row = conn.execute("SELECT * FROM term WHERE paragraph_id=?", (pid,)).fetchone()
    assert row is not None
    assert row["difficulty"] == "yellow"                # llm_disambiguation, not no_candidates/red
    trace = json.loads(row["trace_json"])
    assert trace["resolved_by"] == "llm_disambiguation"
    assert trace["chosen_qid"] == "Q425405"
    guess_queries = [q for q in trace["queries"] if q["kind"] == "label_guess"]
    assert guess_queries, "expected a label_guess-tier query in the trace"
    assert all(q["strategy"] == "guess" for q in guess_queries)   # distinguishable from "prefix"
    # the fake LLM client is called exactly twice: NER extract, then the guess
    assert len(fake_client.calls) == 2
    assert fake_client.calls[1][0] == terminology_live.DEFAULT_LABEL_GUESS_SYSTEM_PROMPT


def test_run_label_guesser_not_called_when_normal_tiers_find_candidates(client):
    """The label-guess tier must only fire on a genuine 0-candidates miss --
    a mention resolved by the deterministic prefix-search tier (rung 1) must
    never reach the (LLM-backed) guesser at all."""
    wd = _FakeWD(
        hits={"Вавилон": [{"id": "Q23522"}]},
        entities={"Q23522": _entity("Q23522", "Babylon", "Вавилон", enwiki="Babylon")},
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(terminology_live, "WikidataClient", lambda *a, **kw: wd)
        conn = db.connect()
        _seed_grounding_config(conn)
        doc = _mk_doc(client, [{"source": "Вавилон был велик.", "target": "Babylon was great."}])

        fake_client = _FakeClient([NER_ONE_TERM])        # only ONE reply configured -- NER
        client_for = _client_for_factory(fake_client)
        judge = asyncio.run(_judge_picks("Q23522"))
        asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    # If the guesser had been invoked it would have called .complete() a
    # second time (returning the clamped last/only reply) -- exactly one call
    # proves the guesser was never reached.
    assert len(fake_client.calls) == 1
    pid = doc["paragraphs"][0]["id"]
    row = conn.execute("SELECT * FROM term WHERE paragraph_id=?", (pid,)).fetchone()
    assert row["difficulty"] == "green"


def test_run_builds_and_passes_label_guesser_into_grounder(client):
    """Unit-level wiring check: _run constructs LabelFirstGrounding with
    search_mode='label-guess' and a callable label_guesser -- both built from
    the same client_for the disambiguation judge/NER call already use."""
    captured: dict = {}
    real_cls = terminology_live.LabelFirstGrounding

    class _CapturingGrounding(real_cls):
        def __init__(self, wd, config=None, *, label_guesser=None):
            captured["config"] = config
            captured["label_guesser"] = label_guesser
            super().__init__(wd, config=config, label_guesser=label_guesser)

    wd = _FakeWD()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(terminology_live, "WikidataClient", lambda *a, **kw: wd)
        mp.setattr(terminology_live, "LabelFirstGrounding", _CapturingGrounding)
        conn = db.connect()
        _seed_grounding_config(conn)
        doc = _mk_doc(client, [{"source": "Ничего не найдено.", "target": "Nothing found."}])

        fake_client = _FakeClient([NER_EMPTY])
        client_for = _client_for_factory(fake_client)
        judge = asyncio.run(_judge_picks("Q1"))
        asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    assert captured["config"].search_mode == "label-guess"
    assert callable(captured["label_guesser"])


def test_label_guess_call_logged_under_distinct_budget_endpoint(client):
    """The label-guess LLM call is logged to the budget under its own
    'label_guess' endpoint tag -- distinct from the disambiguation judge's
    'terms_grounding' tag and the NER call's 'terms_extract' tag -- so
    spend/call-count stay separately attributable (see
    terminology_live._grounding_label_guess_live)."""
    wd = _FakeWD(
        hits={"Хана": [{"id": "Q425405"}]},
        entities={"Q425405": _entity("Q425405", "Hana", "Хана", enwiki="Hana")},
    )
    logged: list[dict] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(terminology_live, "WikidataClient", lambda *a, **kw: wd)
        mp.setattr(terminology_live.budget, "log_call", lambda rec: logged.append(rec))
        conn = db.connect()
        _seed_grounding_config(conn)
        doc = _mk_doc(client, [{"source": "Ханейское царство было соседом Мари.",
                                 "target": "The Kingdom of Hana bordered Mari."}])

        guess_reply = json.dumps({"label_ru": "Хана", "label_en": None})
        fake_client = _FakeClient([NER_HANA_TERM, guess_reply])
        client_for = _client_for_factory(fake_client)
        judge = asyncio.run(_judge_picks("Q425405"))
        asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    endpoints = {rec["endpoint"] for rec in logged}
    assert "label_guess" in endpoints
    assert "terms_extract" in endpoints              # NER's own tag, sanity check they coexist


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


# ── startup sweep for stuck terms_status='running' (stability fix: Issue A) ──

def test_startup_sweep_resets_stuck_running_to_none(client):
    """app._reset_stuck_terms recovers a document left at terms_status=
    'running' by a killed process -- called once from the FastAPI lifespan
    right after migrate(), before any request is served. A 'done' document
    must be left untouched."""
    conn = db.connect()
    running_id = _mk_doc(client, [{"source": "s1", "target": "t1"}])["id"]
    done_id = _mk_doc(client, [{"source": "s2", "target": "t2"}])["id"]
    conn.execute("UPDATE document SET terms_status='running' WHERE id=?", (running_id,))
    conn.execute("UPDATE document SET terms_status='done' WHERE id=?", (done_id,))
    conn.commit()

    n = app_mod._reset_stuck_terms(conn)

    assert n == 1
    row = conn.execute("SELECT terms_status FROM document WHERE id=?", (running_id,)).fetchone()
    assert row["terms_status"] == "none"
    row2 = conn.execute("SELECT terms_status FROM document WHERE id=?", (done_id,)).fetchone()
    assert row2["terms_status"] == "done"           # untouched


def test_startup_sweep_is_noop_when_nothing_stuck(client):
    conn = db.connect()
    doc_id = _mk_doc(client, [{"source": "s", "target": "t"}])["id"]
    conn.execute("UPDATE document SET terms_status='done' WHERE id=?", (doc_id,))
    conn.commit()

    assert app_mod._reset_stuck_terms(conn) == 0
    row = conn.execute("SELECT terms_status FROM document WHERE id=?", (doc_id,)).fetchone()
    assert row["terms_status"] == "done"


def test_startup_sweep_leaves_failed_and_none_alone(client):
    conn = db.connect()
    doc_id = _mk_doc(client, [{"source": "s", "target": "t"}])["id"]
    conn.execute("UPDATE document SET terms_status='failed' WHERE id=?", (doc_id,))
    conn.commit()

    assert app_mod._reset_stuck_terms(conn) == 0
    row = conn.execute("SELECT terms_status FROM document WHERE id=?", (doc_id,)).fetchone()
    assert row["terms_status"] == "failed"           # sweep only ever touches 'running'


# ── timeout race fixes (stability fix: Issue C) ──────────────────────────────

def test_ner_timeout_exceeds_sdk_client_timeout():
    """The NER leg's wait_for ceiling must always exceed the real SDK client
    timeout it wraps (LLMConfig.timeout, 30s default) -- otherwise wait_for
    fires first and abandons a still-running SDK call. Exercised against a
    REAL LLMConfig/LLMClient (no network call: constructing openai.OpenAI
    does not touch the network), not a hardcoded number, so this stays
    correct if either default changes."""
    default_client = LLMClient(LLMConfig(model="m", base_url="http://x", api_key="k"))
    assert default_client.config.timeout == 30.0    # sanity: pin the value this test reasons about
    eff = terminology_live._effective_ner_timeout(default_client)
    assert eff > default_client.config.timeout

    # Even a client explicitly configured with a SMALL SDK timeout must not
    # collapse the ceiling below the env-configured NER floor.
    small_cfg = LLMConfig(model="m", base_url="http://x", api_key="k", timeout=5.0)
    small_timeout_client = LLMClient(small_cfg)
    eff_small = terminology_live._effective_ner_timeout(small_timeout_client)
    assert eff_small > small_timeout_client.config.timeout
    assert eff_small >= terminology_live._NER_TIMEOUT

    # And a LARGE SDK timeout must still be cleared with the same margin.
    large_cfg = LLMConfig(model="m", base_url="http://x", api_key="k", timeout=120.0)
    large_timeout_client = LLMClient(large_cfg)
    eff_large = terminology_live._effective_ner_timeout(large_timeout_client)
    assert eff_large > large_timeout_client.config.timeout


def test_grounding_timeout_constant_is_generous():
    """The grounding leg's ceiling (previously absent entirely) must be
    generous enough to comfortably outlast a normal paragraph run (NER's own
    ceiling alone can reach ~35s; the grounding leg additionally makes
    Wikidata network calls and zero or more judge calls) -- this is a
    defense-in-depth ceiling, not a tight SDK-aligned one."""
    assert terminology_live._GROUNDING_TIMEOUT >= 60.0


def test_grounding_leg_timeout_fires_and_paragraph_fails_gracefully(client, monkeypatch):
    """A pipeline.run() call that outlives _GROUNDING_TIMEOUT must not stall
    the whole run forever -- the wait_for added around the to_thread call
    fires, gets caught by _run's existing per-paragraph except, and the run
    finishes with that paragraph simply skipped (same per-paragraph failure
    contract the NER leg already had). Only the paragraph's OWN pipeline.run
    is slow here; the ceiling is monkeypatched way down so the test itself
    stays fast."""
    monkeypatch.setattr(terminology_live, "_GROUNDING_TIMEOUT", 0.05)

    def _hang(*a, **kw):
        time.sleep(0.3)                              # outlives the 0.05s ceiling above
        return []

    monkeypatch.setattr(terminology_live.pipeline, "run", _hang)
    conn = db.connect()
    _seed_grounding_config(conn)
    doc = _mk_doc(client, [{"source": "Вавилон.", "target": "Babylon."}])

    fake_client = _FakeClient([NER_ONE_TERM])
    client_for = _client_for_factory(fake_client)
    judge = asyncio.run(_judge_picks("Q1"))
    asyncio.run(terminology_live.run(doc["id"], client_for, judge))

    got = client.get(f"/api/documents/{doc['id']}").json()
    assert got["termsStatus"] == "failed"            # only paragraph timed out -> nothing succeeded
    assert got["paragraphs"][0]["terms"] == []
