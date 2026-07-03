"""P1 — link-locate pairing (default, pure-Python, runnable).

Take the grounded QID's canonical EN forms (label + aliases + enwiki sitelink)
and locate them in the translation. Exact hit → green; fuzzy 0.7–0.9 → yellow;
not found → red + recommended. pairAccuracy is null when difficulty=red.
"""
from __future__ import annotations

import time

from ..base import Judge, PairRequest, PairResult
from ..verdict import pair_from_forms
from ..wikidata import WikidataClient, canonical_en_forms


class LinkLocatePairing:
    name = "link_locate"

    def __init__(self, client: WikidataClient) -> None:
        self.wd = client

    def pair(self, req: PairRequest, *, judge: Judge | None = None) -> PairResult:
        t0 = time.perf_counter()
        calls0 = self.wd.n_calls

        # Contract null rule: no grounding → no pairAccuracy.
        if req.difficulty == "red" or not req.qid:
            return PairResult(None, None, None, latency_ms=0.0, n_api_calls=0,
                              trace={"skipped": "difficulty_red"})

        canon = list(req.canon_en)
        if not canon:  # pipeline usually pre-fills; fetch on demand otherwise
            ent = self.wd.get_entities([req.qid]).get(req.qid, {})
            canon = canonical_en_forms(ent)

        target_surface, pair_accuracy, recommended = pair_from_forms(canon, req.target)
        return PairResult(
            target_surface=target_surface,
            pair_accuracy=pair_accuracy,
            recommended=recommended,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            n_api_calls=self.wd.n_calls - calls0,
            trace={"canon_en": canon[:5]},
        )
