"""Metrics for the terminology tournament — definitions corrected per verify-spec.

Grounding: QID accuracy + macro-F1 over {green,yellow,red}; groundable-coverage
and red-accuracy reported *separately* (never conflated). Pairing: verdict-F1
over {green,yellow,red} on difficulty≠red terms only + null-accuracy for red
terms reported separately; recommended accuracy scored only where the verdict is
correct. All pure functions over plain dicts so the CLI can feed either strategy.
"""
from __future__ import annotations

from collections import defaultdict

VERDICTS = ("green", "yellow", "red")


def wilson_ci(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion — honest CI on small-n
    accuracy (spec §8: single-digit term counts move the golden-99 accuracy by
    multiple points, so a plain point estimate without an interval is dishonest).

    ``total=0`` returns the maximally uninformative interval ``(0.0, 1.0)``.
    """
    if total == 0:
        return (0.0, 1.0)
    p = correct / total
    denom = 1 + z * z / total
    center = p + z * z / (2 * total)
    margin = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return (round(max(0.0, lo), 4), round(min(1.0, hi), 4))


def _f1_parts(y_true: list[str], y_pred: list[str], label: str) -> tuple[float, float, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def macro_f1(y_true: list[str], y_pred: list[str], labels=VERDICTS) -> dict:
    per = {lab: dict(zip(("precision", "recall", "f1"), _f1_parts(y_true, y_pred, lab))) for lab in labels}
    present = [lab for lab in labels if lab in y_true]
    macro = sum(per[lab]["f1"] for lab in present) / len(present) if present else 0.0
    return {"macro_f1": round(macro, 4), "per_label": {k: {m: round(v, 4) for m, v in d.items()} for k, d in per.items()}}


def confusion(y_true: list[str], y_pred: list[str], labels=VERDICTS) -> dict:
    mat = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in mat and p in mat[t]:
            mat[t][p] += 1
    return mat


def latency_stats(latencies: list[float]) -> dict:
    if not latencies:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0, "n": 0}
    s = sorted(latencies)
    def pct(q: float) -> float:
        return round(s[min(len(s) - 1, int(q * len(s)))], 1)
    return {"p50": pct(0.50), "p95": pct(0.95), "max": round(s[-1], 1), "n": len(s)}


def score_grounding(rows: list[dict]) -> dict:
    """rows: {gold_qid, gold_difficulty, pred_qid, pred_difficulty, category, latency_ms, n_api_calls}."""
    yt = [r["gold_difficulty"] for r in rows]
    yp = [r["pred_difficulty"] for r in rows]

    groundable = [r for r in rows if r["gold_difficulty"] in ("green", "yellow")]
    qid_hits = sum(1 for r in groundable if r.get("pred_qid") and r["pred_qid"] == r.get("gold_qid"))
    reds = [r for r in rows if r["gold_difficulty"] == "red"]

    pred_groundable = sum(1 for r in rows if r["pred_difficulty"] in ("green", "yellow"))
    return {
        "n": len(rows),
        "class_distribution": {v: yt.count(v) for v in VERDICTS},
        "qid_accuracy_on_groundable": round(qid_hits / len(groundable), 4) if groundable else None,
        "difficulty": macro_f1(yt, yp),
        "difficulty_confusion": confusion(yt, yp),
        "groundable_coverage": round(pred_groundable / len(rows), 4) if rows else 0.0,
        "red_accuracy": round(sum(1 for r in reds if r["pred_difficulty"] == "red") / len(reds), 4) if reds else None,
        "latency_ms": latency_stats([r.get("latency_ms", 0.0) for r in rows]),
        "avg_api_calls": round(sum(r.get("n_api_calls", 0) for r in rows) / len(rows), 2) if rows else 0.0,
        "per_category": _per_category(rows, yt, yp),
    }


def score_pairing(rows: list[dict]) -> dict:
    """rows: {gold_difficulty, gold_pair, gold_recommended, pred_pair, pred_recommended, gold_verdict_correct?, category, latency_ms}.

    Verdict-F1 is computed on difficulty≠red terms only. Red terms must have
    pred_pair is None; null-accuracy measures that separately.
    """
    non_red = [r for r in rows if r["gold_difficulty"] != "red"]
    reds = [r for r in rows if r["gold_difficulty"] == "red"]
    yt = [r["gold_pair"] for r in non_red]
    yp = [(r.get("pred_pair") or "red") for r in non_red]

    # recommended accuracy only where the verdict was predicted correctly and gold expects one
    rec_scope = [r for r in non_red if r.get("pred_pair") == r["gold_pair"] and r.get("gold_recommended")]
    rec_hits = sum(1 for r in rec_scope if _norm(r.get("pred_recommended")) == _norm(r.get("gold_recommended")))

    null_ok = sum(1 for r in reds if r.get("pred_pair") is None)
    return {
        "n_non_red": len(non_red),
        "class_distribution_non_red": {v: yt.count(v) for v in VERDICTS},
        "verdict": macro_f1(yt, yp),
        "verdict_confusion": confusion(yt, yp),
        "null_accuracy_on_red": round(null_ok / len(reds), 4) if reds else None,
        "recommended_accuracy": round(rec_hits / len(rec_scope), 4) if rec_scope else None,
        "recommended_scored_n": len(rec_scope),
        "latency_ms": latency_stats([r.get("latency_ms", 0.0) for r in non_red]),
        "per_category": _per_category(non_red, yt, yp),
    }


def extraction_prf(extracted: set[str], gold: set[str]) -> dict:
    tp = len(extracted & gold)
    prec = tp / len(extracted) if extracted else 0.0
    rec = tp / len(gold) if gold else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "tp": tp, "n_extracted": len(extracted), "n_gold": len(gold),
            "missed": sorted(gold - extracted), "spurious": sorted(extracted - gold)}


def select_winner(by_strategy: dict[str, dict], key_accuracy: str) -> dict:
    """Explicit rule: higher accuracy → higher macro-F1 → fewer API calls → lower p50 latency."""
    def sort_key(item):
        name, m = item
        acc = m.get(key_accuracy) or 0.0
        f1 = m.get("difficulty", m.get("verdict", {})).get("macro_f1", 0.0)
        api = m.get("avg_api_calls", 0.0)
        lat = m.get("latency_ms", {}).get("p50", 0.0)
        return (-acc, -f1, api, lat)
    ranked = sorted(by_strategy.items(), key=sort_key)
    return {"winner": ranked[0][0], "ranking": [n for n, _ in ranked],
            "rule": "max accuracy → max macro-F1 → min avg_api_calls → min p50 latency"}


def _per_category(rows, yt, yp) -> dict:
    buckets = defaultdict(lambda: {"y": [], "p": []})
    for r, t, p in zip(rows, yt, yp):
        b = buckets[r.get("category") or "other"]
        b["y"].append(t)
        b["p"].append(p)
    return {cat: {"n": len(d["y"]), "macro_f1": macro_f1(d["y"], d["p"])["macro_f1"]} for cat, d in buckets.items()}


def _norm(s):
    return (s or "").strip().lower()
