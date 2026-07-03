"""GT-vs-prediction tuple matching: M1 strict, M2 span-overlap, M3 document.

Pure functions, no I/O. Tuple convention (spec Sec.3/E-D6, shared with
tokenize.py and predict.py): a GT or predicted mention is a plain tuple
``(index, surface, qid, span_len)`` — token index of the first token, the
mention surface, the Wikidata QID, and the token-span length. Deliberately a
plain tuple, not a dataclass, per the shared convention across sibling agents.

Each ``match_m*`` returns ``(matched_gt, matched_pred)`` so callers can
compute recall from ``matched_gt`` and precision from ``matched_pred``.
"""
from __future__ import annotations

from palimpsest.terminology.grounding.match import norm

Tuple4 = tuple[int, str, str, int]


def _span(t: Tuple4) -> range:
    index, _surface, _qid, span_len = t
    return range(index, index + max(span_len, 1))


def match_m1(gt: list[Tuple4], pred: list[Tuple4]) -> tuple[set[Tuple4], set[Tuple4]]:
    """Strict match: index equal AND norm(surface) equal AND qid equal."""
    matched_gt: set[Tuple4] = set()
    matched_pred: set[Tuple4] = set()
    for g in gt:
        g_index, g_surface, g_qid, _ = g
        for p in pred:
            p_index, p_surface, p_qid, _ = p
            if g_index == p_index and g_qid == p_qid and norm(g_surface) == norm(p_surface):
                matched_gt.add(g)
                matched_pred.add(p)
    return matched_gt, matched_pred


def match_m2(gt: list[Tuple4], pred: list[Tuple4]) -> tuple[set[Tuple4], set[Tuple4]]:
    """Span-overlap match: token spans overlap AND qid equal. No surface comparison."""
    matched_gt: set[Tuple4] = set()
    matched_pred: set[Tuple4] = set()
    for g in gt:
        g_span = _span(g)
        g_qid = g[2]
        for p in pred:
            if g_qid != p[2]:
                continue
            p_span = _span(p)
            if g_span.start < p_span.stop and p_span.start < g_span.stop:
                matched_gt.add(g)
                matched_pred.add(p)
    return matched_gt, matched_pred


def match_m3(gt: list[Tuple4], pred: list[Tuple4]) -> tuple[set[Tuple4], set[Tuple4]]:
    """Document-level match: qid present anywhere in both gt and pred.

    Credits every GT tuple and every pred tuple sharing a qid that occurs on
    both sides, regardless of position — "concept found and grounded
    correctly, even in a different mention" (spec Sec.4).
    """
    gt_qids = {g[2] for g in gt}
    pred_qids = {p[2] for p in pred}
    shared_qids = gt_qids & pred_qids
    matched_gt = {g for g in gt if g[2] in shared_qids}
    matched_pred = {p for p in pred if p[2] in shared_qids}
    return matched_gt, matched_pred
