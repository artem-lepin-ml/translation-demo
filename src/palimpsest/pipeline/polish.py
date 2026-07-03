"""Stage 5 — polish (fluency, style, consistency, cultural adaptation)."""
from __future__ import annotations

from ..llm.client import LLMClient
from ..paths import PROMPTS
from .base import Paragraph, StageOutput


class PolishStage:
    name = "stage5_polish"

    def __init__(self, client: LLMClient):
        self.client = client
        self._system = (PROMPTS / "05_polish.md").read_text(encoding="utf-8")

    def run(self, paragraph: Paragraph) -> StageOutput:
        user = (
            f"[CONTEXT]\n{paragraph.context_en}\n\n"
            f"[CURRENT EN]\n{paragraph.en}"
        )
        en = self.client.complete(self._system, user).content.strip()
        return StageOutput(
            paragraph_id=paragraph.paragraph_id,
            model=self.client.config.model,
            stage=self.name,
            en=en,
        )
