"""G3 — LLM-assisted grounding.

Same shared candidate generation as G1 ([candidates.py](candidates.py)), but the
final QID choice and difficulty are delegated to an injected ``judge`` (backed by
a subagent, never a direct API client). Falls back to the deterministic notability
verdict when no judge is supplied, so the class is importable and testable without
a model.
"""
from __future__ import annotations

import time

from ..base import GroundingResult, Judge, TermMention, WikidataRef
from ..verdict import difficulty_from_candidates
from ..wikidata import WikidataClient
from .candidates import generate_candidates


class LlmJudgeGrounding:
    name = "llm_judge"

    def __init__(self, client: WikidataClient, search_limit: int = 7, enrich_top: int = 5) -> None:
        self.wd = client
        self.search_limit = search_limit
        self.enrich_top = enrich_top

    def ground(self, mention: TermMention, *, judge: Judge | None = None) -> GroundingResult:
        t0 = time.perf_counter()
        calls0 = self.wd.n_calls
        gen = generate_candidates(self.wd, mention, search_limit=self.search_limit, enrich_top=self.enrich_top)
        cands = gen["candidates"]
        if not cands:
            reason = "type_filtered_out" if gen["n_hits"] else "no_hits"
            return GroundingResult("red", None, [], round((time.perf_counter() - t0) * 1000, 1),
                                   self.wd.n_calls - calls0, {"source": gen["source"], "reason": reason})

        if judge is not None:
            verdict = self._judge_pick(mention, cands, judge)
        else:  # importable/testable without a model
            names = [n for n in (mention.surface, mention.lemma) if n]
            diff, grounded, _ = difficulty_from_candidates(names, cands)
            verdict = {"difficulty": diff, "qid": grounded.qid if grounded else None}

        refs = [WikidataRef.from_qid(c["qid"], c["label"], c["description"]) for c in cands]
        chosen = next((r for r in refs if r.qid == verdict.get("qid")), refs[0] if refs else None)
        difficulty = verdict["difficulty"]
        # keep the trace null-clean on red: no canon leaks from an unchosen candidate
        canon = gen["canon_by_qid"].get(chosen.qid, []) if (chosen and difficulty != "red") else []
        return GroundingResult(
            difficulty=difficulty,
            grounded=None if difficulty == "red" else chosen,
            candidates=[] if difficulty == "red" else refs,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            n_api_calls=self.wd.n_calls - calls0,
            trace={"source": "llm_judge", "canon_en": canon, "n_candidates": len(cands)},
        )

    @staticmethod
    def _judge_pick(mention: TermMention, cands: list[dict], judge: Judge) -> dict:
        options = "\n".join(
            f"- {c['qid']}: {c['label']} — {c['description']}" for c in cands
        )
        prompt = (
            f"Russian term: '{mention.surface}' (lemma '{mention.lemma or mention.surface}').\n"
            f"Sentence context: {mention.context}\n\n"
            f"Candidate Wikidata entities:\n{options}\n\n"
            "Pick the single correct QID for this term in this context, or judge it ambiguous/absent.\n"
            "Return JSON {qid, difficulty} where difficulty is 'green' (one clear match), "
            "'yellow' (genuinely ambiguous between candidates), or 'red' (none fit)."
        )
        out = judge(prompt) or {}
        difficulty = out.get("difficulty") if out.get("difficulty") in ("green", "yellow", "red") else "yellow"
        return {"qid": out.get("qid"), "difficulty": difficulty}
