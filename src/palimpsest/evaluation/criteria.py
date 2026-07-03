"""The six criteria and the weighted-consensus formula.

Weights match the Palimpsest presentation (see palimpsets_summary.md §6).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Criterion:
    key: str
    name_en: str
    weight: float
    description: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion("accuracy",    "Accuracy",    2.0, "Semantic fidelity: facts, numbers, names."),
    Criterion("terminology", "Terminology", 1.5, "Correct domain / academic term choice."),
    Criterion("consistency", "Consistency", 1.5, "Same term rendered the same; steady register."),
    Criterion("fluency",     "Fluency",     1.0, "Natural, grammatical English."),
    Criterion("style",       "Style",       1.0, "Encyclopedic voice; author's tone preserved."),
    Criterion("culture",     "Cultural",    1.0, "Realia adapted for an EN reader."),
)

CRITERIA_BY_KEY: dict[str, Criterion] = {c.key: c for c in CRITERIA}


def consensus(scores: dict[str, float]) -> float:
    """Weighted average; missing criteria are skipped (not zero-imputed)."""
    num = sum(scores[c.key] * c.weight for c in CRITERIA if c.key in scores)
    den = sum(c.weight for c in CRITERIA if c.key in scores)
    return num / den if den else 0.0
