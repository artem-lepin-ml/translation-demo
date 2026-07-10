"""Tests for the protocol-v3 set-based document-level aggregator
(``aggregate_corpus``, spec 2026-07-10-wiki-eval-experiment-v2.md Sec.4.5,
decision Р9).

Tuple convention (spec Sec.3/E-D6): (index, surface, qid, span_len).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimpsest.terminology.evaluation.metrics import (
    UNDERPOWERED_THRESHOLD,
    _cell,
    aggregate_corpus,
)

REPO = Path(__file__).resolve().parents[1]
GT_PATH = REPO / "data/eval/wiki/gt.jsonl"
TIER_PATH = REPO / "data/eval/wiki/tier_assignment.json"
RUN_A = REPO / "reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z/pred.jsonl"
RUN_B = REPO / "reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--provider-9/111/2026-07-05T23-35-52Z/pred.jsonl"


# ---------------------------------------------------------------------------
# (a) Small synthetic-fixture tests
# ---------------------------------------------------------------------------


def test_tier_filter_drops_gold_but_prediction_on_same_qid_is_still_fp():
    """A gold tuple whose QID sits in a non-zero tier is skipped from the gold
    unit map (and counted in n_gold_mentions_dropped_by_tier), but a
    prediction sharing that same QID is not exempted by the filter -- it is
    still classified and counted as FP (spec Sec.4.5: the tier filter prunes
    gold, not predictions -- a deliberate protocol asymmetry)."""
    articles = [
        {
            "gt_tuples": [(0, "Кошка", "Qtiered", 1)],
            "pred_tuples": [(0, "Кошка", "Qtiered", 1)],
        }
    ]
    result = aggregate_corpus(articles, tier_assignment={"Qtiered": 1})

    assert result["n_gold_mentions_dropped_by_tier"] == 1
    assert result["classes"]["named"]["gold_units"] == 0
    assert result["classes"]["named"]["fp"] == 1
    assert result["classes"]["term"]["gold_units"] == 0
    assert result["classes"]["term"]["fp"] == 0


def test_mixed_case_gold_unit_is_named_and_ambiguous():
    """A gold unit whose repeated mentions disagree on case (one capitalized,
    one lowercase) is classified 'named' (any-capitalized rule) but also
    counted in n_ambiguous_gold_units."""
    articles = [
        {
            "gt_tuples": [
                (0, "Рим", "Q220", 1),
                (10, "рим", "Q220", 1),
            ],
            "pred_tuples": [(0, "Рим", "Q220", 1)],
        }
    ]
    result = aggregate_corpus(articles, tier_assignment={})

    assert result["n_ambiguous_gold_units"] == 1
    assert result["classes"]["named"]["gold_units"] == 1
    assert result["classes"]["named"]["tp"] == 1
    assert result["classes"]["term"]["gold_units"] == 0


def test_pred_unit_absent_from_gold_classified_by_own_surfaces():
    """An FP pred unit (QID not in the filtered gold set) is classified by
    its OWN predicted surfaces, not by any gold-side information."""
    articles = [
        {
            "gt_tuples": [],
            "pred_tuples": [(0, "легион", "Qfp", 1)],
        }
    ]
    result = aggregate_corpus(articles, tier_assignment={})

    assert result["classes"]["term"]["fp"] == 1
    assert result["classes"]["named"]["fp"] == 0


def test_repeated_mentions_dedup_to_one_unit():
    """Repeated gold/pred mentions of the same (article, QID) collapse into a
    single unit -- gold_units and tp/fn/fp count units, not raw mention rows."""
    articles = [
        {
            "gt_tuples": [
                (0, "Рим", "Q220", 1),
                (5, "Рима", "Q220", 1),
                (9, "Риме", "Q220", 1),
            ],
            "pred_tuples": [
                (0, "Рим", "Q220", 1),
                (5, "Рима", "Q220", 1),
            ],
        }
    ]
    result = aggregate_corpus(articles, tier_assignment={})

    assert result["classes"]["named"]["gold_units"] == 1
    assert result["classes"]["named"]["tp"] == 1
    assert result["classes"]["named"]["fn"] == 0
    assert result["classes"]["named"]["fp"] == 0


def test_empty_pred_gives_zero_recall_with_correct_totals():
    articles = [
        {
            "gt_tuples": [(0, "Рим", "Q220", 1), (5, "город", "Qterm", 1)],
            "pred_tuples": [],
        }
    ]
    result = aggregate_corpus(articles, tier_assignment={})

    named = result["classes"]["named"]
    term = result["classes"]["term"]
    assert named["tp"] == 0 and named["fn"] == 1 and named["fp"] == 0
    assert term["tp"] == 0 and term["fn"] == 1 and term["fp"] == 0
    assert named["R_doc"]["value"] == pytest.approx(0.0)
    assert named["R_doc"]["total"] == 1
    assert named["P_doc"]["value"] is None  # 0/0 -- uninformative, not a crash
    assert named["P_doc"]["total"] == 0


def test_cell_shape_has_wilson_ci_keys():
    articles = [
        {
            "gt_tuples": [(0, "Рим", "Q220", 1)],
            "pred_tuples": [(0, "Рим", "Q220", 1)],
        }
    ]
    result = aggregate_corpus(articles, tier_assignment={})
    cell = result["classes"]["named"]["R_doc"]
    assert set(cell) == {"matched", "total", "value", "ci_lo", "ci_hi", "underpowered"}
    assert cell["matched"] == 1
    assert cell["total"] == 1
    assert cell["value"] == pytest.approx(1.0)


def test_protocol_key_present():
    result = aggregate_corpus([], tier_assignment={})
    assert result["protocol"] == "v3"


# ── _cell: shared Wilson-CI primitive, retained from the retired            #
# mention-level aggregator (moved here from test_wiki_metrics.py, which was #
# deleted along with the mention-level protocol it tested, spec §7).        #


def test_cell_underpowered_below_threshold():
    cell = _cell(5, UNDERPOWERED_THRESHOLD - 1)
    assert cell["underpowered"] is True


def test_cell_not_underpowered_at_threshold():
    cell = _cell(5, UNDERPOWERED_THRESHOLD)
    assert cell["underpowered"] is False


def test_cell_zero_total_is_uninformative_not_a_crash():
    cell = _cell(0, 0)
    assert cell["total"] == 0
    assert cell["matched"] == 0
    assert cell["value"] is None


# ---------------------------------------------------------------------------
# (b) Regression anchors on committed artifacts
#
# These anchors are RAW-pred: the retired sitelink-replay cleaning (spec
# Sec.7, deleted by this same change) is NOT applied. The paper's pre-redo
# numbers (named 3265/4032, term 621/1530) were computed on sitelink-CLEAN
# predictions and differ slightly from the raw numbers below by construction
# -- both are legitimate, they answer different questions.
#
# Recomputed 2026-07-10 (corpus swap): 5 non-ancient-history articles in
# gt.jsonl (Гелиополиты, Стигия, Яффа, Кесарево безумие, Керченский пролив)
# were replaced by the next seed-42 walk survivors from the same sections
# (see data/eval/wiki/cleanup/replacements_2026-07-10.json). RUN_A/RUN_B
# pred.jsonl are unchanged (predictions were never generated for the 5 new
# articles), so this recompute mechanically re-scores the same runs against
# the new gold -- gold_units drops from 5551 to 5358 and tp/fn/fp shift
# accordingly; this is expected and not a code regression.
#
# Recomputed again 2026-07-10 (tier extension): tier_assignment.json initially
# defaulted the 130 QIDs introduced by the 5 replacement articles to
# drop_level 0 (kept) via aggregate_corpus's `tier_assignment.get(qid, 0)`
# fallback -- extend_tier_assignment.py then classified them properly (2 T1 +
# 4 T2 drops among them), so n_gold_mentions_dropped_by_tier rises 756->764
# and gold_units drops 5358->5351; again expected, not a code regression (see
# data/eval/wiki/dataset_stats.json for the corpus-wide cascade).
# ---------------------------------------------------------------------------


def _load_gt_articles() -> list[dict]:
    articles = []
    for line in GT_PATH.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        articles.append({"title": rec["title"], "gt_tuples": [tuple(t) for t in rec["gt_tuples"]]})
    return articles


def _load_pred_by_title(pred_path: Path) -> dict[str, list[tuple]]:
    by_title: dict[str, list[tuple]] = {}
    for line in pred_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("qid"):
            by_title.setdefault(r["title"], []).append(
                (r["index"], r["surface"], r["qid"], r["span_len"])
            )
    return by_title


def _build_articles(pred_path: Path) -> list[dict]:
    gt_articles = _load_gt_articles()
    pred_by_title = _load_pred_by_title(pred_path)
    return [
        {"gt_tuples": a["gt_tuples"], "pred_tuples": pred_by_title.get(a["title"], [])}
        for a in gt_articles
    ]


@pytest.fixture(scope="module")
def tier_assignment() -> dict[str, int]:
    return json.loads(TIER_PATH.read_text(encoding="utf-8"))


@pytest.mark.skipif(not GT_PATH.exists(), reason="gold corpus not present in this checkout")
@pytest.mark.skipif(not TIER_PATH.exists(), reason="tier assignment not present in this checkout")
@pytest.mark.skipif(not RUN_A.exists(), reason="run A pred.jsonl not present in this checkout")
def test_regression_anchor_run_a_gemini(tier_assignment):
    articles = _build_articles(RUN_A)
    result = aggregate_corpus(articles, tier_assignment=tier_assignment)

    assert result["n_ambiguous_gold_units"] == 112
    assert result["n_gold_mentions_dropped_by_tier"] == 764

    named = result["classes"]["named"]
    assert (named["tp"], named["fn"], named["fp"], named["gold_units"]) == (3078, 807, 1526, 3885)

    term = result["classes"]["term"]
    assert (term["tp"], term["fn"], term["fp"], term["gold_units"]) == (593, 873, 667, 1466)

    assert named["gold_units"] + term["gold_units"] == 5351


@pytest.mark.skipif(not GT_PATH.exists(), reason="gold corpus not present in this checkout")
@pytest.mark.skipif(not TIER_PATH.exists(), reason="tier assignment not present in this checkout")
@pytest.mark.skipif(not RUN_B.exists(), reason="run B pred.jsonl not present in this checkout")
def test_regression_anchor_run_b_deepseek(tier_assignment):
    articles = _build_articles(RUN_B)
    result = aggregate_corpus(articles, tier_assignment=tier_assignment)

    named = result["classes"]["named"]
    assert (named["tp"], named["fn"], named["fp"], named["gold_units"]) == (2705, 1180, 1259, 3885)

    term = result["classes"]["term"]
    assert (term["tp"], term["fn"], term["fp"], term["gold_units"]) == (550, 916, 542, 1466)

    assert named["gold_units"] + term["gold_units"] == 5351


@pytest.mark.skipif(not GT_PATH.exists(), reason="gold corpus not present in this checkout")
@pytest.mark.skipif(not TIER_PATH.exists(), reason="tier assignment not present in this checkout")
def test_gold_named_plus_term_invariant(tier_assignment):
    """Spec Sec.6: named+term gold_units == 5351, independent of which run's
    predictions are scored against it (the gold side alone determines this).
    Was 5562 before the IPA-template symbol-fragment gold-anchor fix (2026-07-10,
    docs/reports/debugger-ipa-parser-gold-anchors.md) dropped 56 spurious
    per-phoneme anchors from gt.jsonl -- most collapsed into already-counted
    gold units or were tier-filtered anyway, netting an 11-unit shift to 5551.
    Then 5551 -> 5358 after the same-day 5-article corpus swap
    (data/eval/wiki/cleanup/replacements_2026-07-10.json) replaced 5 non-ancient
    articles with 5 new ones of different anchor density. Then 5358 -> 5351
    (this recompute) once tier_assignment.json was extended to the 130 QIDs
    those 5 articles introduced (extend_tier_assignment.py) -- 7 of the
    resulting (article, QID) gold units are now correctly tier-dropped instead
    of defaulting to kept."""
    articles = _build_articles(RUN_A)
    result = aggregate_corpus(articles, tier_assignment=tier_assignment)
    total = result["classes"]["named"]["gold_units"] + result["classes"]["term"]["gold_units"]
    assert total == 5351
