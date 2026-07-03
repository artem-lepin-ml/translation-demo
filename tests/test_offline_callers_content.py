"""Guard: dormant pipeline/evaluation stages must handle LLMResult, not a bare str.

These 5 modules are not wired into the live demo (webapp) — they call
``LLMClient.complete()`` directly and, before Task 6, expected it to return a
``str``. Task 6 changed ``complete()`` to return ``LLMResult(content, usage)``.
This test is a proportionate guard, not a refactor: one fake-client call per
stage, asserting no ``AttributeError`` and the right return shape.
"""
from __future__ import annotations

import json

from palimpsest.evaluation.judge import LLMJudge
from palimpsest.glossary import Glossary
from palimpsest.llm.client import LLMResult, Usage
from palimpsest.pipeline.base import Paragraph
from palimpsest.pipeline.draft import DraftStage
from palimpsest.pipeline.factcheck import FactcheckStage
from palimpsest.pipeline.polish import PolishStage
from palimpsest.pipeline.terminology import TerminologyStage


def _fake_client(content: str):
    class FakeClient:
        config = type("Cfg", (), {"model": "fake/model"})()

        def complete(self, system: str, user: str) -> LLMResult:
            return LLMResult(content=content, usage=Usage(1, 1, 0, None))

    return FakeClient()


PARAGRAPH = Paragraph(paragraph_id="p1", ru="Саргон правил.", en="Sargon ruled.",
                      context_en="")


def test_draft_stage_returns_stripped_str():
    stage = DraftStage(_fake_client("  Sargon ruled the land.  "))
    out = stage.run(PARAGRAPH)
    assert out.en == "Sargon ruled the land."


def test_polish_stage_returns_stripped_str():
    stage = PolishStage(_fake_client("  Sargon ruled the land.  "))
    out = stage.run(PARAGRAPH)
    assert out.en == "Sargon ruled the land."


def test_factcheck_stage_parses_jsonl_facts():
    facts_jsonl = json.dumps({"fact": "Sargon ruled"}) + "\n" + json.dumps({"fact": "in Akkad"})
    stage = FactcheckStage(_fake_client(facts_jsonl))
    out = stage.run(PARAGRAPH)
    assert out.metadata["facts"] == [{"fact": "Sargon ruled"}, {"fact": "in Akkad"}]


def test_terminology_stage_extracts_and_resolves_terms(tmp_path):
    glossary = Glossary(tmp_path / "glossary.json")
    extract_json = json.dumps({"terms": [{"ru": "Саргон", "en": "Sargon", "strategy": "transcription"}]})
    stage = TerminologyStage(client=_fake_client(extract_json), glossary=glossary)
    out = stage.run(PARAGRAPH)
    assert out.metadata["terms"] == [{"ru": "Саргон", "en": "Sargon", "strategy": "transcription"}]


def test_evaluation_judge_parses_scores():
    scores_json = json.dumps({
        "accuracy": 5, "terminology": 4, "consistency": 4,
        "fluency": 5, "style": 4, "culture": 3, "rationale": "solid",
    })
    judge = LLMJudge(_fake_client(scores_json))
    out = judge.judge("p1", "target-model", PARAGRAPH.ru, PARAGRAPH.en)
    assert out.scores["accuracy"] == 5.0
    assert out.rationale == "solid"
