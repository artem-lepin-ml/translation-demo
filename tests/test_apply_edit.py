"""apply-edit safety: empty suggestion must not silently delete the fragment.

45/240 seed issues carry suggestion='' (the judge flagged a problem but proposed
no rewrite). Accepting such an issue must be a no-op error, never a deletion of
the flagged target fragment.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import db
    from palimpsest.webapp import seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close()
        db._conn = None


def _find_issue(conn, *, empty: bool):
    """An issue whose target_fragment is present in its paragraph target,
    with suggestion empty (empty=True) or non-empty (empty=False)."""
    op = "=" if empty else "!="
    for r in conn.execute(
        f"SELECT i.id, i.paragraph_id, i.target_fragment, i.suggestion, p.target "
        f"FROM issue i JOIN paragraph p ON p.id=i.paragraph_id "
        f"WHERE i.suggestion {op} '' AND i.target_fragment != '' ORDER BY i.id"
    ):
        if r["target_fragment"] in r["target"]:
            return r
    raise AssertionError(f"no seed issue with empty={empty} and a locatable fragment")


def test_empty_suggestion_is_rejected_not_deleted(seeded):
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=True)
    pid = iss["paragraph_id"]
    before = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]

    with pytest.raises(HTTPException) as ei:
        apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
    assert ei.value.status_code in (400, 422)

    after = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    assert after == before, "empty-suggestion accept must not mutate the translation"
    status = conn.execute("SELECT status FROM issue WHERE id=?", (iss["id"],)).fetchone()["status"]
    assert status == "open", "rejected accept must leave the issue open"


def test_nonempty_suggestion_replaces_fragment(seeded):
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]

    out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
    assert iss["suggestion"] in out["target"]
    assert out["issue"]["status"] == "accepted"


def test_splice_collapses_boundary_duplicate():
    """A suggestion that repeats the word before the fragment must not duplicate it."""
    from palimpsest.webapp.app import _splice_suggestion

    target = "to peasants and were partly drawn into buying and selling. This"
    out = _splice_suggestion(target, "drawn into buying and selling", "partly incorporated into the land market")
    assert "partly partly" not in out
    assert "were partly incorporated into the land market" in out


def test_splice_returns_none_when_fragment_absent():
    from palimpsest.webapp.app import _splice_suggestion

    assert _splice_suggestion("hello world", "absent fragment", "x") is None


def test_splice_whitespace_only_mismatch_applies():
    """Earlier accepts can reflow spacing; token-identical fragments must still match."""
    from palimpsest.webapp.app import _splice_suggestion

    target = "the  fertile\n delta of the river"
    out = _splice_suggestion(target, "fertile delta of", "rich floodplain of")
    assert out is not None
    assert "rich floodplain of the river" in out


def test_splice_none_when_tokens_overlapped():
    """A fragment partially overwritten by a prior edit is genuinely gone → None."""
    from palimpsest.webapp.app import _splice_suggestion

    # prior edit replaced "fertile delta" with "floodplain" — old fragment's tokens are gone
    assert _splice_suggestion("the floodplain of the river", "fertile delta of", "x") is None


def test_apply_edit_whitespace_reflow_still_applies(seeded):
    """Route-level: double-spaced fragment region still applies (200, accepted)."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    frag = iss["target_fragment"]
    reflowed = conn.execute(
        "SELECT target FROM paragraph WHERE id=?", (pid,)
    ).fetchone()["target"].replace(frag, frag.replace(" ", "  "), 1)
    conn.execute("UPDATE paragraph SET target=? WHERE id=?", (reflowed, pid))
    conn.commit()

    out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
    assert out["issue"]["status"] == "accepted"
    assert iss["suggestion"] in out["target"]


def test_apply_edit_overlapped_fragment_is_422(seeded):
    """Route-level: fragment whose tokens were removed by a prior edit → 422."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    gutted = conn.execute(
        "SELECT target FROM paragraph WHERE id=?", (pid,)
    ).fetchone()["target"].replace(iss["target_fragment"], "", 1)
    conn.execute("UPDATE paragraph SET target=? WHERE id=?", (gutted, pid))
    conn.commit()

    with pytest.raises(HTTPException) as ei:
        apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
    assert ei.value.status_code == 422
    assert ei.value.detail == {"error": "fragment_not_found"}


def test_apply_edit_nonnumeric_id_is_404(seeded):
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    for bad in ("abc", "", "1.5"):
        with pytest.raises(HTTPException) as ei:
            apply_edit(1, ApplyEditBody(issueId=bad))
        assert ei.value.status_code == 404, f"issueId={bad!r} should 404, not 500"



def _plant_legacy_advice_row(conn, pid: int, criterion_id: str, target_fragment: str) -> int:
    """Insert an issue row with a non-empty advice suggestion directly via SQL,
    bypassing sanitize_issue — simulates a pre-guard prod row that ingest never saw."""
    return conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
        "suggestion,severity,mqm_category,status,kind,created_at) "
        "VALUES(?,?,?,?,?,?,?,?, 'open','seed', datetime('now'))",
        (pid, criterion_id, target_fragment, "", "Term is inconsistent.",
         "Use 'debt bondage', which is the standard anthropological term.",
         "minor", None),
    ).lastrowid


def test_apply_edit_rejects_legacy_nonempty_advice_row(seeded):
    """A legacy row (pre-guard, non-empty advice suggestion) must not splice into the target."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    criterion_id = conn.execute(
        "SELECT criterion_id FROM issue WHERE id=?", (iss["id"],)
    ).fetchone()["criterion_id"]
    frag = iss["target_fragment"]
    before = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]

    iid = _plant_legacy_advice_row(conn, pid, criterion_id, frag)
    conn.commit()

    with pytest.raises(HTTPException) as ei:
        apply_edit(pid, ApplyEditBody(issueId=str(iid)))
    assert ei.value.status_code == 422
    assert ei.value.detail == {"error": "advice_suggestion"}

    after = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    assert after == before, "advice-suggestion accept must not mutate the translation"
    status = conn.execute("SELECT status FROM issue WHERE id=?", (iid,)).fetchone()["status"]
    assert status == "open", "rejected accept must leave the issue open"


def test_accept_all_style_sequence_skips_advice_row_applies_honest_rows(seeded):
    """Batch-accept semantics: honest rows apply; a legacy advice row planted in the
    same paragraph is skipped (422 advice_suggestion) without blocking the honest one."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    honest = _find_issue(conn, empty=False)
    pid = honest["paragraph_id"]
    criterion_id = conn.execute(
        "SELECT criterion_id FROM issue WHERE id=?", (honest["id"],)
    ).fetchone()["criterion_id"]
    # The advice row's fragment must SURVIVE the honest edit: a fragment that is
    # gone from the rewritten target would be swept to 'outdated' by sibling
    # invalidation before its own apply attempt, and the batch would then hit
    # 422 not_open instead of the advice path this test is about.
    target = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    frag_pos = target.find(honest["target_fragment"])
    assert frag_pos != -1
    after = target[frag_pos + len(honest["target_fragment"]):]
    before = target[:frag_pos]
    chunk = (after if len(after.strip()) > 20 else before).strip()
    survivor_frag = chunk[5:45].strip() or chunk
    assert survivor_frag and survivor_frag in target
    advice_iid = _plant_legacy_advice_row(conn, pid, criterion_id, survivor_frag)
    conn.commit()

    applied, skipped = 0, 0
    for iid in (honest["id"], advice_iid):
        try:
            apply_edit(pid, ApplyEditBody(issueId=str(iid)))
            applied += 1
        except HTTPException as e:
            assert e.status_code == 422
            assert e.detail == {"error": "advice_suggestion"}
            skipped += 1

    assert applied == 1
    assert skipped == 1
    status = conn.execute("SELECT status FROM issue WHERE id=?", (advice_iid,)).fetchone()["status"]
    assert status == "open"



def test_apply_edit_invalidates_overlapping_open_sibling(seeded):
    """After a successful apply, a sibling open issue whose fragment is no longer
    locatable in the rewritten target is flipped to 'outdated' and returned in
    the response's siblingIssues."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    target = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    # _find_issue's SELECT doesn't project criterion_id — fetch the full row.
    criterion_id = conn.execute("SELECT criterion_id FROM issue WHERE id=?", (iss["id"],)).fetchone()[0]

    # Craft a sibling open issue on the SAME paragraph whose fragment overlaps the
    # region the accepted edit rewrites (so it is gone after the splice).
    overlap_frag = iss["target_fragment"]           # identical region → certainly overlapped
    sib_id = conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
        "explanation,suggestion,severity,mqm_category,status,kind) "
        "VALUES(?,?,?,?,?,?,?,?, 'open','live')",
        (pid, criterion_id, overlap_frag, "", "sib", "zzz", "minor", None),
    ).lastrowid
    conn.commit()

    out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))

    # Accepted issue unchanged in shape
    assert out["issue"]["status"] == "accepted"
    # Sibling now outdated, persisted
    sib_status = conn.execute("SELECT status FROM issue WHERE id=?", (sib_id,)).fetchone()["status"]
    assert sib_status == "outdated"
    # Response carries the updated sibling(s)
    sib_ids = {i["id"]: i["status"] for i in out["siblingIssues"]}
    assert sib_ids.get(str(sib_id)) == "outdated"


def test_apply_edit_keeps_still_locatable_sibling_open(seeded):
    """A sibling whose fragment survives the edit (whitespace-tolerant match still
    hits) stays open and is NOT in siblingIssues."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    target = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    # _find_issue's SELECT doesn't project criterion_id — fetch the full row.
    criterion_id = conn.execute("SELECT criterion_id FROM issue WHERE id=?", (iss["id"],)).fetchone()[0]

    # A disjoint word that survives the splice.
    survivor = next(w for w in target.split() if w and w not in iss["target_fragment"])
    sib_id = conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
        "explanation,suggestion,severity,mqm_category,status,kind) "
        "VALUES(?,?,?,?,?,?,?,?, 'open','live')",
        (pid, criterion_id, survivor, "", "sib", "zzz", "minor", None),
    ).lastrowid
    conn.commit()

    out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))

    sib_status = conn.execute("SELECT status FROM issue WHERE id=?", (sib_id,)).fetchone()["status"]
    assert sib_status == "open"
    assert all(i["id"] != str(sib_id) for i in out["siblingIssues"])


def test_apply_edit_rejects_dismissed_issue(seeded):
    """Accept on a dismissed issue must 422 not_open, leaving text and status untouched."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    conn.execute("UPDATE issue SET status='dismissed' WHERE id=?", (iss["id"],))
    conn.commit()
    before = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]

    with pytest.raises(HTTPException) as ei:
        apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
    assert ei.value.status_code == 422
    assert ei.value.detail == {"error": "not_open"}

    after = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    assert after == before, "accept on a dismissed issue must not mutate the translation"
    status = conn.execute("SELECT status FROM issue WHERE id=?", (iss["id"],)).fetchone()["status"]
    assert status == "dismissed", "accept on a dismissed issue must not flip its status"


def test_apply_edit_rejects_accepted_issue(seeded):
    """Accept on an already-accepted issue must 422 not_open, leaving text untouched."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    # First accept goes through normally.
    apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
    after_first = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]

    with pytest.raises(HTTPException) as ei:
        apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
    assert ei.value.status_code == 422
    assert ei.value.detail == {"error": "not_open"}

    after_second = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    assert after_second == after_first, "re-accept must not splice the suggestion a second time"
    status = conn.execute("SELECT status FROM issue WHERE id=?", (iss["id"],)).fetchone()["status"]
    assert status == "accepted"


def test_apply_edit_rolls_back_on_mid_loop_exception(seeded, monkeypatch):
    """A failure partway through the sibling-invalidation loop must not leave a
    partial write (paragraph rewritten / issue accepted) visible from a fresh
    connection — the whole write section is one transaction."""
    import palimpsest.webapp.app as app_module

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    criterion_id = conn.execute("SELECT criterion_id FROM issue WHERE id=?", (iss["id"],)).fetchone()[0]
    before_target = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]

    # Two open siblings so the loop calls the (monkeypatched) matcher at least twice.
    for i in range(2):
        conn.execute(
            "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
            "explanation,suggestion,severity,mqm_category,status,kind) "
            "VALUES(?,?,?,?,?,?,?,?, 'open','live')",
            (pid, criterion_id, f"sib-frag-{i}", "", "sib", "zzz", "minor", None),
        )
    conn.commit()

    calls = {"n": 0}
    real_splice = app_module._splice_suggestion

    def flaky_splice(target, frag, suggestion):
        if frag and frag.startswith("sib-frag"):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom mid-loop")
        return real_splice(target, frag, suggestion)

    monkeypatch.setattr(app_module, "_splice_suggestion", flaky_splice)

    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    with pytest.raises(RuntimeError):
        apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))

    # Fresh connection — bypasses any in-process cached state.
    fresh = sqlite3.connect(str(seeded.DB_PATH))
    fresh.row_factory = sqlite3.Row
    try:
        target_after = fresh.execute(
            "SELECT target FROM paragraph WHERE id=?", (pid,)
        ).fetchone()["target"]
        issue_status_after = fresh.execute(
            "SELECT status FROM issue WHERE id=?", (iss["id"],)
        ).fetchone()["status"]
    finally:
        fresh.close()

    assert target_after == before_target, "no partial paragraph rewrite must survive a mid-loop crash"
    assert issue_status_after == "open", "issue must not be left half-accepted after rollback"


def test_apply_edit_never_invalidates_accepted_or_dismissed_siblings(seeded):
    """Only status='open' siblings are candidates; accepted/dismissed are left alone
    even if their fragment is now gone."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    # _find_issue's SELECT doesn't project criterion_id — fetch the full row.
    criterion_id = conn.execute("SELECT criterion_id FROM issue WHERE id=?", (iss["id"],)).fetchone()[0]

    for status in ("accepted", "dismissed"):
        sid = conn.execute(
            "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
            "explanation,suggestion,severity,mqm_category,status,kind) "
            "VALUES(?,?,?,?,?,?,?,?,?, 'live')",
            (pid, criterion_id, iss["target_fragment"], "", "s", "z", "minor", None, status),
        ).lastrowid
        conn.commit()
        out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
        assert all(i["id"] != str(sid) for i in out["siblingIssues"])
        # restore target for the next iteration
        conn.execute("UPDATE paragraph SET target=seed_target WHERE id=?", (pid,))
        conn.execute("UPDATE issue SET status='open' WHERE id=?", (iss["id"],))
        conn.commit()
