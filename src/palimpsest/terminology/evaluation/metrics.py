"""Protocol-v3 set-based document-level aggregation over GT vs prediction tuples.

Tuple convention (spec Sec.3/E-D6): ``(index, surface, qid, span_len)``.

v3 is the only protocol supported here (wiki-eval experiment v2, spec
2026-07-10-wiki-eval-experiment-v2.md Р9/§4.5): mention-level M1/M2/M3
matching and the P1/P2/P3 precision variants were retired along with
``matching.py`` (§7 of that spec) — GT/pred are reduced to unique
``(article, QID)`` sets and scored as a document-level micro confusion,
split named vs. term. Methodology prose SSOT:
``docs/paper/sections/eval-metrics-terminology.tex`` — this module only
implements the formalism, it does not restate it.

``aggregate_corpus`` is the sole aggregator; ``ArticleUnits`` is its
per-article input shape. ``_cell``/``UNDERPOWERED_THRESHOLD``/``wilson_ci``
are the shared per-cell CI primitives reused from the retired mention-level
protocol (still correct, protocol-agnostic).
"""
from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from palimpsest.terminology.eval_harness import wilson_ci

Tuple4 = tuple[int, str, str, int]

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


class ArticleUnits(TypedDict):
    """One article's worth of GT/pred tuples for the v3 set-based aggregator
    (``aggregate_corpus``) — no per-tuple slice maps, since v3 has no
    stratum/resolved_by slicing (spec Sec.4.5, Р9)."""

    gt_tuples: list[Tuple4]
    pred_tuples: list[Tuple4]


def _classify(surfaces: list[str]) -> tuple[str, bool]:
    """named/term class + ambiguous flag from a unit's pooled anchor surfaces
    (spec Sec.4, existing harness convention): named if ANY surface starts
    uppercase; ambiguous if surfaces disagree on case (still classified named)."""
    caps = [s[:1].isupper() for s in surfaces if s]
    named = any(caps)
    ambiguous = named and not all(caps)
    return ("named" if named else "term"), ambiguous


def aggregate_corpus(
    articles: list[ArticleUnits],
    *,
    tier_assignment: dict[str, int],
) -> dict:
    """Protocol v3: set-based document-level R_doc/P_doc, split named/term
    (spec Sec.4.5, Р9; methodology prose SSOT:
    docs/paper/sections/eval-metrics-terminology.tex — this docstring only
    restates the formalism for maintainers, does not own it).

    Per the supervisor's ICD-coding formalism: both GT and prediction lists
    are deduplicated to unique (article, QID) sets S_t/S_p per article, then
    pooled into a corpus-level micro confusion count — TP = S_p ∩ S_t,
    FP = S_p \\ S_t, FN = S_t \\ S_p — accumulated over all articles (never
    averaged per-article). Because Wikipedia's hyperlink annotation is sparse
    (not every mentionable entity is linked), a predicted unit absent from
    gold is not necessarily wrong, so P_doc is a conservative lower bound,
    not a true precision.

    Per-article steps:
      1. Gold units: group GT tuples by QID, but SKIP any GT tuple whose QID
         falls in a generic lexical class per ``tier_assignment`` (tier != 0
         — languages/scripts, taxa, materials, units; spec Sec.4.5) *before*
         grouping. Skipped mentions are counted in
         ``n_gold_mentions_dropped_by_tier``, not per-unit (a partly-tiered
         gold unit keeps its remaining, non-tiered mentions).
      2. Pred units: group ALL pred tuples by QID, with NO tier filter. This
         is a deliberate protocol asymmetry, not an oversight: the tier
         filter exists to stop rewarding the model for generic-class gold
         links, not to excuse a generic-class prediction outside the
         filtered gold set — such a prediction still counts as FP, which
         keeps P_doc a conservative lower bound rather than inflating it by
         quietly forgiving predictions on the same grounds gold was pruned.
      3. Classify each gold unit named/term by ``_classify`` over its pooled
         anchor surfaces (any capitalized -> named); a unit with mixed-case
         surfaces is counted in ``n_ambiguous_gold_units`` but still
         classified named.
      4. TP/FN come from the gold side: a gold QID present in the pred unit
         map is TP (for the gold unit's class); absent is FN. FP comes from
         the pred side: a pred QID absent from the gold unit map is FP,
         classified by its OWN predicted surfaces (not the — nonexistent —
         gold class).

    tp/fn/fp/gold_units are pooled per class across all articles; R_doc/P_doc
    are each a single ``_cell`` (Wilson CI) computed once from the pooled
    counts, exactly like the retired mention-level aggregator's top-level
    cells.
    """
    stats: dict[str, dict[str, int]] = {
        cls: {"tp": 0, "fn": 0, "fp": 0, "gold_units": 0} for cls in ("named", "term")
    }
    n_ambiguous_gold_units = 0
    n_gold_mentions_dropped_by_tier = 0

    for article in articles:
        gold_surfaces: dict[str, list[str]] = defaultdict(list)
        for t in article["gt_tuples"]:
            if tier_assignment.get(t[2], 0) != 0:
                n_gold_mentions_dropped_by_tier += 1
                continue
            gold_surfaces[t[2]].append(t[1])

        pred_surfaces: dict[str, list[str]] = defaultdict(list)
        for t in article["pred_tuples"]:
            pred_surfaces[t[2]].append(t[1])

        gold_class: dict[str, str] = {}
        for qid, surfaces in gold_surfaces.items():
            cls, ambiguous = _classify(surfaces)
            gold_class[qid] = cls
            n_ambiguous_gold_units += ambiguous

        for qid, cls in gold_class.items():
            stats[cls]["gold_units"] += 1
            if qid in pred_surfaces:
                stats[cls]["tp"] += 1
            else:
                stats[cls]["fn"] += 1

        for qid, surfaces in pred_surfaces.items():
            if qid in gold_class:
                continue
            cls, _ambiguous = _classify(surfaces)
            stats[cls]["fp"] += 1

    return {
        "protocol": "v3",
        "n_ambiguous_gold_units": n_ambiguous_gold_units,
        "n_gold_mentions_dropped_by_tier": n_gold_mentions_dropped_by_tier,
        "classes": {
            cls: {
                **s,
                "R_doc": _cell(s["tp"], s["tp"] + s["fn"]),
                "P_doc": _cell(s["tp"], s["tp"] + s["fp"]),
            }
            for cls, s in stats.items()
        },
    }
