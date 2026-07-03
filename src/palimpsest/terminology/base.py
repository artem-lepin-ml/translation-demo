"""Frozen shared types and strategy protocols for the terminology module.

Written before any strategy so grounding/pairing implementations are swappable
and comparable 1:1. No LLM or DB dependency lives here — strategies that need a
model receive an injected ``judge`` callable the orchestrator backs with a
subagent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

Verdict = Literal["green", "yellow", "red"]

# A judge turns a prompt into structured output. In this project it is backed by
# a subagent (Haiku/Sonnet), never a direct API client, so ``src/`` stays pure.
Judge = Callable[[str], dict]

# An extractor turns source text into raw NER surfaces. Same subagent-injection
# pattern as Judge, but a different return arity (list[dict], not dict).
Extractor = Callable[[str], list[dict]]   # source text -> [{surface, category}]


@dataclass(frozen=True)
class WikidataRef:
    """A resolved (or candidate) Wikidata entity."""

    qid: str
    url: str
    label: str
    description: str = ""

    @classmethod
    def from_qid(cls, qid: str, label: str, description: str = "") -> "WikidataRef":
        return cls(
            qid=qid,
            url=f"https://www.wikidata.org/wiki/{qid}",
            label=label,
            description=description,
        )

    def as_dict(self) -> dict:
        return {"qid": self.qid, "url": self.url, "label": self.label, "description": self.description}


@dataclass
class TermMention:
    """One occurrence of a source-language term to analyse."""

    surface: str
    context: str = ""
    lemma: str | None = None
    char_start: int = -1
    char_end: int = -1
    lang: str = "ru"
    category: str | None = None


@dataclass
class GroundingResult:
    """Output of grounding: the difficulty signal + Wikidata references."""

    difficulty: Verdict
    grounded: WikidataRef | None
    candidates: list[WikidataRef]
    latency_ms: float = 0.0
    n_api_calls: int = 0
    trace: dict = field(default_factory=dict)


@dataclass
class PairRequest:
    """Input to pairing: a grounded mention plus the EN translation to search."""

    surface: str
    context: str
    target: str  # full EN translation of the paragraph
    qid: str | None
    canon_en: list[str]  # canonical EN forms (label + aliases + sitelink title)
    difficulty: Verdict


@dataclass
class PairResult:
    """Output of pairing: the pairAccuracy signal + what the translation used."""

    target_surface: str | None
    pair_accuracy: Verdict | None
    recommended: str | None
    latency_ms: float = 0.0
    n_api_calls: int = 0
    trace: dict = field(default_factory=dict)


@dataclass
class Term:
    """Assembled term, one row per occurrence. Columns mirror the ``term`` DDL.

    Contract null rule: ``difficulty == 'red'`` forces ``grounded=None``,
    ``candidates=[]``, ``pair_accuracy=None`` and ``recommended=None``.
    """

    source_surface: str
    source_lemma: str | None
    context: str
    char_start: int
    char_end: int
    difficulty: Verdict
    grounded: WikidataRef | None
    candidates: list[WikidataRef]
    target_surface: str | None
    pair_accuracy: Verdict | None
    recommended: str | None
    note: str = ""

    def db_tuple(self, paragraph_id: int) -> tuple:
        """Row tuple for INSERT into the ``term`` table (grounded/candidates as JSON)."""
        import json

        return (
            paragraph_id,
            self.source_surface,
            self.source_lemma,
            self.context,
            self.char_start,
            self.char_end,
            self.difficulty,
            json.dumps(self.grounded.as_dict()) if self.grounded else None,
            json.dumps([c.as_dict() for c in self.candidates]),
            self.target_surface,
            self.pair_accuracy,
            self.recommended,
            self.note,
        )


class GroundingStrategy(Protocol):
    name: str

    def ground(self, mention: TermMention, *, judge: Judge | None = None) -> GroundingResult: ...


class PairingStrategy(Protocol):
    name: str

    def pair(self, req: PairRequest, *, judge: Judge | None = None) -> PairResult: ...
