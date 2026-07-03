"""G5 — hybrid grounding (best-of-both).

Composition, not a new algorithm: take the robust *difficulty* + candidate list
from the deterministic api_first, and swap in the judge-picked *QID* from
llm_judge only when the judge resolved one. Red short-circuits before any judge
call (cost + correctness). Without a judge it degrades to plain api_first, so it
stays importable/testable.

Rationale (term-grounding audit, ported): api_first gives a calibrated difficulty
floor and never wastes a judge call on ungroundable terms; the judge only fixes
*which* entity among the candidates — the +accuracy, 0-regression pattern.
"""
from __future__ import annotations

import time

from ..base import GroundingResult, Judge, TermMention
from ..wikidata import WikidataClient
from .api_first import ApiFirstGrounding
from .llm_judge import LlmJudgeGrounding


class HybridGrounding:
    name = "hybrid"

    def __init__(self, client: WikidataClient, search_limit: int = 7, enrich_top: int = 5) -> None:
        self.api = ApiFirstGrounding(client, enrich_top=enrich_top, search_limit=search_limit)
        self.llm = LlmJudgeGrounding(client, search_limit=search_limit, enrich_top=enrich_top)

    def ground(self, mention: TermMention, *, judge: Judge | None = None) -> GroundingResult:
        a = self.api.ground(mention)
        if a.difficulty == "red" or judge is None:
            # red short-circuit (no wasted judge call) / degrade to api_first without a judge
            a.trace = {**a.trace, "hybrid": True, "difficulty_from": "api_first",
                       "grounded_from": None if a.difficulty == "red" else "api_first"}
            return a

        t1 = time.perf_counter()
        lj = self.llm.ground(mention, judge=judge)
        # keep api_first's robust difficulty + candidate list; take the judge's QID
        # (and its canon_en) only when it actually resolved an entity.
        use_llm = lj.grounded is not None
        grounded = lj.grounded if use_llm else a.grounded
        canon = lj.trace.get("canon_en", []) if use_llm else a.trace.get("canon_en", [])
        return GroundingResult(
            difficulty=a.difficulty,
            grounded=grounded,
            candidates=a.candidates,
            latency_ms=round(a.latency_ms + (time.perf_counter() - t1) * 1000, 1),
            n_api_calls=a.n_api_calls + lj.n_api_calls,
            trace={**a.trace, "hybrid": True, "difficulty_from": "api_first",
                   "grounded_from": "llm_judge" if use_llm else "api_first", "canon_en": canon},
        )
