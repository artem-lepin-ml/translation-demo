"""judge_one: tolerant JSON parse, v2 payload → issue mapping, severity derivation."""
from __future__ import annotations

import json

from palimpsest.webapp.judge import _parse_json, derive_severity, judge_one


def test_parse_strips_code_fence():
    assert _parse_json('```json\n{"final_score": 7}\n```') == {"final_score": 7}
    assert _parse_json('noise {"final_score": 5} trailing') == {"final_score": 5}


def test_parse_strips_trailing_comma_in_object():
    assert _parse_json('{"final_score": 7, "summary": "ok",}') == {"final_score": 7, "summary": "ok"}


def test_parse_strips_trailing_comma_in_array():
    assert _parse_json('{"identified_issues": [1, 2, 3,]}') == {"identified_issues": [1, 2, 3]}


def test_parse_strips_trailing_comma_nested():
    raw = '{"final_score": 6, "identified_issues": [{"explanation": "x",},],}'
    assert _parse_json(raw) == {"final_score": 6, "identified_issues": [{"explanation": "x"}]}


def test_severity_from_keywords():
    assert derive_severity("the term is wrong here") == "major"
    assert derive_severity("a missing word") == "major"
    assert derive_severity("slightly awkward phrasing") == "minor"


class _FakeClient:
    def complete(self, system: str, user: str):
        from palimpsest.llm.client import LLMResult, Usage
        return LLMResult(content=json.dumps({
            "final_score": 6,
            "summary": "ok",
            "identified_issues": [{
                "problematic_fragment": "X", "source_fragment": "Y",
                "explanation": "missing nuance", "suggestion": "Z",
            }],
        }), usage=Usage(0, 0, 0, None))


def test_judge_one_maps_issue_fields():
    out = judge_one(_FakeClient(), "accuracy", "ru", "en")
    assert out["value"] == 6.0
    i = out["issues"][0]
    assert i["targetFragment"] == "X"
    assert i["sourceFragment"] == "Y"
    assert i["suggestion"] == "Z"
    assert i["severity"] == "major"      # 'missing' → major
    assert i["mqmCategory"] is None


class _FluencyStyleClient:
    """Payload shaped like the old fluency.md prompt (suggested_improvement key)."""

    def complete(self, system: str, user: str):
        from palimpsest.llm.client import LLMResult, Usage
        return LLMResult(content=json.dumps({
            "final_score": 6,
            "summary": "ok",
            "identified_issues": [{
                "problematic_fragment": "X", "source_fragment": "Y",
                "explanation": "awkward phrasing", "suggested_improvement": "Z",
            }],
        }), usage=Usage(0, 0, 0, None))


def test_judge_one_reads_suggested_improvement_fallback():
    """fluency-style payloads (suggested_improvement key) must not lose the suggestion."""
    out = judge_one(_FluencyStyleClient(), "fluency", "ru", "en")
    i = out["issues"][0]
    assert i["suggestion"] == "Z"


def test_judge_one_returns_usage_and_no_temperature_override():
    from palimpsest.llm.client import LLMResult, Usage
    from palimpsest.webapp import judge

    calls = {}

    class FakeClient:
        def complete(self, system, user):
            calls["args"] = (system, user)
            return LLMResult(content='{"final_score": 7, "summary": "ok", "identified_issues": []}',
                             usage=Usage(12, 8, 0, 0.0002))

    out = judge.judge_one(FakeClient(), "accuracy", "ru", "en")
    assert out["value"] == 7.0
    assert out["usage"].cost_usd == 0.0002       # usage surfaced to caller
