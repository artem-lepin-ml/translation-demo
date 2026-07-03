"""End-to-end assembly: (source, target, mentions) → Term[].

Runs a grounding strategy then a pairing strategy per mention and enforces the
contract null rule (difficulty=red ⇒ everything downstream is null).
"""
from __future__ import annotations

from .base import GroundingStrategy, Judge, PairingStrategy, PairRequest, Term, TermMention


def run(
    source: str,
    target: str,
    mentions: list[TermMention],
    *,
    grounder: GroundingStrategy,
    pairer: PairingStrategy,
    judge: Judge | None = None,
    scope_id: object | None = None,
    judge_cache: dict | None = None,
) -> list[Term]:
    terms: list[Term] = []
    for m in mentions:
        gr = grounder.ground(m, judge=judge, scope_id=scope_id, judge_cache=judge_cache)

        if gr.difficulty == "red":
            terms.append(Term(
                source_surface=m.surface, source_lemma=m.lemma or m.surface,
                context=m.context, char_start=m.char_start, char_end=m.char_end,
                difficulty="red", grounded=None, candidates=[],
                target_surface=None, pair_accuracy=None, recommended=None,
                note=m.category or "", trace=gr.trace,
            ))
            continue

        canon = gr.trace.get("canon_en", [])
        pr = pairer.pair(PairRequest(
            surface=m.surface, context=m.context, target=target,
            qid=gr.grounded.qid if gr.grounded else None,
            canon_en=canon, difficulty=gr.difficulty,
        ))
        terms.append(Term(
            source_surface=m.surface, source_lemma=m.lemma or m.surface,
            context=m.context, char_start=m.char_start, char_end=m.char_end,
            difficulty=gr.difficulty, grounded=gr.grounded, candidates=gr.candidates,
            target_surface=pr.target_surface, pair_accuracy=pr.pair_accuracy,
            recommended=pr.recommended, note=m.category or "", trace=gr.trace,
        ))
    return terms
