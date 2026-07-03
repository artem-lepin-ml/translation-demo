"""Guard against advice-text leaking into apply-edit: prompt contract + heuristic."""
from __future__ import annotations

from palimpsest import paths
from palimpsest.webapp.judge import scoring_system_prompt


def test_preamble_states_suggestion_contract():
    p = scoring_system_prompt("accuracy", "ru", "en")
    disk = (paths.PROMPTS / "scoring" / "accuracy.md").read_text(encoding="utf-8")
    contract = p[: len(p) - len(disk)]
    assert "drop-in replacement" in contract
    assert "problematic_fragment" in contract
    assert "Consider" in contract and "if needed" in contract
    assert "empty string" in contract
    assert p.endswith(disk)


def test_preamble_contract_present_for_non_ru_en_pair():
    p = scoring_system_prompt("style", "de", "fr")
    assert "drop-in replacement" in p
    assert "This rubric was written for Russian" in p


from palimpsest.webapp.judge import looks_like_advice, sanitize_issue


def test_flags_debt_bondage_prod_case():
    assert looks_like_advice(
        "Use 'debt bondage', which is the standard anthropological and historical term "
        "that accurately conveys the temporary nature."
    )


def test_flags_city_states_case():
    assert looks_like_advice(
        "Replace with 'city-states' or 'city-state polities' throughout to align with "
        "standard English historiography."
    )


def test_flags_temple_centers_gloss_case():
    assert looks_like_advice("Consider 'temple centers' with a brief gloss if needed.")


def test_flags_quoted_alternatives_slash():
    assert looks_like_advice("'polis'/'city-state', depending on the register you prefer")


def test_flags_quoted_alternatives_with_trailing_clause():
    sug = "'slaves' or 'bondservants' - the latter is more accurate for the period described"
    assert looks_like_advice(sug)


def test_honest_single_replacement_not_flagged():
    assert not looks_like_advice("city-states")


def test_honest_multiword_replacement_not_flagged():
    assert not looks_like_advice("were partly incorporated into the land market")


def test_honest_replacement_with_word_use_inside_not_flagged():
    assert not looks_like_advice("the use of cuneiform script")


def test_empty_suggestion_not_flagged():
    assert not looks_like_advice("")
    assert not looks_like_advice("   ")


def test_sanitize_moves_advice_to_explanation():
    issue = {
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Term is inconsistent.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
        "severity": "minor",
        "mqmCategory": None,
    }
    out = sanitize_issue(issue)
    assert out["suggestion"] == ""
    assert out["explanation"].endswith("Advice: Use 'debt bondage', which is the standard term.")
    assert out["explanation"].startswith("Term is inconsistent.")


def test_sanitize_leaves_honest_suggestion_untouched():
    issue = {
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Should be hyphenated.",
        "suggestion": "city-states",
        "severity": "minor",
        "mqmCategory": None,
    }
    out = sanitize_issue(issue)
    assert out["suggestion"] == "city-states"
    assert out["explanation"] == "Should be hyphenated."


def test_sanitize_coerces_none_suggestion_to_empty_string():
    issue = {
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Should be hyphenated.",
        "suggestion": None,
        "severity": "minor",
        "mqmCategory": None,
    }
    out = sanitize_issue(issue)
    assert out["suggestion"] == ""


def test_sanitize_coerces_non_str_suggestion_to_str():
    issue = {
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Should be hyphenated.",
        "suggestion": 5,
        "severity": "minor",
        "mqmCategory": None,
    }
    out = sanitize_issue(issue)
    assert out["suggestion"] == "5"


def test_sanitize_is_idempotent():
    issue = {
        "targetFragment": "raby",
        "sourceFragment": "raby-ru",
        "explanation": "Wrong term.",
        "suggestion": "Consider 'bondservants' if needed.",
        "severity": "major",
        "mqmCategory": None,
    }
    once = sanitize_issue(issue)
    twice = sanitize_issue(dict(once))
    assert once == twice
    assert twice["suggestion"] == ""
    assert twice["explanation"].count("Advice:") == 1


from palimpsest.webapp.judge import _issue_from


def test_issue_from_sanitizes_advice_suggestion():
    raw = {
        "problematic_fragment": "city states",
        "source_fragment": "goroda-gosudarstva",
        "explanation": "Inconsistent term.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
    }
    out = _issue_from(raw)
    assert out["suggestion"] == ""
    assert "Advice: Use 'debt bondage'" in out["explanation"]
    assert out["explanation"].startswith("Inconsistent term.")


def test_issue_from_keeps_honest_suggestion():
    raw = {
        "problematic_fragment": "city states",
        "source_fragment": "goroda-gosudarstva",
        "explanation": "Hyphenate.",
        "suggestion": "city-states",
    }
    out = _issue_from(raw)
    assert out["suggestion"] == "city-states"
    assert out["explanation"] == "Hyphenate."


def test_apply_edit_rejects_sanitized_advice_issue(client):
    body = {
        "title": "advice guard", "sourceLang": "ru", "targetLang": "en", "precompute": False,
        "paragraphs": [{"source": "goroda-gosudarstva", "target": "city states"}],
    }
    doc = client.post("/api/documents", json=body).json()
    doc_id = doc["id"]
    pid = doc["paragraphs"][0]["id"]

    issue = _issue_from({
        "problematic_fragment": "city states",
        "source_fragment": "goroda-gosudarstva",
        "explanation": "Inconsistent term.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
    })
    assert issue["suggestion"] == ""

    from palimpsest.webapp import db
    conn = db.connect()
    with db._lock:
        # A freshly created document (via POST /api/documents) has no seeded
        # criterion/model rows; issue.criterion_id -> criterion.model_name are
        # FK-constrained, so insert both first (matches seed.py's shape,
        # deviation from the plan's snippet which assumed a seeded fixture
        # with 'cultural' already present).
        conn.execute(
            "INSERT OR IGNORE INTO model(name,base_url,api_key,params_json) "
            "VALUES('test-model','http://test','','{}')")
        conn.execute(
            "INSERT OR IGNORE INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
            "VALUES('cultural','Cultural Adaptation','test-model','p',1.0,10.0,0.15,'#fb923c',1)")
        iid = conn.execute(
            "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
            "suggestion,severity,mqm_category,status,kind,created_at) "
            "VALUES(?,?,?,?,?,?,?,?, 'open','live', datetime('now'))",
            (pid, "cultural", issue["targetFragment"], issue["sourceFragment"],
             issue["explanation"], issue["suggestion"], issue["severity"], None)).lastrowid
        conn.commit()

    r = client.post(f"/api/paragraphs/{pid}/apply-edit", json={"issueId": str(iid)})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "no_suggestion"

    doc_after = client.get(f"/api/documents/{doc_id}").json()
    para = next(p for p in doc_after["paragraphs"] if p["id"] == pid)
    assert para["target"] == "city states"
    assert "debt bondage" not in para["target"]
