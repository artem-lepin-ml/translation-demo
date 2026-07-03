"""Stage 4 — atomic-fact extraction and verification.

Port target: factowl/atomic_facts.py (see factowl/factscorer.py#L45-L206 for usage).
For now this stage calls prompt 04 directly; replace the body when we port factowl.
"""
from __future__ import annotations

import json

from ..llm.client import LLMClient
from ..paths import PROMPTS
from .base import Paragraph, StageOutput


class FactcheckStage:
    name = "stage4_factcheck"

    def __init__(self, client: LLMClient):
        self.client = client
        self._system = (PROMPTS / "04_factcheck.md").read_text(encoding="utf-8")

    def run(self, paragraph: Paragraph) -> StageOutput:
        user = f"[RU SOURCE]\n{paragraph.ru}\n\n[EN]\n{paragraph.en}"
        raw = self.client.complete(self._system, user).content
        facts = [json.loads(line) for line in raw.splitlines() if line.strip()]
        return StageOutput(
            paragraph_id=paragraph.paragraph_id,
            model=self.client.config.model,
            stage=self.name,
            en=paragraph.en,  # factcheck does not rewrite; it annotates
            metadata={"facts": facts},
        )
