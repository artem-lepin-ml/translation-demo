"""compute_aggregate: normalization across heterogeneous scales + criteria_key."""
from __future__ import annotations

from palimpsest.webapp.aggregate import compute_aggregate


def crit(cid, lo, hi, w, enabled=1):
    return {"id": cid, "scale_min": lo, "scale_max": hi, "weight": w, "enabled": enabled}


def test_normalization_makes_scales_comparable():
    crits = [crit("a", 1, 10, 1.0), crit("b", 0, 100, 1.0)]
    # both at their max → each normalises to 1.0 → aggregate 10.0 despite different scales
    agg, key = compute_aggregate({"a": 10, "b": 100}, crits)
    assert agg == 10.0
    assert key == "a,b"
    # both at their min → 0
    assert compute_aggregate({"a": 1, "b": 0}, crits)[0] == 0.0


def test_weighting():
    crits = [crit("a", 0, 10, 3.0), crit("b", 0, 10, 1.0)]
    # a=10(→1.0) weight 3, b=0(→0) weight 1 → (3*1+1*0)/4 *10 = 7.5
    assert compute_aggregate({"a": 10, "b": 0}, crits)[0] == 7.5


def test_disabled_excluded_from_key_and_sum():
    crits = [crit("a", 1, 10, 1.0), crit("z", 1, 10, 1.0, enabled=0)]
    agg, key = compute_aggregate({"a": 10, "z": 1}, crits)
    assert key == "a"          # disabled criterion not in key
    assert agg == 10.0         # nor in the weighted sum
