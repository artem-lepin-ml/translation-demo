"""LLM-as-judge: score one (paragraph, translation) pair against the RU source."""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..llm.client import LLMClient
from ..paths import PROMPTS
from .criteria import CRITERIA, consensus


@dataclass(slots=True)
class JudgeOutput:
    paragraph_id: str
    judge_model: str
    target_model: str
    scores: dict[str, float]
    consensus_score: float
    rationale: str

    def to_dict(self) -> dict:
        return {
            "paragraph_id": self.paragraph_id,
            "judge_model": self.judge_model,
            "target_model": self.target_model,
            "scores": self.scores,
            "consensus": self.consensus_score,
            "rationale": self.rationale,
        }


class LLMJudge:
    def __init__(self, client: LLMClient):
        self.client = client
        self._system = (PROMPTS / "judge.md").read_text(encoding="utf-8")

    def judge(self, paragraph_id: str, target_model: str, ru: str, en: str) -> JudgeOutput:
        user = f"[SOURCE RU]\n{ru}\n\n[TRANSLATION EN by {target_model}]\n{en}"
        raw = self.client.complete(self._system, user).content
        data = json.loads(raw)
        scores = {c.key: float(data[c.key]) for c in CRITERIA}
        return JudgeOutput(
            paragraph_id=paragraph_id,
            judge_model=self.client.config.model,
            target_model=target_model,
            scores=scores,
            consensus_score=consensus(scores),
            rationale=data.get("rationale", ""),
        )
