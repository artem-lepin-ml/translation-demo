"""Guards for the disambiguated demo terminology seed (terminology_out.json).

``scripts/rebuild_demo.py`` runs the G6 ``label_first`` grounding + live LLM
judge over the demo mentions and writes ``data/seed/terminology_out.json``,
which ``scripts/load_terms.py`` loads verbatim into the ``term`` table (the
canonical demo reseed). These tests pin the invariants that the
disambiguation pass establishes so a stale/hand-patched artifact (e.g. the
pre-fix ``judge_unavailable`` gaps or the ``ambiguous_candidates`` hand-patch)
can't silently return, and that the mention-lemma fix keeps the core entities
groundable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest import paths

OUT_FILE = paths.DATA / "seed" / "terminology_out.json"

# LabelFirstGrounding's decision-table enum (grounding/label_first.py docstring).
PIPELINE_RESOLVED_BY = {
    "exact_label",
    "llm_disambiguation",
    "judge_rejected",
    "judge_unavailable",
    "wikidata_unavailable",
    "no_candidates",
}
# The demo seed is fully disambiguated: every escalation carries a real judge
# decision, so these two "unresolved" outcomes must not appear.
UNRESOLVED_RESOLVED_BY = {"judge_unavailable", "wikidata_unavailable"}


def _terms() -> list[dict]:
    out = json.loads(OUT_FILE.read_text("utf-8"))
    return [t for terms in out.values() for t in terms]


def test_every_term_carries_a_trace():
    for t in _terms():
        trace = t.get("trace")
        assert isinstance(trace, dict) and trace, f"{t['sourceSurface']!r} has no decision trace"
        assert trace.get("resolved_by") in PIPELINE_RESOLVED_BY, (
            f"{t['sourceSurface']!r} has non-pipeline resolved_by {trace.get('resolved_by')!r}"
        )


def test_no_unresolved_escalations():
    """No term is left ``judge_unavailable``/``wikidata_unavailable`` — the
    disambiguation ran and every escalation got a real judge decision. Also
    guards against enrich-only vocab (``ambiguous_candidates``) leaking in."""
    offenders = [
        (t["sourceSurface"], t["trace"].get("resolved_by"))
        for t in _terms()
        if t["trace"].get("resolved_by") in UNRESOLVED_RESOLVED_BY
        or t["trace"].get("resolved_by") not in PIPELINE_RESOLVED_BY
    ]
    assert offenders == [], f"unresolved/foreign resolved_by present: {offenders}"


def test_yellow_terms_are_grounded():
    """A yellow term is an LLM-disambiguated hit, so it must carry a grounded
    QID — the disambiguation invariant (no yellow with ``grounded=None``)."""
    offenders = [
        t["sourceSurface"]
        for t in _terms()
        if t["difficulty"] == "yellow" and not t.get("grounded")
    ]
    assert offenders == [], f"yellow terms with no grounding: {offenders}"


def test_null_rule_holds():
    """Contract null rule: ``difficulty='red'`` ⇒ ``grounded=None`` and
    ``candidates=[]`` (grounding/pipeline enforce it; the seed must too)."""
    for t in _terms():
        if t["difficulty"] == "red":
            assert t.get("grounded") is None, f"red {t['sourceSurface']!r} carries a grounding"
            assert t.get("candidates") == [], f"red {t['sourceSurface']!r} carries candidates"


def test_core_entities_ground_correctly():
    """Lemma-fix regression guard: the demo's central entities, in the INFLECTED
    forms that were red before the nominative-lemma correction, now resolve to
    their canonical Wikidata QIDs. These are stable, high-notability items; a
    miss here means the lemma correction regressed and candidate generation is
    back to searching the raw inflected surface."""
    want = {"Месопотамии": "Q11767", "Вавилоне": "Q5684", "Евфрата": "Q34589"}
    got: dict[str, str] = {}
    for t in _terms():
        g = t.get("grounded")
        if g and t["sourceSurface"] in want and t["sourceSurface"] not in got:
            got[t["sourceSurface"]] = g["qid"]
    for surface, qid in want.items():
        assert got.get(surface) == qid, (
            f"{surface!r} grounded to {got.get(surface)!r}, expected {qid}"
        )
