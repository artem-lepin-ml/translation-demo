"""P3 — LLM-assisted pairing.

Locates the term in the translation and judges the adaptation via an injected
``judge`` (subagent-backed). Falls back to P1's deterministic locate when no
judge is supplied, so it is importable and testable without a model.
"""
from __future__ import annotations

import time

from ..base import Judge, PairRequest, PairResult
from ..verdict import pair_from_forms


class LlmJudgePairing:
    name = "llm_judge"

    def pair(self, req: PairRequest, *, judge: Judge | None = None) -> PairResult:
        t0 = time.perf_counter()
        if req.difficulty == "red" or not req.qid:
            return PairResult(None, None, None, trace={"skipped": "difficulty_red"})

        if judge is None:  # deterministic fallback == P1
            ts, pa, rec = pair_from_forms(req.canon_en, req.target)
            return PairResult(ts, pa, rec, latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                              trace={"fallback": "pair_from_forms"})

        prompt = (
            f"Russian term: '{req.surface}'. Its canonical English equivalents (from Wikidata): "
            f"{', '.join(req.canon_en) or '(none)'}.\n"
            f"English translation of the paragraph:\n{req.target}\n\n"
            "Did the translation render this term with an acceptable English equivalent? "
            "Return JSON {target_surface, verdict, recommended} where target_surface is the exact "
            "phrase the translation used (or null if the term is absent), verdict is 'green' "
            "(correct/standard), 'yellow' (understandable but non-standard/transliterated) or 'red' "
            "(wrong or omitted), and recommended is the canonical English form when verdict is "
            "yellow/red else null."
        )
        out = judge(prompt) or {}
        verdict = out.get("verdict") if out.get("verdict") in ("green", "yellow", "red") else "yellow"
        return PairResult(
            target_surface=out.get("target_surface"),
            pair_accuracy=verdict,
            recommended=out.get("recommended") if verdict != "green" else None,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            trace={"source": "llm_judge"},
        )
