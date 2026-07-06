"""Tests for recall/precision/CI/slice aggregation over GT vs prediction tuples.

Tuple convention (spec Sec.3/E-D6): (index, surface, qid, span_len).
"""
from __future__ import annotations

import pytest

from palimpsest.terminology.evaluation.metrics import (
    _precision_counts_p3_ex,
    aggregate,
    aggregate_corpus,
    precision,
    recall,
)


def test_recall_m1_arithmetic_against_closed_form():
    gt = [(0, "a", "Q1", 1), (1, "b", "Q2", 1), (2, "c", "Q3", 1), (3, "d", "Q4", 1)]
    pred = [(0, "a", "Q1", 1), (1, "b", "Q2", 1)]
    result = recall(gt, pred, mode="m1")
    assert result["total"] == 4
    assert result["matched"] == 2
    assert result["value"] == pytest.approx(0.5)


def test_recall_m2_span_overlap_mode():
    gt = [(0, "Римской империи", "Q1", 2), (5, "e", "Q5", 1)]
    pred = [(1, "империи", "Q1", 1)]
    result = recall(gt, pred, mode="m2")
    assert result["total"] == 2
    assert result["matched"] == 1
    assert result["value"] == pytest.approx(0.5)


def test_recall_m3_document_mode():
    gt = [(0, "a", "Q1", 1), (100, "a again", "Q1", 1)]
    pred = [(50, "a", "Q1", 1)]
    result = recall(gt, pred, mode="m3")
    assert result["total"] == 2
    assert result["matched"] == 2
    assert result["value"] == pytest.approx(1.0)


def test_recall_zero_gt_is_uninformative_not_a_crash():
    result = recall([], [], mode="m1")
    assert result["total"] == 0
    assert result["matched"] == 0
    # zero-total is handled the same way wilson_ci treats it: maximally uninformative.
    assert result["value"] in (0.0, None)


def test_precision_p1_base_arithmetic():
    gt = [(0, "a", "Q1", 1), (1, "b", "Q2", 1)]
    pred = [(0, "a", "Q1", 1), (1, "b", "Q2", 1), (2, "x", "Q9", 1)]
    result = precision(gt, pred, mode="m1", variant="p1")
    assert result["total"] == 3
    assert result["matched"] == 2
    assert result["value"] == pytest.approx(2 / 3)


def test_precision_p2_dedup_by_norm_lemma_or_surface_and_qid():
    gt = [(0, "рим", "Q1", 1)]
    # Two predictions with the same (norm-surface, qid) — dedup before counting.
    pred = [(0, "Рим", "Q1", 1), (10, "Рим", "Q1", 1), (20, "x", "Q9", 1)]
    result = precision(gt, pred, mode="m1", variant="p2")
    assert result["total"] == 2  # deduped: {(рим,Q1), (x,Q9)}
    assert result["matched"] == 1
    assert result["value"] == pytest.approx(0.5)


def test_precision_p3_label_justified_counts_outside_gt_pred_when_label_exists():
    gt = [(0, "a", "Q1", 1)]
    pred = [(0, "a", "Q1", 1), (5, "b", "Q2", 1)]

    def label_exists(surface: str) -> bool:
        return surface == "b"

    result = precision(
        gt, pred, mode="m1", variant="p3", label_exists=label_exists, resolved_by="llm_disambiguation"
    )
    assert result["total"] == 2
    assert result["matched"] == 2  # "a" matched GT, "b" justified by label
    assert result["value"] == pytest.approx(1.0)


def test_precision_p3_refuses_unsliced_aggregate():
    gt = [(0, "a", "Q1", 1)]
    pred = [(0, "a", "Q1", 1)]
    with pytest.raises((ValueError, TypeError)):
        precision(gt, pred, mode="m1", variant="p3", label_exists=lambda s: True, resolved_by=None)


def test_wilson_ci_flags_underpowered_below_30():
    gt = [(i, "a", "Q1", 1) for i in range(10)]
    pred = [(i, "a", "Q1", 1) for i in range(10)]
    result = recall(gt, pred, mode="m1")
    assert result["underpowered"] is True


def test_wilson_ci_not_underpowered_at_30_or_more():
    gt = [(i, "a", "Q1", 1) for i in range(30)]
    pred = [(i, "a", "Q1", 1) for i in range(30)]
    result = recall(gt, pred, mode="m1")
    assert result["underpowered"] is False


def test_aggregate_slices_sum_back_to_totals_by_stratum():
    gt = [
        (0, "a", "Q1", 1),
        (1, "b", "Q2", 1),
        (2, "c", "Q3", 1),
        (3, "d", "Q4", 1),
    ]
    pred = [
        (0, "a", "Q1", 1),
        (1, "b", "Q2", 1),
        (2, "c", "Q3", 1),
    ]
    stratum_of = {0: "hard", 1: "hard", 2: "typical", 3: "typical"}
    resolved_by_of = {0: "exact_label", 1: "exact_label", 2: "llm_disambiguation", 3: "llm_disambiguation"}
    type_of = {0: "named_entity", 1: "term", 2: "named_entity", 3: "term"}

    result = aggregate(
        gt,
        pred,
        resolved_by_of=resolved_by_of,
        stratum_of=stratum_of,
        type_of=type_of,
    )

    assert "slices" in result
    stratum_slices = result["slices"]["stratum"]
    total_matched = sum(s["recall"]["m1"]["matched"] for s in stratum_slices.values())
    total_gt = sum(s["recall"]["m1"]["total"] for s in stratum_slices.values())
    assert total_matched == result["recall"]["m1"]["matched"]
    assert total_gt == result["recall"]["m1"]["total"] == len(gt)


def test_aggregate_p3_not_present_as_unsliced_aggregate():
    gt = [(0, "a", "Q1", 1)]
    pred = [(0, "a", "Q1", 1)]
    result = aggregate(
        gt,
        pred,
        resolved_by_of={0: "exact_label"},
        stratum_of={0: "typical"},
        type_of={0: "named_entity"},
    )
    # top-level precision dict must not carry a "p3" key at the unsliced level
    assert "p3" not in result["precision"]
    # but per resolved_by slice it should be present
    resolved_by_slices = result["slices"]["resolved_by"]
    for slice_data in resolved_by_slices.values():
        assert "p3" in slice_data["precision"] or slice_data["precision"].get("p3") is None


# ── aggregate_corpus: per-article scoping (bug fix regression) ─────────────


def test_aggregate_corpus_does_not_cross_match_identical_indices_across_articles():
    """Two articles each have a GT tuple at (index=5, ...) sharing the same
    QID but with DIFFERENT strata and different (unrelated) predictions. A
    flattened cross-article match would let article A's index-5 prediction
    satisfy article B's index-5 GT tuple (or vice versa) purely because the
    bare index+QID collide. aggregate_corpus must match each article only
    against its own predictions, so recall here is exactly 1/2 per article
    (each article's own prediction hits only its own GT), and the stratum
    slices must not be corrupted by last-write-wins on the bare index key.
    """
    article_a = {
        "gt_tuples": [(5, "рим", "Q1", 1)],
        "pred_tuples": [(5, "рим", "Q1", 1)],  # article A's own correct prediction
        "resolved_by_of": {5: "exact_label"},
        "stratum_of": {5: "hard"},
        "type_of": {5: "named_entity"},
    }
    article_b = {
        "gt_tuples": [(5, "рим", "Q1", 1)],  # same bare index + same QID as A
        "pred_tuples": [],  # article B's system found NOTHING
        "resolved_by_of": {5: "exact_label"},
        "stratum_of": {5: "typical"},  # different stratum than A
        "type_of": {5: "named_entity"},
    }

    result = aggregate_corpus([article_a, article_b])

    # Unsliced: 1 of 2 GT tuples matched (article A's), NOT 2 of 2 -- a
    # cross-article match would wrongly credit B's tuple via A's prediction.
    assert result["recall"]["m1"]["matched"] == 1
    assert result["recall"]["m1"]["total"] == 2
    assert result["recall"]["m2"]["matched"] == 1
    assert result["recall"]["m2"]["total"] == 2
    # M3 "document-level, anywhere" must also stay within one article: it
    # must NOT let B's GT tuple match via A's document-level QID presence.
    assert result["recall"]["m3"]["matched"] == 1
    assert result["recall"]["m3"]["total"] == 2

    # Stratum slices: article A's tuple (hard) is fully matched; article B's
    # tuple (typical) is unmatched. Last-write-wins on the bare index key
    # would put BOTH tuples in whichever stratum was written last.
    stratum_slices = result["slices"]["stratum"]
    assert set(stratum_slices.keys()) == {"hard", "typical"}
    assert stratum_slices["hard"]["recall"]["m1"]["matched"] == 1
    assert stratum_slices["hard"]["recall"]["m1"]["total"] == 1
    assert stratum_slices["typical"]["recall"]["m1"]["matched"] == 0
    assert stratum_slices["typical"]["recall"]["m1"]["total"] == 1

    # Sanity: slice totals still sum back to the unsliced total.
    total_gt = sum(s["recall"]["m1"]["total"] for s in stratum_slices.values())
    assert total_gt == result["recall"]["m1"]["total"] == 2


def test_aggregate_corpus_sums_raw_counts_before_computing_ci_once():
    """Wilson CI must be computed once from the summed counts, not averaged
    per-article -- e.g. two articles each with 1/1 recall must aggregate to
    total=2, matched=2 (CI computed on n=2), not two separate n=1 cells."""
    article_a = {
        "gt_tuples": [(0, "a", "Q1", 1)],
        "pred_tuples": [(0, "a", "Q1", 1)],
        "resolved_by_of": {0: "exact_label"},
        "stratum_of": {0: "typical"},
        "type_of": {0: "term"},
    }
    article_b = {
        "gt_tuples": [(0, "b", "Q2", 1)],
        "pred_tuples": [(0, "b", "Q2", 1)],
        "resolved_by_of": {0: "exact_label"},
        "stratum_of": {0: "typical"},
        "type_of": {0: "term"},
    }

    result = aggregate_corpus([article_a, article_b])

    assert result["recall"]["m1"]["matched"] == 2
    assert result["recall"]["m1"]["total"] == 2
    # CI on the summed n=2 cell, matching a direct wilson_ci(2, 2) call.
    from palimpsest.terminology.eval_harness import wilson_ci

    expected_lo, expected_hi = wilson_ci(2, 2)
    assert result["recall"]["m1"]["ci_lo"] == expected_lo
    assert result["recall"]["m1"]["ci_hi"] == expected_hi


def test_aggregate_corpus_p3_only_inside_resolved_by_slice():
    article = {
        "gt_tuples": [(0, "a", "Q1", 1)],
        "pred_tuples": [(0, "a", "Q1", 1)],
        "resolved_by_of": {0: "exact_label"},
        "stratum_of": {0: "typical"},
        "type_of": {0: "term"},
    }
    result = aggregate_corpus([article])
    assert "p3" not in result["precision"]
    assert "p3" in result["slices"]["resolved_by"]["exact_label"]["precision"]
    assert "p3" not in result["slices"]["stratum"]["typical"]["precision"]


def test_aggregate_corpus_empty_article_list_is_uninformative_not_a_crash():
    result = aggregate_corpus([])
    assert result["recall"]["m1"]["total"] == 0
    assert result["recall"]["m1"]["matched"] == 0
    assert result["slices"]["stratum"] == {}


# ── P3\\exact headline (real label_exists predicate, wiki_eval.py --p3) ─────


def _p3_ex_fixture():
    """One GT tuple matched by an exact_label prediction, plus two
    llm_disambiguation predictions that don't match GT: one has a surface
    that exists as a Wikidata label (justified), one doesn't (unjustified)."""
    gt = [(0, "a", "Q1", 1)]
    pred = [
        (0, "a", "Q1", 1),   # exact_label -- matches GT, EXCLUDED from p3_ex's denominator
        (5, "b", "Q2", 1),   # llm_disambiguation, no GT match, label_exists("b") -> justified
        (10, "c", "Q3", 1),  # llm_disambiguation, no GT match, label_exists("c") -> NOT justified
    ]
    resolved_by_of = {0: "exact_label", 5: "llm_disambiguation", 10: "llm_disambiguation"}

    def label_exists(surface: str) -> bool:
        return surface == "b"

    return gt, pred, resolved_by_of, label_exists


def test_precision_counts_p3_ex_excludes_exact_label_from_denominator():
    gt, pred, resolved_by_of, label_exists = _p3_ex_fixture()
    matched, total = _precision_counts_p3_ex(
        gt, pred, mode="m2", resolved_by_of=resolved_by_of, label_exists=label_exists,
    )
    # Denominator is 2 (the two non-exact-label predictions), NOT 3 -- the
    # exact_label prediction is excluded entirely, not merely down-weighted.
    assert total == 2
    # "b" is justified via label_exists; "c" is not (and neither matches GT).
    assert matched == 1


def test_aggregate_corpus_p3_ex_absent_without_label_exists():
    gt, pred, resolved_by_of, _label_exists = _p3_ex_fixture()
    article = {
        "gt_tuples": gt,
        "pred_tuples": pred,
        "resolved_by_of": resolved_by_of,
        "stratum_of": {0: "typical"},
        "type_of": {0: "term"},
    }
    result = aggregate_corpus([article])
    assert "p3_ex" not in result["precision"]
    # p1 stays over the FULL prediction set (3), unaffected by p3_ex's exclusion.
    assert result["precision"]["p1"]["total"] == 3


def test_aggregate_corpus_p3_ex_headline_present_and_correct_when_label_exists_given():
    gt, pred, resolved_by_of, label_exists = _p3_ex_fixture()
    article = {
        "gt_tuples": gt,
        "pred_tuples": pred,
        "resolved_by_of": resolved_by_of,
        "stratum_of": {0: "typical"},
        "type_of": {0: "term"},
    }
    result = aggregate_corpus([article], label_exists=label_exists)
    assert result["precision"]["p3_ex"]["total"] == 2
    assert result["precision"]["p3_ex"]["matched"] == 1
    assert result["precision"]["p3_ex"]["value"] == pytest.approx(0.5)
    # p1/p2 untouched by passing label_exists (only "p3_ex" is added).
    assert result["precision"]["p1"]["total"] == 3


def test_aggregate_corpus_p3_ex_sums_matched_and_total_across_articles():
    gt_a, pred_a, resolved_by_of_a, label_exists = _p3_ex_fixture()
    # Second article: same shape, different token-index space (article-local
    # indices, spec E-D6) and a QID namespace disjoint from article A's.
    gt_b = [(0, "x", "Q10", 1)]
    pred_b = [
        (0, "x", "Q10", 1),     # exact_label match -- excluded from p3_ex denominator
        (5, "b", "Q20", 1),     # llm_disambiguation, label_exists("b") -> justified
    ]
    resolved_by_of_b = {0: "exact_label", 5: "llm_disambiguation"}

    article_a = {
        "gt_tuples": gt_a, "pred_tuples": pred_a, "resolved_by_of": resolved_by_of_a,
        "stratum_of": {0: "typical"}, "type_of": {0: "term"},
    }
    article_b = {
        "gt_tuples": gt_b, "pred_tuples": pred_b, "resolved_by_of": resolved_by_of_b,
        "stratum_of": {0: "typical"}, "type_of": {0: "term"},
    }

    result = aggregate_corpus([article_a, article_b], label_exists=label_exists)
    # article A: matched=1, total=2 (from the fixture); article B: matched=1, total=1.
    assert result["precision"]["p3_ex"]["total"] == 3
    assert result["precision"]["p3_ex"]["matched"] == 2


def test_aggregate_corpus_resolved_by_slice_p3_uses_real_label_exists_when_provided():
    # aggregate_corpus's resolved_by axis derives its slice VALUES from GT
    # indices (`_filter_by` looks up `mapping.get(t[0])` for `t` in `gt`), so
    # a second GT tuple at the SAME index as the llm_disambiguation
    # predictions is needed for that slice to exist at all; it carries an
    # unrelated QID so it doesn't itself get matched by anything.
    gt = [(0, "a", "Q1", 1), (5, "z", "Q999", 1)]
    pred = [
        (0, "a", "Q1", 1),   # exact_label -- matches gt[0]
        (5, "b", "Q2", 1),   # llm_disambiguation, no GT match, label_exists("b") -> justified
        (10, "c", "Q3", 1),  # llm_disambiguation, no GT match, label_exists("c") -> NOT justified
    ]
    resolved_by_of = {0: "exact_label", 5: "llm_disambiguation", 10: "llm_disambiguation"}

    def label_exists(surface: str) -> bool:
        return surface == "b"

    article = {
        "gt_tuples": gt,
        "pred_tuples": pred,
        "resolved_by_of": resolved_by_of,
        "stratum_of": {0: "typical", 5: "typical"},
        "type_of": {0: "term", 5: "term"},
    }

    # Default (no label_exists): P3 stub-equals P1 within the resolved_by
    # slice -- unchanged prior behaviour (activation must be opt-in).
    stub_result = aggregate_corpus([article])
    llm_slice_stub = stub_result["slices"]["resolved_by"]["llm_disambiguation"]["precision"]
    assert llm_slice_stub["p3"]["matched"] == llm_slice_stub["p1"]["matched"] == 0
    assert llm_slice_stub["p3"]["total"] == llm_slice_stub["p1"]["total"] == 2

    # With the real predicate: "b" gets label-justified inside the SAME
    # resolved_by slice, so p3 now diverges from p1 (still 0/2).
    real_result = aggregate_corpus([article], label_exists=label_exists)
    llm_slice_real = real_result["slices"]["resolved_by"]["llm_disambiguation"]["precision"]
    assert llm_slice_real["p1"]["matched"] == 0
    assert llm_slice_real["p3"]["matched"] == 1
    assert llm_slice_real["p3"]["total"] == 2
