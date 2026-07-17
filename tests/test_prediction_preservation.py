"""Owner invariant (wave-4 Б3): no user path may DELETE score/issue rows.

evaluate() supersedes prior open live issues instead of deleting them;
reset_document() archives live scores/issues instead of deleting them. Both
must stay queryable directly in the DB, but must never leak into the API
(_para_issues) once superseded/archived. The resurrect-guard narrowing must
not block re-detection after a reset.

Uses a fake judge (NO real OpenRouter calls) against an isolated sqlite DB,
same pattern as test_issue_dedup.py.
"""
from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import budget, db
    from palimpsest.webapp import seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "preserve.db")
    monkeypatch.setattr(db, "_conn", None)
    budget.reset()
    budget._CAP_USD = 100.0
    budget._CALL_CAP = 10000
    budget._PRICES = {}
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close()
        db._conn = None


def _install_fake_judge(monkeypatch, *, value_by_criterion=None, issues_by_criterion=None):
    """Patch judge_one so evaluate() runs against canned per-criterion results
    without any network call."""
    from types import SimpleNamespace
    from palimpsest.llm.client import Usage
    from palimpsest.webapp import app

    value_by_criterion = value_by_criterion or {}
    issues_by_criterion = issues_by_criterion or {}

    def _fake_judge_one(client, criterion_id, ru, en, *, source_lang="ru", target_lang="en", **_kw):
        value = value_by_criterion.get(criterion_id, 8.0)
        issues = issues_by_criterion.get(criterion_id, [])
        payload = {"final_score": value, "summary": "ok", "identified_issues": issues}
        data = json.loads(json.dumps(payload))
        from palimpsest.webapp.judge import _issue_from
        parsed_issues = [_issue_from(it) for it in (data.get("identified_issues") or [])]
        return {"value": float(data["final_score"]), "summary": data.get("summary", ""),
                "issues": parsed_issues, "usage": Usage(50, 20, 0, 0.0001)}

    monkeypatch.setattr(app, "_client_for", lambda conn, name: SimpleNamespace(
        config=SimpleNamespace(max_tokens=1024, extra_body=None)))
    monkeypatch.setattr(app, "judge_one", _fake_judge_one)


def _mk_issue(target_fragment, suggestion, explanation="incorrect term used"):
    return {
        "problematic_fragment": target_fragment, "source_fragment": "исходник",
        "explanation": explanation, "suggestion": suggestion,
    }


def _first_open_issue(conn, *, criterion_id=None):
    q = ("SELECT i.id iid, i.paragraph_id pid, i.criterion_id, i.target_fragment, i.suggestion, p.target "
         "FROM issue i JOIN paragraph p ON p.id = i.paragraph_id "
         "WHERE i.status='open' AND i.suggestion != ''")
    if criterion_id:
        q += f" AND i.criterion_id = '{criterion_id}'"
    q += " ORDER BY i.id"
    for r in conn.execute(q):
        if r["target_fragment"] and r["target_fragment"] in r["target"]:
            return r
    raise AssertionError("no matching seed issue found")


def test_reset_archives_live_rows_and_reeval_still_detects(seeded, monkeypatch):
    """Named preservation test (spec-required):
    seed -> evaluate a paragraph (produces live scores+issues) -> reset the doc
    -> pre-reset live rows STILL EXIST with kind='archived'/status='archived'
    -> re-evaluate the reset paragraph -> issues are returned again (the
    narrowed resurrect-guard doesn't block post-reset re-detection).
    """
    from palimpsest.webapp.app import EvaluateBody, evaluate, reset_document

    conn = seeded.connect()
    seed_iss = _first_open_issue(conn)
    pid, crit, frag, sugg = seed_iss["pid"], seed_iss["criterion_id"], seed_iss["target_fragment"], seed_iss["suggestion"]
    doc_id = conn.execute("SELECT document_id FROM paragraph WHERE id=?", (pid,)).fetchone()["document_id"]

    _install_fake_judge(monkeypatch, value_by_criterion={crit: 9.0},
                         issues_by_criterion={crit: [_mk_issue(frag, sugg)]})
    ev = asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[crit])))
    assert ev["scores"], "evaluate must have produced live scores"

    live_score_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM score WHERE paragraph_id=? AND kind='live'", (pid,))]
    live_issue_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM issue WHERE paragraph_id=? AND kind='live'", (pid,))]
    assert live_score_ids, "evaluate must have written live score rows"
    assert live_issue_ids, "evaluate must have written live issue rows"

    reset_document(doc_id)

    # pre-reset live rows still exist in the DB, now archived — not deleted.
    for sid in live_score_ids:
        row = conn.execute("SELECT kind FROM score WHERE id=?", (sid,)).fetchone()
        assert row is not None, "live score row must not be deleted by reset"
        assert row["kind"] == "archived"
    for iid in live_issue_ids:
        row = conn.execute("SELECT status FROM issue WHERE id=?", (iid,)).fetchone()
        assert row is not None, "live issue row must not be deleted by reset"
        assert row["status"] == "archived"

    # re-evaluate the reset paragraph: the narrowed resurrect-guard (only
    # accepted/dismissed block resurrection) must not treat the now-archived
    # rows as a reason to suppress re-detection of the same fragment.
    _install_fake_judge(monkeypatch, value_by_criterion={crit: 9.0},
                         issues_by_criterion={crit: [_mk_issue(frag, sugg)]})
    ev2 = asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[crit])))
    reopened = [i for i in ev2["issues"] if i["targetFragment"] == frag and i["criterionId"] == crit
                and i["status"] == "open"]
    assert len(reopened) == 1, "re-evaluate after reset must surface the fragment again, not be blocked by archived history"


def test_reevaluate_supersedes_not_deletes_prior_open_live_issue(seeded, monkeypatch):
    """A second evaluate() on the same criterion must flip the prior open live
    issue to 'superseded' (row preserved), not DELETE it."""
    from palimpsest.webapp.app import EvaluateBody, evaluate

    conn = seeded.connect()
    seed_iss = _first_open_issue(conn)
    pid, crit, frag, sugg = seed_iss["pid"], seed_iss["criterion_id"], seed_iss["target_fragment"], seed_iss["suggestion"]

    _install_fake_judge(monkeypatch, value_by_criterion={crit: 6.0},
                         issues_by_criterion={crit: [_mk_issue(frag, sugg)]})
    asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[crit])))
    first_live_id = conn.execute(
        "SELECT id FROM issue WHERE paragraph_id=? AND criterion_id=? AND kind='live' AND target_fragment=?",
        (pid, crit, frag)).fetchone()["id"]

    # second pass: judge emits a DIFFERENT fragment for the same criterion —
    # the first live issue is now stale (superseded), not re-emitted, not deleted.
    other_frag = "a completely different phrase not previously flagged"
    _install_fake_judge(monkeypatch, value_by_criterion={crit: 7.0},
                         issues_by_criterion={crit: [_mk_issue(other_frag, "fix it")]})
    ev2 = asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[crit])))

    row = conn.execute("SELECT status FROM issue WHERE id=?", (first_live_id,)).fetchone()
    assert row is not None, "superseded issue row must not be deleted"
    assert row["status"] == "superseded"

    api_ids = {i["id"] for i in ev2["issues"]}
    assert str(first_live_id) not in api_ids, "superseded issues must not appear in _para_issues output"


def test_para_issues_excludes_superseded_and_archived(seeded, monkeypatch):
    """Direct unit check on _para_issues: superseded and archived rows are
    dropped from the API output regardless of which elif branch they'd
    otherwise match (the full-body rewrite must guard every branch)."""
    from palimpsest.webapp.app import _para_issues

    conn = seeded.connect()
    seed_iss = _first_open_issue(conn)
    pid, crit = seed_iss["pid"], seed_iss["criterion_id"]

    # plant a superseded live issue whose criterion IS in live_crits (would
    # have leaked via the old unguarded elif branch)
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at) "
        "VALUES(?,?,?,?,?,?,'live',?)", (pid, crit, 8.0, "s", 8.0, "k", "2026-01-01"))
    conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
        "suggestion,severity,mqm_category,status,kind,created_at) "
        "VALUES(?,?,?,?,?,?,?,?, 'superseded','live',?)",
        (pid, crit, "superseded fragment", "src", "expl", "", "minor", None, "2026-01-01"))
    # plant an archived live issue for the same criterion too
    conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
        "suggestion,severity,mqm_category,status,kind,created_at) "
        "VALUES(?,?,?,?,?,?,?,?, 'archived','live',?)",
        (pid, crit, "archived fragment", "src", "expl", "", "minor", None, "2026-01-01"))
    # plant a still-open SEED issue for the same criterion: once a criterion is
    # in live_crits, its seed-open issue is implicitly superseded and must not
    # leak either (mutual exclusivity between the live and seed open branches).
    conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
        "suggestion,severity,mqm_category,status,kind,created_at) "
        "VALUES(?,?,?,?,?,?,?,?, 'open','seed',?)",
        (pid, crit, "stale seed fragment", "src", "expl", "", "minor", None, "2026-01-01"))
    conn.commit()

    out = _para_issues(conn, pid)
    fragments = {i["targetFragment"] for i in out}
    assert "superseded fragment" not in fragments
    assert "archived fragment" not in fragments
    assert "stale seed fragment" not in fragments, (
        "an open seed issue whose criterion has been live-evaluated must not leak "
        "(it is implicitly superseded by the live branch owning that criterion)"
    )
    statuses = {i["status"] for i in out}
    assert "superseded" not in statuses
    assert "archived" not in statuses
