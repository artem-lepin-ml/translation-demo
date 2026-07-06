"""Recall / precision / Wilson-CI aggregation over GT vs prediction tuples.

Tuple convention (spec Sec.3/E-D6): ``(index, surface, qid, span_len)``.
Reuses ``matching.py`` (M1/M2/M3) and ``eval_harness.wilson_ci``. Produces the
``metrics.json``-style structure via ``aggregate`` (single article) or
``aggregate_corpus`` (many articles, spec Sec.4 "M3 anywhere in the article").

P3 (label-justified precision) is tautological on the ``exact_label``
resolution path (spec Sec.4) — it is therefore never reported as an unsliced
aggregate. ``precision(..., variant="p3")`` requires a non-None
``resolved_by`` and raises otherwise; ``aggregate``/``aggregate_corpus`` only
compute P3 inside the ``resolved_by`` slice, never at the top level.

``aggregate_corpus`` additionally accepts an optional ``label_exists``
predicate (the real Wikidata-label check, wired in by ``scripts/wiki_eval.py
cmd_report --p3``). When given, it (a) replaces the stub
``lambda _s: False`` used for P3 inside the ``resolved_by`` slice, and (b)
activates a headline ``"p3_ex"`` cell in the unsliced ``precision`` dict:
P3 computed over every prediction EXCEPT those resolved via
``exact_label`` (see ``_precision_counts_p3_ex``). Excluding the
tautological exact_label path from the denominator makes this headline
non-tautological, unlike plain unsliced P3. Omitting ``label_exists``
(the default) leaves both computations exactly as before — no "p3_ex" key,
stub-based P3 in the resolved_by slice.

Cross-article scoping (bug fix): GT/pred token indices are ARTICLE-LOCAL
(reset to 0 per article — spec E-D6 indexes "the whole-article token stream",
one stream per article, not one global stream across the corpus). Matching
tuples from different articles by bare ``(index, qid)`` is a silent
cross-article collision. ``aggregate_corpus`` matches each article
independently (M3's "anywhere" stays *within* that one article) and only
sums raw matched/total counts across articles; Wilson CI is computed once at
the end from the summed counts, never per-article.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, TypedDict

from palimpsest.terminology.eval_harness import wilson_ci
from palimpsest.terminology.evaluation.matching import match_m1, match_m2, match_m3
from palimpsest.terminology.grounding.match import norm

Tuple4 = tuple[int, str, str, int]

_MATCHERS: dict[str, Callable[[list[Tuple4], list[Tuple4]], tuple[set[Tuple4], set[Tuple4]]]] = {
    "m1": match_m1,
    "m2": match_m2,
    "m3": match_m3,
}
MODES = tuple(_MATCHERS)
UNDERPOWERED_THRESHOLD = 30


def _cell(matched: int, total: int) -> dict:
    value = (matched / total) if total else None
    lo, hi = wilson_ci(matched, total)
    return {
        "matched": matched,
        "total": total,
        "value": value,
        "ci_lo": lo,
        "ci_hi": hi,
        "underpowered": total < UNDERPOWERED_THRESHOLD,
    }


def _recall_counts(gt: list[Tuple4], pred: list[Tuple4], *, mode: str) -> tuple[int, int]:
    """Raw (matched, total) for recall — no CI. One article's worth of tuples."""
    matched_gt, _matched_pred = _MATCHERS[mode](gt, pred)
    return len(matched_gt), len(gt)


def recall(gt: list[Tuple4], pred: list[Tuple4], *, mode: str) -> dict:
    """R = |GT matched| / |GT| under the given mode ('m1'|'m2'|'m3')."""
    matched, total = _recall_counts(gt, pred, mode=mode)
    return _cell(matched, total)


def _dedup_pred(pred: list[Tuple4]) -> list[Tuple4]:
    """P2 dedup key: (norm surface, qid) — collapses repeat mentions of the same entity."""
    seen: set[tuple[str, str]] = set()
    deduped: list[Tuple4] = []
    for p in pred:
        key = (norm(p[1]), p[2])
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def _precision_counts(
    gt: list[Tuple4],
    pred: list[Tuple4],
    *,
    mode: str,
    variant: str,
    label_exists: Callable[[str], bool] | None = None,
    resolved_by: str | None = "unsliced",
) -> tuple[int, int]:
    """Raw (matched, total) for one precision variant — no CI. One article's tuples.

    P3 is tautological on ``exact_label`` (spec Sec.4) and must always be
    computed within a ``resolved_by`` slice — passing ``resolved_by=None``
    (the aggregate/unsliced case) raises.
    """
    if variant == "p1":
        _matched_gt, matched_pred = _MATCHERS[mode](gt, pred)
        return len(matched_pred), len(pred)

    if variant == "p2":
        deduped = _dedup_pred(pred)
        _matched_gt, matched_pred = _MATCHERS[mode](gt, deduped)
        return len(matched_pred), len(deduped)

    if variant == "p3":
        if resolved_by is None:
            raise ValueError(
                "P3 label-justified precision is tautological on the exact_label "
                "path and must never be reported as an unsliced aggregate; pass "
                "a concrete resolved_by slice."
            )
        if label_exists is None:
            raise ValueError("P3 requires a label_exists(surface) -> bool predicate.")
        _matched_gt, matched_pred = _MATCHERS[mode](gt, pred)
        justified = {p for p in pred if p in matched_pred or label_exists(p[1])}
        return len(justified), len(pred)

    raise ValueError(f"unknown precision variant: {variant!r}")


# resolved_by tag of the deterministic path P3 is tautological on (spec Sec.4).
P3_EX_EXCLUDED_RESOLVED_BY = "exact_label"


def _precision_counts_p3_ex(
    gt: list[Tuple4],
    pred: list[Tuple4],
    *,
    mode: str,
    resolved_by_of: dict[int, str],
    label_exists: Callable[[str], bool],
) -> tuple[int, int]:
    """Headline "P3\\exact": label-justified precision computed over every
    prediction EXCEPT those resolved via ``exact_label`` — denominator is the
    count of non-exact-label predictions, not the full prediction set. Unlike
    plain unsliced P3 (tautological, see ``_precision_counts``), this is
    well-defined without a ``resolved_by`` slice because excluding the
    always-justified exact_label path from the denominator removes the
    tautology by construction.

    ``resolved_by_of`` is keyed by a prediction tuple's own index (see
    ``scripts/wiki_eval.py::_resolved_by_of_for_article``); a prediction with
    no entry (e.g. a resolution path added later that isn't tagged) is
    treated as not-exact-label and kept in the denominator.
    """
    non_exact_pred = [p for p in pred if resolved_by_of.get(p[0]) != P3_EX_EXCLUDED_RESOLVED_BY]
    _matched_gt, matched_pred = _MATCHERS[mode](gt, non_exact_pred)
    justified = {p for p in non_exact_pred if p in matched_pred or label_exists(p[1])}
    return len(justified), len(non_exact_pred)


def precision(
    gt: list[Tuple4],
    pred: list[Tuple4],
    *,
    mode: str,
    variant: str,
    label_exists: Callable[[str], bool] | None = None,
    resolved_by: str | None = "unsliced",
) -> dict:
    """P1 base, P2 unique-word dedup, or P3 label-justified. See ``_precision_counts``."""
    matched, total = _precision_counts(
        gt, pred, mode=mode, variant=variant, label_exists=label_exists, resolved_by=resolved_by,
    )
    return _cell(matched, total)


def _all_precisions(gt: list[Tuple4], pred: list[Tuple4], *, mode: str, resolved_by: str | None) -> dict:
    result = {
        "p1": precision(gt, pred, mode=mode, variant="p1"),
        "p2": precision(gt, pred, mode=mode, variant="p2"),
    }
    if resolved_by is not None:
        result["p3"] = precision(
            gt,
            pred,
            mode=mode,
            variant="p3",
            label_exists=lambda _s: False,
            resolved_by=resolved_by,
        )
    return result


def _all_recalls(gt: list[Tuple4], pred: list[Tuple4]) -> dict:
    return {mode: recall(gt, pred, mode=mode) for mode in MODES}


def _filter_by(tuples: list[Tuple4], mapping: dict[int, str], value: str) -> list[Tuple4]:
    return [t for t in tuples if mapping.get(t[0]) == value]


def aggregate(
    gt: list[Tuple4],
    pred: list[Tuple4],
    *,
    resolved_by_of: dict[int, str],
    stratum_of: dict[int, str],
    type_of: dict[int, str],
) -> dict:
    """Build the metrics.json-style structure: totals + slices (stratum/resolved_by/type).

    Slices partition ``gt``/``pred`` by the *GT* tuple's index key looked up
    in the ``*_of`` maps (resolved_by/stratum/type keyed by GT token index),
    so every slice's counts sum back to the unsliced totals. P3 is computed
    only inside the ``resolved_by`` slice (never at the top level).
    """
    result: dict = {
        "recall": _all_recalls(gt, pred),
        "precision": _all_precisions(gt, pred, mode="m2", resolved_by=None),
        "slices": {},
    }

    for axis, mapping in (("stratum", stratum_of), ("resolved_by", resolved_by_of), ("type", type_of)):
        values = sorted(set(mapping.get(t[0]) for t in gt if mapping.get(t[0]) is not None))
        axis_slices = {}
        for value in values:
            slice_gt = _filter_by(gt, mapping, value)
            slice_pred = _filter_by(pred, mapping, value)
            slice_result = {
                "recall": _all_recalls(slice_gt, slice_pred),
                "precision": _all_precisions(
                    slice_gt,
                    slice_pred,
                    mode="m2",
                    resolved_by=value if axis == "resolved_by" else None,
                ),
            }
            axis_slices[value] = slice_result
        result["slices"][axis] = axis_slices

    return result


class ArticleTuples(TypedDict):
    """One article's worth of GT/pred tuples + index->label maps, all local to
    that article's own token stream (spec E-D6: index resets per article)."""

    gt_tuples: list[Tuple4]
    pred_tuples: list[Tuple4]
    resolved_by_of: dict[int, str]
    stratum_of: dict[int, str]
    type_of: dict[int, str]


def _add_counts(acc: dict, key: tuple, matched: int, total: int) -> None:
    m, t = acc.get(key, (0, 0))
    acc[key] = (m + matched, t + total)


def aggregate_corpus(
    articles: list[ArticleTuples],
    *,
    label_exists: Callable[[str], bool] | None = None,
) -> dict:
    """Corpus-level aggregation across many articles, matching each article's
    GT against only that SAME article's predictions (bug fix: GT/pred token
    indices are article-local, so matching flattened cross-article tuples by
    bare ``(index, qid)`` silently cross-matches unrelated articles and
    corrupts recall/precision and the slice buckets via last-write-wins on
    the index-keyed ``*_of`` maps).

    M3's "document-level, anywhere in the article" (spec Sec.4) is therefore
    evaluated per article here, never across the whole corpus. Per-cell raw
    matched/total counts are summed across articles and Wilson CI is computed
    ONCE at the end from the accumulated counts — never averaged per-article.

    ``label_exists`` (module docstring): omitted (default) reproduces the old
    behaviour exactly — no ``"p3_ex"`` headline, stub-based P3 in the
    resolved_by slice. Passed (the real Wikidata-label predicate), it
    activates both.
    """
    recall_counts: dict[tuple, tuple[int, int]] = {}
    precision_counts: dict[tuple, tuple[int, int]] = {}
    slice_recall_counts: dict[tuple, tuple[int, int]] = {}
    slice_precision_counts: dict[tuple, tuple[int, int]] = {}
    slice_values: dict[str, set[str]] = {"stratum": set(), "resolved_by": set(), "type": set()}

    axes = (
        ("stratum", "stratum_of"),
        ("resolved_by", "resolved_by_of"),
        ("type", "type_of"),
    )

    for article in articles:
        gt = article["gt_tuples"]
        pred = article["pred_tuples"]

        for mode in MODES:
            matched, total = _recall_counts(gt, pred, mode=mode)
            _add_counts(recall_counts, (mode,), matched, total)

        for variant in ("p1", "p2"):
            matched, total = _precision_counts(gt, pred, mode="m2", variant=variant)
            _add_counts(precision_counts, (variant,), matched, total)

        if label_exists is not None:
            matched, total = _precision_counts_p3_ex(
                gt, pred, mode="m2",
                resolved_by_of=article["resolved_by_of"], label_exists=label_exists,
            )
            _add_counts(precision_counts, ("p3_ex",), matched, total)

        for axis, mapping_key in axes:
            mapping = article[mapping_key]
            values = set(mapping.get(t[0]) for t in gt if mapping.get(t[0]) is not None)
            slice_values[axis] |= values
            for value in values:
                slice_gt = _filter_by(gt, mapping, value)
                slice_pred = _filter_by(pred, mapping, value)

                for mode in MODES:
                    matched, total = _recall_counts(slice_gt, slice_pred, mode=mode)
                    _add_counts(slice_recall_counts, (axis, value, mode), matched, total)

                for variant in ("p1", "p2"):
                    matched, total = _precision_counts(slice_gt, slice_pred, mode="m2", variant=variant)
                    _add_counts(slice_precision_counts, (axis, value, variant), matched, total)

                if axis == "resolved_by":
                    real_or_stub = label_exists if label_exists is not None else (lambda _s: False)
                    matched, total = _precision_counts(
                        slice_gt, slice_pred, mode="m2", variant="p3",
                        label_exists=real_or_stub, resolved_by=value,
                    )
                    _add_counts(slice_precision_counts, (axis, value, "p3"), matched, total)

    result: dict = {
        "recall": {mode: _cell(*recall_counts.get((mode,), (0, 0))) for mode in MODES},
        "precision": {
            variant: _cell(*precision_counts.get((variant,), (0, 0))) for variant in ("p1", "p2")
        },
        "slices": {},
    }
    if label_exists is not None:
        result["precision"]["p3_ex"] = _cell(*precision_counts.get(("p3_ex",), (0, 0)))

    for axis, _mapping_key in axes:
        axis_slices = {}
        for value in sorted(slice_values[axis]):
            recall_result = {
                mode: _cell(*slice_recall_counts.get((axis, value, mode), (0, 0))) for mode in MODES
            }
            precision_result = {
                variant: _cell(*slice_precision_counts.get((axis, value, variant), (0, 0)))
                for variant in ("p1", "p2")
            }
            if axis == "resolved_by":
                precision_result["p3"] = _cell(
                    *slice_precision_counts.get((axis, value, "p3"), (0, 0))
                )
            axis_slices[value] = {"recall": recall_result, "precision": precision_result}
        result["slices"][axis] = axis_slices

    return result
