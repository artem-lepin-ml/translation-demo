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


# ── Survival-stage factorized metrics (pooled, unit = gold entity) ─────────
#
# ``aggregate_survival`` is a SIBLING of ``aggregate_corpus``, not an
# extension of it: its per-article input shape is genuinely different
# (un-deduplicated predicted MENTIONS carrying candidate lists, title-scoped
# anchor-exclusion filtering) and its output is POOLED -- no named/term
# split, unlike aggregate_corpus's classes. Both share the ``_cell``/
# ``wilson_ci`` primitives and the gold-side tier filter convention.
#
# Factors the pipeline's end-to-end entity recall into three independently
# interpretable survival rates (paper Table C / tab:grounding-results):
#   R_NER    -- was the gold entity's span recognized at all (extraction)?
#   R_search -- among recognized entities, did candidate search surface the
#               gold QID at all (retrieval)?
#   A_disamb -- among search-survived entities, did disambiguation pick the
#               gold QID (judge/exact-match correctness)?
#   R = R_NER * R_search * A_disamb  ==  end-to-end entity recall
# plus a conservative-lower-bound precision P over predicted linked entities.

ExclusionId = tuple[str, int, str, str, int]  # (title, token_index, anchor_text, qid, span_len)


class PredMention(TypedDict):
    """One predicted mention's overlap/search/disambiguation-relevant
    fields, straight off a ``pred.jsonl`` record. Unlike ``ArticleUnits``'s
    ``pred_tuples`` (deduped, qid-is-not-None only), this is the RAW
    per-mention list: R_search/A_disamb need every mention's own candidate
    list and resolved QID, and R_NER needs even ungrounded mentions (a
    mention can be recognized -- overlap a gold span -- and still fail to
    resolve to any QID)."""

    index: int
    span_len: int
    qid: str | None
    candidates: list[dict]  # [{"qid": ..., ...}, ...] -- pred.jsonl's own compact shape


class SurvivalArticleUnits(TypedDict):
    """Per-article input for ``aggregate_survival``. Carries ``title``
    (unlike ``ArticleUnits``) because anchor-exclusion filtering is
    title-scoped (``data/eval/wiki/anchor_exclusions.json``'s identity is
    ``(title, token_index, anchor_text, qid, span_len)``)."""

    title: str
    gt_tuples: list[Tuple4]
    pred_mentions: list[PredMention]


def _overlaps(a_index: int, a_len: int, b_index: int, b_len: int) -> bool:
    """Token-range overlap test -- byte-identical to the formula every
    ``data/eval/wiki/cleanup/tools/*`` miss-analysis script
    (``search_miss_analysis.py`` and its siblings) already carries as a
    local port. This IS the canonical stage-1/2 overlap semantics (reused,
    not re-derived) -- gold mention x predicted mention overlap on the
    shared article-local token-index convention."""
    return a_index < b_index + b_len and b_index < a_index + a_len


def _effective_gold_entities(
    articles: list[SurvivalArticleUnits],
    tier_assignment: dict[str, int],
    excluded_gold_identities: set[ExclusionId] | None,
) -> tuple[dict[tuple[str, str], list[tuple[int, int]]], int, int]:
    """``(title, qid) -> [(token_index, span_len), ...]`` for every
    surviving gold mention, after the SAME two-stage filter
    ``data/eval/wiki/dataset_stats.json``'s cascade applies: keep a gold
    mention iff ``tier_assignment.get(qid, 0) == 0`` AND ``(title,
    token_index, anchor_text, qid, span_len)`` is not in
    ``excluded_gold_identities`` (the approved anchor-exclusions overlay,
    applied at scoring time -- ``gt.jsonl`` itself stays raw). Both are
    independent drop conditions (order doesn't affect the surviving set),
    so a mention already dropped by tier is never also counted against the
    exclusion counter, matching ``compute_dataset_stats.py``'s
    ``overlap_excl_already_t2dropped`` convention.

    Returns ``(entities, n_dropped_by_tier, n_dropped_by_exclusion)``.
    """
    excluded = excluded_gold_identities or set()
    entities: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    n_dropped_by_tier = 0
    n_dropped_by_exclusion = 0
    for article in articles:
        title = article["title"]
        for t in article["gt_tuples"]:
            idx, surf, qid, slen = t
            if tier_assignment.get(qid, 0) != 0:
                n_dropped_by_tier += 1
                continue
            if (title, idx, surf, qid, slen) in excluded:
                n_dropped_by_exclusion += 1
                continue
            entities[(title, qid)].append((idx, slen))
    return entities, n_dropped_by_tier, n_dropped_by_exclusion


def aggregate_survival(
    articles: list[SurvivalArticleUnits],
    *,
    tier_assignment: dict[str, int],
    excluded_gold_identities: set[ExclusionId] | None = None,
) -> dict:
    """Factorized survival-stage metrics, unit = gold entity (unique
    ``(article, QID)`` pair, tier + approved-exclusions filtered, same gold
    population ``aggregate_corpus`` scores against -- POOLED, no named/term
    split).

    For each gold entity, its gold mentions are pooled and every predicted
    mention overlapping ANY of them (``_overlaps``, token-range) is
    collected into that entity's ``overlapping`` set:

    - **Recognized** (R_NER numerator): ``overlapping`` is non-empty --
      SOME predicted mention's span overlaps a gold mention's span,
      regardless of whether that predicted mention ever resolved to a QID.
      ``R_NER = n_recognized / n_gold_entities``. By construction this is
      exactly ``1 - not_extracted_rate`` of
      ``search_miss_analysis.py``'s outcome classifier run over the same
      inputs (its ``not_extracted`` outcome is precisely "no overlapping
      predicted mention"; unit tests assert the identity).
    - **Search-survived** (R_search numerator, among recognized entities
      only): the gold QID is a member of the UNION of ``candidates`` qids
      across every overlapping mention (a missing/empty ``candidates``
      list -- including a ``pred.jsonl`` record from a run that predates
      the 2026-07-10 candidates-field patch -- contributes nothing to the
      union; this is a provenance gap, not evidence search failed).
      ``R_search = n_search_survived / n_recognized``.
    - **Disambiguated correctly** (A_disamb numerator, among search-survived
      entities only): SOME overlapping mention's own resolved ``qid`` field
      equals the gold QID. ``A_disamb = n_disamb_correct / n_search_survived``.
    - **R** (end-to-end, factorized): ``n_disamb_correct / n_gold_entities``.
      Computed directly from the (nested: disamb-correct subset-of
      search-survived subset-of recognized subset-of gold) counts rather
      than by multiplying the three ratios' float ``value``s -- algebraically
      identical to ``R_NER * R_search * A_disamb`` whenever every
      intermediate stage has a well-defined (non-zero-denominator) rate,
      and still exactly correct even when an intermediate denominator is 0
      (a 0/0 mid-pipeline ratio would otherwise poison a naive float
      product with ``None``).
    - **R_direct**: ``n_direct_correct / n_gold_entities``, where
      direct-correct = SOME overlapping mention's resolved ``qid`` equals
      the gold QID -- computed WITHOUT requiring search-survival first.
      ``R["matched"] + n_resolved_correct_search_miss == R_direct["matched"]``
      always, by construction (a direct-correct entity is either
      search-survived-and-correct, counted in R, or resolved-correct
      despite its own overlapping mentions' candidate lists never carrying
      the gold QID -- counted in ``n_resolved_correct_search_miss`` instead).
      **They agree exactly (divergence count 0)** whenever every predicted
      mention's ``candidates`` list was actually recorded and the resolved
      ``qid`` was chosen FROM that list, which the live pipeline guarantees
      by construction (``LabelFirstGrounding.ground()`` always picks
      ``chosen_qid`` out of its own ``candidates``, and ``pred.jsonl``
      records that exact same list) -- the only real-world source of
      divergence found so far is scoring an OLDER run dir whose
      ``pred.jsonl`` predates the candidates-field patch (2026-07-10) and
      so never recorded a ``candidates`` key at all.
    - **P** (conservative lower bound; first-mention-only gold sparsity):
      pooled entity-level precision over PREDICTED LINKED entities --
      ``pred_linked`` = every unique ``(article, qid)`` pair with
      ``qid is not None`` across ALL predicted mentions (repeat links of
      the same QID in one article dedup to a single entry, so a repeat
      mention never inflates either P's numerator or its denominator
      beyond the single-mention case -- see the repeat-link unit test).
      ``TP_pred_linked`` = the subset whose ``qid`` is a member of that
      article's gold-entity QID set (same tier+exclusion-filtered gold
      population as above; predictions get NO tier filter, mirroring
      ``aggregate_corpus``'s own asymmetric-by-design P_doc). ``P =
      |TP_pred_linked| / |pred_linked|``. It is a LOWER bound because
      Wikipedia's hyperlink convention links an entity only at its first
      mention (often only once per article at all) -- a correctly grounded
      predicted entity that editors simply never linked in that article
      has no gold counterpart and always counts as FP, dedup or not; the
      dedup above only prevents repeats from being double-PENALIZED, it
      does not and cannot rescue a genuinely gold-absent correct grounding
      from counting against P.

    Every rate is a ``_cell`` (Wilson CI + ``matched``/``total`` counts, the
    same primitive ``aggregate_corpus`` uses) so the paper table has both
    the point estimate and its uncertainty, and honest reporting always has
    the raw counts backing it.
    """
    gold_entities, n_dropped_by_tier, n_dropped_by_exclusion = _effective_gold_entities(
        articles, tier_assignment, excluded_gold_identities
    )
    n_gold_entities = len(gold_entities)

    pred_mentions_by_title: dict[str, list[PredMention]] = {
        a["title"]: a["pred_mentions"] for a in articles
    }

    gold_qids_by_title: dict[str, set[str]] = defaultdict(set)
    for title, qid in gold_entities:
        gold_qids_by_title[title].add(qid)

    # Precision side: pooled predicted-linked-entity set, deduped per (title, qid).
    pred_linked: set[tuple[str, str]] = set()
    for title, mentions in pred_mentions_by_title.items():
        for m in mentions:
            if m.get("qid"):
                pred_linked.add((title, m["qid"]))
    n_pred_linked = len(pred_linked)
    n_pred_linked_tp = sum(1 for title, qid in pred_linked if qid in gold_qids_by_title.get(title, ()))

    n_recognized = 0
    n_search_survived = 0
    n_disamb_correct = 0
    n_direct_correct = 0
    n_resolved_correct_search_miss = 0

    for (title, qid), gold_mentions in gold_entities.items():
        article_pred = pred_mentions_by_title.get(title, [])
        overlapping: dict[tuple[int, int], PredMention] = {}
        for gidx, gslen in gold_mentions:
            for m in article_pred:
                if _overlaps(m["index"], m["span_len"], gidx, gslen):
                    overlapping[(m["index"], m["span_len"])] = m

        if not overlapping:
            continue
        n_recognized += 1

        mentions_ov = list(overlapping.values())
        candidate_qids = {
            c.get("qid") for m in mentions_ov for c in (m.get("candidates") or []) if c.get("qid")
        }
        search_survived = qid in candidate_qids
        direct_correct = any(m.get("qid") == qid for m in mentions_ov)

        if search_survived:
            n_search_survived += 1
            if direct_correct:
                n_disamb_correct += 1
        if direct_correct:
            n_direct_correct += 1
            if not search_survived:
                n_resolved_correct_search_miss += 1

    return {
        "n_gold_entities": n_gold_entities,
        "n_gold_mentions_dropped_by_tier": n_dropped_by_tier,
        "n_gold_mentions_dropped_by_exclusion": n_dropped_by_exclusion,
        "n_pred_linked_entities": n_pred_linked,
        "n_resolved_correct_search_miss": n_resolved_correct_search_miss,
        "R_NER": _cell(n_recognized, n_gold_entities),
        "R_search": _cell(n_search_survived, n_recognized),
        "A_disamb": _cell(n_disamb_correct, n_search_survived),
        "R": _cell(n_disamb_correct, n_gold_entities),
        "R_direct": _cell(n_direct_correct, n_gold_entities),
        "P": _cell(n_pred_linked_tp, n_pred_linked),
    }
