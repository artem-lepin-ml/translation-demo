"""Stage 2 — terminology extraction and resolution.

This stage is two LLM calls in a trench-coat:
  1. extract terms from the (ru, en_draft) pair (prompt 02),
  2. resolve each term against Wikipedia candidates + glossary (prompt 03),
then write-back confirmed RU->EN pairs to the glossary.

The implementation here is a scaffold; the Wikipedia lookup is stubbed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..glossary import Glossary, TermEntry
from ..llm.client import LLMClient
from ..paths import PROMPTS
from .base import Paragraph, StageOutput


@dataclass
class TerminologyStage:
    client: LLMClient
    glossary: Glossary
    name: str = "stage2_terminology"

    def __post_init__(self) -> None:
        self._extract_system = (PROMPTS / "02_term_extract.md").read_text(encoding="utf-8")
        self._lookup_system = (PROMPTS / "03_term_lookup.md").read_text(encoding="utf-8")

    def run(self, paragraph: Paragraph) -> StageOutput:
        extracted = self._extract(paragraph)
        resolved = self._resolve(extracted)
        for term in resolved:
            if term["strategy"] != "unresolved":
                self.glossary.upsert(
                    TermEntry(
                        ru=term["ru"],
                        en=term["en"],
                        strategy=term["strategy"],
                        source=term.get("source"),
                        notes=term.get("notes", ""),
                    )
                )
        en = self._rewrite_with_glossary(paragraph.en, resolved)
        return StageOutput(
            paragraph_id=paragraph.paragraph_id,
            model=self.client.config.model,
            stage=self.name,
            en=en,
            metadata={"terms": resolved},
        )

    def _extract(self, paragraph: Paragraph) -> list[dict]:
        user = f"[RU]\n{paragraph.ru}\n\n[EN DRAFT]\n{paragraph.en}"
        raw = self.client.complete(self._extract_system, user).content
        return json.loads(raw).get("terms", [])

    def _resolve(self, terms: list[dict]) -> list[dict]:
        # TODO: enrich each term with Wikipedia candidates + existing glossary hits.
        user = json.dumps({"terms": terms}, ensure_ascii=False)
        raw = self.client.complete(self._lookup_system, user).content
        return json.loads(raw).get("terms", [])

    @staticmethod
    def _rewrite_with_glossary(en: str, resolved: list[dict]) -> str:
        # Minimal pass: replace [ru] transliterations with the decided EN form.
        for term in resolved:
            placeholder = f"[{term['ru']}]"
            if placeholder in en and term["strategy"] != "unresolved":
                en = en.replace(placeholder, term["en"])
        return en
