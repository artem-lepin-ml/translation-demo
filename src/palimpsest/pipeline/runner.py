"""Pipeline orchestrator: iterate paragraphs, apply stages in order, carry context."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tqdm import tqdm

from .base import Paragraph, Stage, StageOutput


@dataclass
class PipelineRunner:
    stages: list[Stage]
    context_window: int = 1

    def run(self, paragraphs: Iterable[Paragraph]) -> list[dict[str, StageOutput]]:
        """Returns a list aligned with `paragraphs`, each element mapping stage name -> output."""
        paragraphs = list(paragraphs)
        all_outputs: list[dict[str, StageOutput]] = []
        history_en: list[str] = []

        for p in tqdm(paragraphs, desc="paragraphs"):
            p.context_en = "\n\n".join(history_en[-self.context_window :])
            per_stage: dict[str, StageOutput] = {}
            for stage in self.stages:
                out = stage.run(p)
                per_stage[stage.name] = out
                p.en = out.en
            all_outputs.append(per_stage)
            history_en.append(p.en)

        return all_outputs
