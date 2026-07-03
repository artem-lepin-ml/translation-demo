"""Tests for the three GT/prediction matching modes: M1 strict, M2 span-overlap, M3 document.

Tuple convention (spec Sec.3/E-D6): (index, surface, qid, span_len).
"""
from __future__ import annotations

from palimpsest.terminology.evaluation.matching import (
    match_m1,
    match_m2,
    match_m3,
)


def test_m1_matches_on_index_norm_surface_and_qid():
    gt = [(5, "Рима", "Q220", 1)]
    pred = [(5, "Рима", "Q220", 1)]
    matched_gt, matched_pred = match_m1(gt, pred)
    assert matched_gt == set(gt)
    assert matched_pred == set(pred)


def test_m1_matches_inflected_surface_via_norm():
    # norm() casefolds and normalizes dashes/ё; here differing case should still match.
    gt = [(5, "РИМА", "Q220", 1)]
    pred = [(5, "рима", "Q220", 1)]
    matched_gt, matched_pred = match_m1(gt, pred)
    assert matched_gt == set(gt)
    assert matched_pred == set(pred)


def test_m1_rejects_index_mismatch():
    gt = [(5, "Рима", "Q220", 1)]
    pred = [(6, "Рима", "Q220", 1)]
    matched_gt, matched_pred = match_m1(gt, pred)
    assert matched_gt == set()
    assert matched_pred == set()


def test_m1_rejects_qid_mismatch():
    gt = [(5, "Рима", "Q220", 1)]
    pred = [(5, "Рима", "Q999", 1)]
    matched_gt, matched_pred = match_m1(gt, pred)
    assert matched_gt == set()
    assert matched_pred == set()


def test_m1_rejects_surface_mismatch_even_when_normed():
    gt = [(5, "Рима", "Q220", 1)]
    pred = [(5, "Империи", "Q220", 1)]
    matched_gt, matched_pred = match_m1(gt, pred)
    assert matched_gt == set()
    assert matched_pred == set()


def test_m2_matches_on_span_overlap_and_qid_without_surface_check():
    # GT spans tokens [5,7) "Римской империи"; pred spans [6,8) "империи, древнего" — overlap at 6.
    gt = [(5, "Римской империи", "Q220", 2)]
    pred = [(6, "империи, древнего", "Q220", 2)]
    matched_gt, matched_pred = match_m2(gt, pred)
    assert matched_gt == set(gt)
    assert matched_pred == set(pred)


def test_m2_multiword_overlap_matches_single_token_pred_inside_span():
    # GT spans [5,7); pred single token at index 6 falls inside the GT span.
    gt = [(5, "Римской империи", "Q220", 2)]
    pred = [(6, "империи", "Q220", 1)]
    matched_gt, matched_pred = match_m2(gt, pred)
    assert matched_gt == set(gt)
    assert matched_pred == set(pred)


def test_m2_no_overlap_does_not_match():
    gt = [(5, "Римской империи", "Q220", 2)]
    pred = [(10, "империи", "Q220", 1)]
    matched_gt, matched_pred = match_m2(gt, pred)
    assert matched_gt == set()
    assert matched_pred == set()


def test_m2_requires_qid_equality_despite_overlap():
    gt = [(5, "Римской империи", "Q220", 2)]
    pred = [(5, "Римской империи", "Q999", 2)]
    matched_gt, matched_pred = match_m2(gt, pred)
    assert matched_gt == set()
    assert matched_pred == set()


def test_m2_ignores_surface_difference_on_overlap():
    # Different surfaces entirely, only overlap + qid matter for M2.
    gt = [(5, "Римской", "Q220", 1)]
    pred = [(5, "totallydifferent", "Q220", 1)]
    matched_gt, matched_pred = match_m2(gt, pred)
    assert matched_gt == set(gt)
    assert matched_pred == set(pred)


def test_m3_matches_on_qid_present_anywhere_in_document():
    # GT at index 5, pred at a completely different index — M3 credits by qid alone.
    gt = [(5, "Рима", "Q220", 1)]
    pred = [(200, "Рим", "Q220", 1)]
    matched_gt, matched_pred = match_m3(gt, pred)
    assert matched_gt == set(gt)
    assert matched_pred == set(pred)


def test_m3_no_match_when_qid_absent_from_other_side():
    gt = [(5, "Рима", "Q220", 1)]
    pred = [(200, "Рим", "Q999", 1)]
    matched_gt, matched_pred = match_m3(gt, pred)
    assert matched_gt == set()
    assert matched_pred == set()


def test_m3_matches_all_gt_and_pred_tuples_sharing_a_qid():
    # Multiple GT mentions of the same entity should all be credited once pred has the qid anywhere.
    gt = [(5, "Рима", "Q220", 1), (50, "Рим", "Q220", 1)]
    pred = [(200, "Рим", "Q220", 1)]
    matched_gt, matched_pred = match_m3(gt, pred)
    assert matched_gt == set(gt)
    assert matched_pred == set(pred)
