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
    aggregate_survival,
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


# ---------------------------------------------------------------------------
# (c) aggregate_survival -- factorized R_NER/R_search/A_disamb/R/R_direct/P
# (pooled, unit = gold entity). Small synthetic fixtures.
# ---------------------------------------------------------------------------


def _article(title, gt_tuples, pred_mentions):
    return {"title": title, "gt_tuples": gt_tuples, "pred_mentions": pred_mentions}


def _pm(index, span_len, qid, candidates=None):
    """Build a PredMention with an EXPLICIT (possibly empty) candidates key."""
    return {"index": index, "span_len": span_len, "qid": qid, "candidates": candidates or []}


def test_survival_not_recognized_when_no_overlapping_prediction():
    """No predicted mention overlaps the gold span at all -- the gold entity
    is not recognized, contributing to R_NER's denominator only."""
    articles = [_article("A", [(0, "Рим", "Q220", 1)], [])]
    result = aggregate_survival(articles, tier_assignment={})

    assert result["n_gold_entities"] == 1
    assert result["R_NER"] == {"matched": 0, "total": 1, "value": pytest.approx(0.0),
                                "ci_lo": pytest.approx(0.0), "ci_hi": pytest.approx(0.7935),
                                "underpowered": True}
    # downstream stages have no recognized population to work over -- 0/0, uninformative
    assert result["R_search"]["total"] == 0 and result["R_search"]["value"] is None
    assert result["R"]["matched"] == 0 and result["R"]["total"] == 1


def test_survival_recognized_but_candidates_miss_gold_qid():
    """Entity recognized (span overlap) but the overlapping mention's own
    candidate list never contains the gold QID -- R_search misses it, and
    A_disamb's denominator (search-survived) stays 0 for this entity."""
    articles = [_article(
        "A", [(0, "Рим", "Q220", 1)],
        [_pm(0, 1, None, candidates=[{"qid": "Qwrong"}])],
    )]
    result = aggregate_survival(articles, tier_assignment={})

    assert result["R_NER"]["matched"] == 1 and result["R_NER"]["total"] == 1
    assert result["R_search"]["matched"] == 0 and result["R_search"]["total"] == 1
    assert result["A_disamb"]["total"] == 0  # no search-survived population
    assert result["R"] == {"matched": 0, "total": 1, "value": pytest.approx(0.0),
                            "ci_lo": pytest.approx(0.0), "ci_hi": pytest.approx(0.7935),
                            "underpowered": True}
    assert result["n_resolved_correct_search_miss"] == 0


def test_survival_candidates_hit_but_judge_wrong():
    """Candidate search DID surface the gold QID, but the mention's final
    resolved qid is a different candidate -- A_disamb counts this as a
    search-survived miss, not a recognition or search failure."""
    articles = [_article(
        "A", [(0, "Рим", "Q220", 1)],
        [_pm(0, 1, "Qwrong", candidates=[{"qid": "Q220"}, {"qid": "Qwrong"}])],
    )]
    result = aggregate_survival(articles, tier_assignment={})

    assert result["R_NER"]["matched"] == 1
    assert result["R_search"] == {"matched": 1, "total": 1, "value": pytest.approx(1.0),
                                   "ci_lo": pytest.approx(0.2065), "ci_hi": pytest.approx(1.0),
                                   "underpowered": True}
    assert result["A_disamb"]["matched"] == 0 and result["A_disamb"]["total"] == 1
    assert result["R"]["matched"] == 0
    assert result["R_direct"]["matched"] == 0
    assert result["n_resolved_correct_search_miss"] == 0


def test_survival_judge_right_fully_correct():
    """Fully correct pipeline outcome: recognized, gold QID in candidates,
    resolved qid == gold qid -- contributes 1 to every stage's numerator,
    and R == R_direct exactly (no structural divergence)."""
    articles = [_article(
        "A", [(0, "Рим", "Q220", 1)],
        [_pm(0, 1, "Q220", candidates=[{"qid": "Q220"}, {"qid": "Qother"}])],
    )]
    result = aggregate_survival(articles, tier_assignment={})

    for key in ("R_NER", "R_search", "A_disamb", "R", "R_direct"):
        assert result[key]["value"] == pytest.approx(1.0), key
    assert result["P"]["value"] == pytest.approx(1.0)
    assert result["n_resolved_correct_search_miss"] == 0


def test_survival_excluded_anchor_dropped_from_gold():
    """A gold mention whose identity is in ``excluded_gold_identities`` is
    dropped from the effective gold set entirely -- it does not count
    toward n_gold_entities, and is counted separately from the tier drop."""
    articles = [_article(
        "A",
        [(0, "мумия", "Q43616", 1), (5, "Рим", "Q220", 1)],
        [_pm(0, 1, "Q43616", candidates=[{"qid": "Q43616"}]),
         _pm(5, 1, "Q220", candidates=[{"qid": "Q220"}])],
    )]
    excluded = {("A", 0, "мумия", "Q43616", 1)}
    result = aggregate_survival(articles, tier_assignment={}, excluded_gold_identities=excluded)

    assert result["n_gold_entities"] == 1  # only Q220 survives
    assert result["n_gold_mentions_dropped_by_exclusion"] == 1
    assert result["n_gold_mentions_dropped_by_tier"] == 0
    assert result["R_NER"]["total"] == 1


def test_survival_tier_filter_drops_gold_same_as_aggregate_corpus():
    """Same asymmetric tier-filter convention as aggregate_corpus: a
    non-zero-tier gold QID is dropped from the gold set, counted in
    n_gold_mentions_dropped_by_tier -- independent of the exclusion filter."""
    articles = [_article("A", [(0, "Кошка", "Qtiered", 1)], [_pm(0, 1, "Qtiered", candidates=[{"qid": "Qtiered"}])])]
    result = aggregate_survival(articles, tier_assignment={"Qtiered": 1})

    assert result["n_gold_entities"] == 0
    assert result["n_gold_mentions_dropped_by_tier"] == 1
    assert result["R_NER"]["total"] == 0 and result["R_NER"]["value"] is None


def test_survival_precision_repeat_link_dedups_to_one_entity():
    """A predicted QID linked twice in the same article (repeat mention)
    dedups to ONE (title, qid) entry in pred_linked -- it does not inflate
    P's numerator or denominator beyond the single-link case, whether the
    repeat is a true positive or a false positive."""
    gold = [(0, "Рим", "Q220", 1)]

    tp_once = [_article("A", gold, [_pm(0, 1, "Q220")])]
    tp_repeat = [_article("A", gold, [_pm(0, 1, "Q220"), _pm(10, 1, "Q220")])]
    r_once = aggregate_survival(tp_once, tier_assignment={})
    r_repeat = aggregate_survival(tp_repeat, tier_assignment={})
    assert r_once["P"] == r_repeat["P"] == {
        "matched": 1, "total": 1, "value": pytest.approx(1.0),
        "ci_lo": pytest.approx(0.2065), "ci_hi": pytest.approx(1.0), "underpowered": True,
    }

    fp_once = [_article("A", [], [_pm(0, 1, "Qfp")])]
    fp_repeat = [_article("A", [], [_pm(0, 1, "Qfp"), _pm(10, 1, "Qfp"), _pm(20, 1, "Qfp")])]
    p_once = aggregate_survival(fp_once, tier_assignment={})
    p_repeat = aggregate_survival(fp_repeat, tier_assignment={})
    assert p_once["P"] == p_repeat["P"] == {
        "matched": 0, "total": 1, "value": pytest.approx(0.0),
        "ci_lo": pytest.approx(0.0), "ci_hi": pytest.approx(0.7935), "underpowered": True,
    }


def test_survival_precision_predicted_entity_absent_from_gold_is_conservative_fp():
    """A predicted entity never linked by any editor in this article (not in
    the gold set at all, regardless of first-mention convention) always
    counts as FP -- P is a lower bound, dedup does not rescue it."""
    articles = [_article("A", [(0, "Рим", "Q220", 1)], [_pm(0, 1, "Q220"), _pm(20, 1, "Qnotgold")])]
    result = aggregate_survival(articles, tier_assignment={})
    assert result["P"] == {"matched": 1, "total": 2, "value": pytest.approx(0.5),
                            "ci_lo": pytest.approx(0.0945), "ci_hi": pytest.approx(0.9055),
                            "underpowered": True}


def test_survival_r_factorization_identity_matches_direct_product():
    """R == n_disamb_correct / n_gold_entities must equal the literal
    product R_NER.value * R_search.value * A_disamb.value (float tolerance)
    whenever every intermediate stage has a well-defined denominator --
    covering not_extracted / no_candidates / retrieval_miss / candidates_hit
    outcomes together in one corpus."""
    articles = [_article(
        "A",
        [(0, "A1", "Q1", 1), (10, "A2", "Q2", 1), (20, "A3", "Q3", 1), (30, "A4", "Q4", 1)],
        [
            # Q1: not recognized (no overlapping prediction) -- excluded below.
            # Q2: recognized, search-survived, disamb-correct.
            _pm(10, 1, "Q2", candidates=[{"qid": "Q2"}]),
            # Q3: recognized, search-survived, disamb-wrong.
            _pm(20, 1, "Qwrong3", candidates=[{"qid": "Q3"}, {"qid": "Qwrong3"}]),
            # Q4: recognized, search-missed (candidates never carry Q4).
            _pm(30, 1, None, candidates=[{"qid": "Qwrong4"}]),
        ],
    )]
    result = aggregate_survival(articles, tier_assignment={})

    assert result["n_gold_entities"] == 4
    assert (result["R_NER"]["matched"], result["R_NER"]["total"]) == (3, 4)
    # Q2 and Q3 both search-survive (their candidates carry the gold QID);
    # Q4's candidates never do.
    assert (result["R_search"]["matched"], result["R_search"]["total"]) == (2, 3)
    # Among search-survived {Q2, Q3}: Q2 resolves correctly, Q3 doesn't.
    assert (result["A_disamb"]["matched"], result["A_disamb"]["total"]) == (1, 2)

    r_ner, r_search, a_disamb = (
        result["R_NER"]["value"], result["R_search"]["value"], result["A_disamb"]["value"],
    )
    assert result["R"]["value"] == pytest.approx(r_ner * r_search * a_disamb)
    assert result["R"]["matched"] == 1 and result["R"]["total"] == 4
    # No structural divergence in this fixture -- every candidate list is
    # fully populated, so R and R_direct agree exactly.
    assert result["R_direct"] == result["R"]
    assert result["n_resolved_correct_search_miss"] == 0


def test_survival_r_ner_equals_one_minus_not_extracted_rate():
    """R_NER must equal 1 - not_extracted_rate of
    search_miss_analysis.py's outcome classifier run over the SAME inputs
    (its not_extracted outcome is exactly 'no overlapping predicted
    mention') -- reimplemented locally with the identical overlap formula
    rather than importing the script (an ad hoc data/eval/wiki/cleanup/tools
    tool, not a library import target)."""
    def overlaps(a_index, a_len, b_index, b_len):
        return a_index < b_index + b_len and b_index < a_index + a_len

    def not_extracted_rate(gold_tuples, pred_mentions):
        n_not_extracted = 0
        for idx, _surf, _qid, slen in gold_tuples:
            if not any(overlaps(m["index"], m["span_len"], idx, slen) for m in pred_mentions):
                n_not_extracted += 1
        return n_not_extracted / len(gold_tuples)

    gold = [(0, "A1", "Q1", 1), (10, "A2", "Q2", 1), (20, "A3", "Q3", 1)]
    pred = [_pm(0, 1, "Q1", candidates=[{"qid": "Q1"}]), _pm(20, 1, None)]  # Q2 not extracted
    articles = [_article("A", gold, pred)]

    result = aggregate_survival(articles, tier_assignment={})
    rate = not_extracted_rate(gold, pred)
    assert result["R_NER"]["value"] == pytest.approx(1 - rate)
    assert rate == pytest.approx(1 / 3)


def test_survival_structural_divergence_missing_candidates_field_pre_patch_run():
    """A pred.jsonl record predating the 2026-07-10 candidates-field patch
    (key entirely ABSENT, not an explicit empty list) still resolved
    correctly -- R_direct counts it, R (which requires search-survival)
    does not, and the gap is captured exactly by
    n_resolved_correct_search_miss. This is the one real divergence source
    found scoring actual pilot run dirs (see docs/stages/wiki-eval.md)."""
    pre_patch_record = {"index": 0, "span_len": 1, "qid": "Q220"}  # no "candidates" key at all
    articles = [_article("A", [(0, "Рим", "Q220", 1)], [pre_patch_record])]
    result = aggregate_survival(articles, tier_assignment={})

    assert result["R_direct"]["matched"] == 1
    assert result["R"]["matched"] == 0
    assert result["n_resolved_correct_search_miss"] == 1
    assert result["R_direct"]["matched"] == result["R"]["matched"] + result["n_resolved_correct_search_miss"]


def test_survival_multiple_gold_mentions_pool_across_overlapping_predictions():
    """A gold entity with several mentions pools ALL overlapping predicted
    mentions' candidates/resolved-qid together -- one mention supplying
    search-survival evidence and a DIFFERENT one supplying the correct
    resolution both count toward the same gold entity."""
    articles = [_article(
        "A",
        [(0, "Рим", "Q220", 1), (10, "Рима", "Q220", 1)],
        [
            _pm(0, 1, "Qwrong", candidates=[{"qid": "Q220"}, {"qid": "Qwrong"}]),  # search-survives here
            _pm(10, 1, "Q220", candidates=[{"qid": "Qother"}]),  # resolves correctly here
        ],
    )]
    result = aggregate_survival(articles, tier_assignment={})

    assert result["n_gold_entities"] == 1
    assert result["R_search"]["matched"] == 1
    assert result["A_disamb"]["matched"] == 1
    assert result["R"]["matched"] == 1


# ---------------------------------------------------------------------------
# (d) aggregate_survival regression anchor over the FULL committed 100-article
# corpus + tier_assignment.json + anchor_exclusions.json -- no run dir needed,
# this exercises the gold-side filter plumbing alone and must reproduce
# data/eval/wiki/dataset_stats.json's committed cascade exactly.
# ---------------------------------------------------------------------------

EXCLUSIONS_PATH = REPO / "data/eval/wiki/anchor_exclusions.json"


@pytest.mark.skipif(not GT_PATH.exists(), reason="gold corpus not present in this checkout")
@pytest.mark.skipif(not TIER_PATH.exists(), reason="tier assignment not present in this checkout")
@pytest.mark.skipif(not EXCLUSIONS_PATH.exists(), reason="anchor exclusions not present in this checkout")
def test_survival_gold_cascade_matches_dataset_stats_json(tier_assignment):
    excl_data = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    excluded = {
        (e["title"], e["token_index"], e["anchor_text"], e["qid"], e["span_len"])
        for e in excl_data["exclusions"]
    }
    articles = [
        {"title": rec["title"], "gt_tuples": [tuple(t) for t in rec["gt_tuples"]], "pred_mentions": []}
        for rec in (json.loads(l) for l in GT_PATH.read_text(encoding="utf-8").splitlines())
    ]
    result = aggregate_survival(articles, tier_assignment=tier_assignment, excluded_gold_identities=excluded)

    # data/eval/wiki/dataset_stats.json cascade: mentions raw=7658 t2=6894 final=6573;
    # entities raw=5879 t2=5351 final=5061.
    assert result["n_gold_mentions_dropped_by_tier"] == 7658 - 6894
    assert result["n_gold_mentions_dropped_by_exclusion"] == 6894 - 6573
    assert result["n_gold_entities"] == 5061
