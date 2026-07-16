"""End-to-end assembly: (source, target, mentions) → Term[].

Runs a grounding strategy then a pairing strategy per mention and enforces the
contract null rule (difficulty=red ⇒ everything downstream is null).
"""
from __future__ import annotations

import logging

from .base import (
    FatalGroundingJudgeError,
    GroundingStrategy,
    Judge,
    PairingStrategy,
    PairRequest,
    Term,
    TermMention,
)

logger = logging.getLogger(__name__)


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
    """Ground+pair every mention, isolating per-mention grounding failures.

    A grounding strategy is expected to degrade gracefully on its own (e.g.
    label_first's red/wikidata_unavailable), but this loop is a second,
    defense-in-depth layer: any exception the strategy still lets escape for
    one mention (a non-retryable Wikidata HTTPError, an unhandled bug in a
    third-party strategy, ...) must drop only that mention, not the whole
    paragraph. ``FatalGroundingJudgeError`` is the one exception NOT isolated
    here -- it is an explicit halt marker (token-limit overflow, per-call
    gate violations) that must stop the run (see grounding/label_first.py).
    """
    terms: list[Term] = []
    for m in mentions:
        try:
            gr = grounder.ground(m, judge=judge, scope_id=scope_id, judge_cache=judge_cache)
        except FatalGroundingJudgeError:
            raise
        except Exception as exc:  # noqa: BLE001 -- isolate one bad mention, not the paragraph
            logger.warning(
                "terminology pipeline: skipping mention %r after an unhandled "
                "grounding error (%s: %s)", m.surface, type(exc).__name__, exc,
            )
            continue

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
