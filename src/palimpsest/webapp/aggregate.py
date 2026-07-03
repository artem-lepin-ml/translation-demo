"""Document/paragraph aggregate (rev-4 contract §3).

ONE helper used by both seed and ``/evaluate`` so the baseline and the latest
aggregate are always computed the same way. Each criterion is normalised to its
own [scaleMin, scaleMax] before weighting — criteria may have different scales,
so a raw weighted sum would be incomparable.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _get(c: Any, key: str) -> Any:
    # works for dict, sqlite3.Row (subscript by column), and dataclasses/objects
    try:
        return c[key]
    except (TypeError, KeyError, IndexError):
        return getattr(c, key)


def compute_aggregate(
    values_by_criterion: Mapping[str, float],
    criteria: Sequence[Any],
) -> tuple[float, str]:
    """Return ``(aggregate_0_to_10, criteria_key)``.

    ``criteria`` are the criterion rows (need id, scale_min, scale_max, weight,
    enabled). The caller must pass a ``value`` for every enabled criterion it
    wants counted — on a partial re-evaluate, substitute the latest available
    score for criteria not evaluated in this call, so baseline and latest stay
    comparable. ``criteria_key`` is the sorted set of enabled criterion ids,
    used by the UI to flag a changed criterion set.
    """
    enabled = [c for c in criteria if _get(c, "enabled")]
    num = den = 0.0
    for c in enabled:
        cid = _get(c, "id")
        if cid not in values_by_criterion:
            continue
        lo, hi = float(_get(c, "scale_min")), float(_get(c, "scale_max"))
        norm = (float(values_by_criterion[cid]) - lo) / (hi - lo) if hi > lo else 0.0
        w = float(_get(c, "weight"))
        num += norm * w
        den += w
    aggregate = round(num / den * 10, 2) if den else 0.0
    criteria_key = ",".join(sorted(str(_get(c, "id")) for c in enabled))
    return aggregate, criteria_key
