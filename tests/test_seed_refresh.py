"""Guards for the rebuilt demo seed (data/seed/seed_paragraphs.jsonl).

Phase A shipped texts; Phase B filled in real judge baselines (scores +
issues, advice-free per the suggestion-guard); Phase C filled in real
terminology. See the seed-refresh plan.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest import paths

SEED_FILE = paths.DATA / "seed" / "seed_paragraphs.jsonl"
CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
CRITERIA = ("accuracy", "fluency", "style", "cultural", "terminology")


def _load_records() -> list[dict]:
    return [json.loads(line) for line in SEED_FILE.read_text("utf-8").splitlines() if line.strip()]


def test_15_paragraphs():
    records = _load_records()
    assert len(records) == 15


def test_no_cyrillic_in_translated():
    records = _load_records()
    offenders = [r["id"] for r in records if CYRILLIC_RE.search(r["translated"])]
    assert offenders == []


def test_ids_unique():
    records = _load_records()
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_each_has_baseline():
    records = _load_records()
    for r in records:
        for crit in CRITERIA:
            payload = r.get(crit)
            assert isinstance(payload, dict) and payload.get("final_score") is not None, (
                f"record id={r['id']} missing baseline for {crit}"
            )


def test_real_terms():
    records = _load_records()
    any_real = False
    for r in records:
        terms = r.get("terminology", {}).get("identified_terms")
        assert isinstance(terms, list)
        if terms and any(t.get("translation_used") for t in terms):
            any_real = True
    assert any_real, "no record carries a non-placeholder translation_used"


def test_advice_free():
    from palimpsest.webapp.judge import looks_like_advice

    records = _load_records()
    offenders = []
    for r in records:
        for crit in CRITERIA:
            payload = r.get(crit)
            if not isinstance(payload, dict):
                continue
            for issue in payload.get("identified_issues") or []:
                suggestion = issue.get("suggestion", "")
                if suggestion and looks_like_advice(suggestion):
                    offenders.append((r["id"], crit, suggestion))
    assert offenders == []
