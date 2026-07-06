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
class GroundingConfig:
    """Ablation toggles for candidate generation and exact-label matching.

    Each toggle acts at exactly one point in the G6 label_first algorithm, so
    ablation runs can isolate and attribute its contribution (spec §3.3).

    .. deprecated:: 2026-07-06
        ``use_fallbacks`` split into ``use_cirrus`` (CirrusSearch full-text
        rung) and ``use_sitelink`` (Wikipedia RU-title -> Wikidata item rung).
        The two rungs are no longer coupled because ``use_sitelink`` shares
        its title->QID mapping with the wiki-eval reference annotations,
        which creates evaluation circularity when both are scored together
        (docs/stages/wiki-eval.md Subtleties) -- eval runs need to disable
        ``use_sitelink`` while keeping ``use_cirrus`` on. The constructor
        still accepts ``use_fallbacks=<bool>`` as a compat alias that sets
        both new fields to the same value, so existing call sites and
        ablation bit-configs keep working unchanged; reading back
        ``.use_fallbacks`` returns ``True`` only when both are ``True``. New
        code should set ``use_cirrus``/``use_sitelink`` directly.
    """

    use_lemma: bool = True
    use_cirrus: bool = True
    use_sitelink: bool = True
    match_aliases: bool = True
    search_limit: int = 7
    enrich_top: int = 5

    def __init__(
        self,
        use_lemma: bool = True,
        use_cirrus: bool = True,
        use_sitelink: bool = True,
        match_aliases: bool = True,
        search_limit: int = 7,
        enrich_top: int = 5,
        use_fallbacks: bool | None = None,
    ) -> None:
        # dataclass(frozen=True) only auto-generates __init__ when the class
        # doesn't already define one, so this hand-written constructor is the
        # cleanest way to keep a deprecated compat kwarg without duplicating
        # the field list in a classmethod/factory -- __repr__/__eq__ still
        # come from the annotated fields below, unaffected.
        if use_fallbacks is not None:
            use_cirrus = use_fallbacks
            use_sitelink = use_fallbacks
        object.__setattr__(self, "use_lemma", use_lemma)
        object.__setattr__(self, "use_cirrus", use_cirrus)
        object.__setattr__(self, "use_sitelink", use_sitelink)
        object.__setattr__(self, "match_aliases", match_aliases)
        object.__setattr__(self, "search_limit", search_limit)
        object.__setattr__(self, "enrich_top", enrich_top)

    @property
    def use_fallbacks(self) -> bool:
        """Deprecated compat read: True only if both use_cirrus and use_sitelink are True."""
        return self.use_cirrus and self.use_sitelink


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
    trace: dict = field(default_factory=dict)

    def db_tuple(self, paragraph_id: int) -> tuple:
        """Row tuple for INSERT into the ``term`` table (grounded/candidates as JSON).

        ``trace_json`` is appended LAST to match the column order in the
        ``term`` DDL (db.py) -- it was added after the original columns.
        """
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
            json.dumps(self.trace),
        )


class GroundingStrategy(Protocol):
    name: str

    def ground(
        self,
        mention: TermMention,
        *,
        judge: Judge | None = None,
        scope_id: object | None = None,
        judge_cache: dict | None = None,
    ) -> GroundingResult: ...


class PairingStrategy(Protocol):
    name: str

    def pair(self, req: PairRequest, *, judge: Judge | None = None) -> PairResult: ...
