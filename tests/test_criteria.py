from palimpsest.evaluation.criteria import CRITERIA, consensus


def test_weights_match_presentation():
    weights = {c.key: c.weight for c in CRITERIA}
    assert weights == {
        "accuracy": 2.0,
        "terminology": 1.5,
        "consistency": 1.5,
        "fluency": 1.0,
        "style": 1.0,
        "culture": 1.0,
    }


def test_consensus_matches_weighted_average():
    scores = {"accuracy": 5, "terminology": 4, "consistency": 4,
              "fluency": 3, "style": 3, "culture": 3}
    total_weight = 2.0 + 1.5 + 1.5 + 1.0 + 1.0 + 1.0
    expected = (5 * 2.0 + 4 * 1.5 + 4 * 1.5 + 3 * 1.0 + 3 * 1.0 + 3 * 1.0) / total_weight
    assert abs(consensus(scores) - expected) < 1e-9
