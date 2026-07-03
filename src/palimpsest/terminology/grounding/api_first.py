"""G1 — API-first grounding (default, pure-Python, runnable).

Shared candidate generation ([candidates.py](candidates.py): prefix search →
CirrusSearch → Wikipedia langlink → enrich → type filter) then the deterministic
notability verdict. No judge needed; this is the zero-cost default.
"""
from __future__ import annotations

import time

from ..base import GroundingResult, Judge, TermMention
from ..verdict import difficulty_from_candidates
from ..wikidata import WikidataClient
from .candidates import generate_candidates


class ApiFirstGrounding:
    name = "api_first"

    def __init__(self, client: WikidataClient, enrich_top: int = 4, search_limit: int = 7) -> None:
        self.wd = client
        self.enrich_top = enrich_top
        self.search_limit = search_limit

    def ground(self, mention: TermMention, *, judge: Judge | None = None) -> GroundingResult:
        t0 = time.perf_counter()
        calls0 = self.wd.n_calls
        gen = generate_candidates(self.wd, mention, search_limit=self.search_limit, enrich_top=self.enrich_top)
        candidates = gen["candidates"]
        if not candidates:
            return self._result("red", None, [], t0, calls0,
                                {"source": gen["source"], "reason": "no_candidates"}, [])

        names = [n for n in (mention.surface, mention.lemma) if n]
        difficulty, grounded, refs = difficulty_from_candidates(names, candidates)
        canon = gen["canon_by_qid"].get(grounded.qid, []) if grounded else []
        trace = {"source": gen["source"], "n_hits": gen["n_hits"], "n_after_filter": len(candidates)}
        return self._result(difficulty, grounded, refs, t0, calls0, trace, canon)

    def _result(self, difficulty, grounded, refs, t0, calls0, trace, canon_en) -> GroundingResult:
        trace = {**trace, "canon_en": canon_en}
        return GroundingResult(
            difficulty=difficulty,
            grounded=grounded,
            candidates=refs,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            n_api_calls=self.wd.n_calls - calls0,
            trace=trace,
        )
