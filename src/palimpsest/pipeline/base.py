"""Core dataclasses and the Stage protocol used by every pipeline step."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class Paragraph:
    """The unit of translation. `ru` never changes; `en` is overwritten as stages run."""

    paragraph_id: str            # e.g. "vol01/ch01/p0042"
    ru: str                      # Russian source — immutable after loading
    en: str = ""                 # current English rendering, updated per stage
    context_en: str = ""         # English context from neighbour paragraphs


@dataclass(slots=True)
class StageOutput:
    paragraph_id: str
    model: str
    stage: str
    en: str
    metadata: dict = field(default_factory=dict)


class Stage(Protocol):
    name: str

    def run(self, paragraph: Paragraph) -> StageOutput: ...
