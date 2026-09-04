"""Regression: evaluate() must not resurrect a dismissed/accepted issue as a new
'open' duplicate when the live judge re-emits the same fragment on re-judge.

Uses a fake judge (NO real OpenRouter calls) against an isolated sqlite DB.
"""
from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import budget, db
    from palimpsest.webapp import seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "dedup.db")
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
    # keys match judge._issue_from's expected raw LLM-JSON shape.
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


def test_dismissed_issue_not_duplicated_on_rejudge(seeded, monkeypatch):
    """Dismiss an open issue, then re-judge the same criterion with the judge
    re-emitting the identical fragment. No new open duplicate must appear."""
    from palimpsest.webapp.app import EvaluateBody, IssueStatusBody, evaluate, patch_issue_status

    conn = seeded.connect()
    iss = _first_open_issue(conn)
    pid, iid, crit, frag, sugg = iss["pid"], iss["iid"], iss["criterion_id"], iss["target_fragment"], iss["suggestion"]

    out = patch_issue_status(iid, IssueStatusBody(status="dismissed"))
    assert out["status"] == "dismissed"

    _install_fake_judge(monkeypatch, value_by_criterion={crit: 7.0},
                         issues_by_criterion={crit: [_mk_issue(frag, sugg)]})
    ev = asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[crit])))

    row = conn.execute("SELECT status FROM issue WHERE id=?", (iid,)).fetchone()
    assert row["status"] == "dismissed", "dismissed issue must not flip back to open"

    open_dupes = [i for i in ev["issues"] if i["status"] == "open" and i["targetFragment"] == frag
                  and i["criterionId"] == crit]
    assert len(open_dupes) == 0, "re-judge must not resurrect a dismissed fragment as a new open issue"

    # exactly one row total for that fragment/criterion/paragraph — no duplicate insert
    rows = conn.execute(
        "SELECT COUNT(*) n FROM issue WHERE paragraph_id=? AND criterion_id=? AND target_fragment=?",
        (pid, crit, frag)).fetchone()
    assert rows["n"] == 1


def test_dismissed_issue_different_fragment_still_inserts(seeded, monkeypatch):
    """Dismissing one fragment must not suppress a genuinely NEW fragment the
    judge flags on re-judge for the same criterion/paragraph."""
    from palimpsest.webapp.app import EvaluateBody, IssueStatusBody, evaluate, patch_issue_status

    conn = seeded.connect()
    iss = _first_open_issue(conn)
    pid, iid, crit, frag = iss["pid"], iss["iid"], iss["criterion_id"], iss["target_fragment"]

    patch_issue_status(iid, IssueStatusBody(status="dismissed"))

    other_frag = "a completely different phrase not seen before"
    _install_fake_judge(monkeypatch, value_by_criterion={crit: 7.0},
                         issues_by_criterion={crit: [_mk_issue(other_frag, "fix it")]})
    ev = asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[crit])))

    new_open = [i for i in ev["issues"] if i["status"] == "open" and i["targetFragment"] == other_frag
                and i["criterionId"] == crit]
    assert len(new_open) == 1, "a genuinely different fragment must still be inserted as a new open issue"
    assert frag != other_frag


def test_accepted_issue_not_duplicated_on_rejudge(seeded, monkeypatch):
    """apply-edit marks an issue 'accepted'; if the live judge re-emits the same
    fragment on the next re-judge (e.g. suggestion not fully cleaning it up),
    no new open duplicate must be inserted either."""
    from palimpsest.webapp.app import ApplyEditBody, EvaluateBody, apply_edit, evaluate

    conn = seeded.connect()
    iss = _first_open_issue(conn)
    pid, iid, crit, frag, sugg = iss["pid"], iss["iid"], iss["criterion_id"], iss["target_fragment"], iss["suggestion"]

    out = apply_edit(pid, ApplyEditBody(issueId=str(iid)))
    assert out["issue"]["status"] == "accepted"

    _install_fake_judge(monkeypatch, value_by_criterion={crit: 8.0},
                         issues_by_criterion={crit: [_mk_issue(frag, sugg)]})
    ev = asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[crit])))

    row = conn.execute("SELECT status FROM issue WHERE id=?", (iid,)).fetchone()
    assert row["status"] == "accepted", "accepted issue must not flip back to open"

    open_dupes = [i for i in ev["issues"] if i["status"] == "open" and i["targetFragment"] == frag
                  and i["criterionId"] == crit]
    assert len(open_dupes) == 0, "re-judge must not resurrect an accepted fragment as a new open issue"
