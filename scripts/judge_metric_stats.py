#!/usr/bin/env python3
"""Spearman/Kendall analysis of judge scores vs. automatic metrics on the
vendored BOUQUET evaluation outputs, plus a built-in reproduction check
against a colleague's previously reported paragraph-level Spearman table.

Per system (of the 4 vendored under --eval-root):
  1. Paragraph-level Spearman rho for each judge criterion (accuracy, fluency,
     style) against each metric (MetricX ref-based, MetricX QE/reference-free,
     COMET), with n reported per cell.
  2. Judge-score tie statistics per criterion: modal value share, % of mass on
     {9, 10}, distinct-value count.
  3. Paired refinement deltas (initial -> refined, same paragraph index):
     mean delta per judge criterion / metric, sign-agreement rate between
     delta-judge and the "improvement-oriented" metric delta (-delta MetricX,
     +delta COMET) on pairs where both deltas are non-zero, and Kendall
     tau-b on the raw (unoriented) deltas.
  4. A validation section comparing the ref-based- and QE-metric Spearman
     numbers above against a colleague's screenshot values, to confirm which
     MetricX variant his "MetX" column used.

Vendored data (read-only): external/gse-translation/data/bouquet/evaluation/
<system>/{scores.jsonl, metricx/scores.jsonl, metricx/scores_wo_ref.jsonl,
comet/scores.json}. See docs/superpowers/specs/2026-06-30-demo-contracts.md
for the demo's own DB contract -- unrelated to this vendored research data.

Requires numpy + scipy, not project dependencies (research one-off): run via
    uv run --with scipy scripts/judge_metric_stats.py
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_ROOT = ROOT / "external/gse-translation/data/bouquet/evaluation"
DEFAULT_OUT = ROOT / "reports/bouquet/judge_metric_stats.json"

CRITERIA = ("accuracy", "fluency", "style")
# MetricX is an error-style metric (lower = better); COMET is quality-style
# (higher = better). sign=-1/+1 is the "improvement direction" for each metric,
# used only for the sign-agreement stat -- correlations/deltas elsewhere are
# always reported on the raw, unflipped values.
METRICS = (
    ("metricx_ref", -1),
    ("metricx_qe", -1),
    ("comet", +1),
)

SYSTEM_LABELS = {
    "qwen-27b-bouquet": "Qwen3.6-27B",
    "qwen-27b-bouquet-refined": "Qwen3.6-27B Refined",
    "translate-gemma-bouquet": "Translate Gemma",
    "translate-gemma-bouquet-refined": "Translate Gemma Refined",
}
REFINEMENT_PAIRS = (
    ("qwen-27b-bouquet", "qwen-27b-bouquet-refined"),
    ("translate-gemma-bouquet", "translate-gemma-bouquet-refined"),
)

# Colleague's screenshot: paragraph-level Spearman rho, (metricx, comet) per
# criterion, keyed by SYSTEM_LABELS value. Used only to validate our reading
# of the vendored data -- not a claim about the "true" correlation.
REFERENCE_SPEARMAN: dict[str, dict[str, tuple[float, float]]] = {
    "Translate Gemma": {
        "accuracy": (-0.1285, 0.1719),
        "fluency": (-0.1104, 0.1451),
        "style": (-0.3061, 0.2851),
    },
    "Translate Gemma Refined": {
        "accuracy": (-0.1255, 0.1094),
        "fluency": (-0.0963, 0.1854),
        "style": (-0.0589, 0.1382),
    },
    "Qwen3.6-27B": {
        "accuracy": (0.0185, -0.069),
        "fluency": (-0.0798, 0.1064),
        "style": (-0.0614, 0.1721),
    },
    "Qwen3.6-27B Refined": {
        "accuracy": (-0.0036, 0.1331),
        "fluency": (-0.0686, 0.0682),
        "style": (-0.0506, 0.1727),
    },
}

# Colleague's headline table: system-level means, keyed the same way.
REFERENCE_HEADLINE: dict[str, dict[str, float]] = {
    "Translate Gemma": dict(accuracy=9.7, fluency=9.58, style=9.53,
                             metricx_ref=2.41, metricx_qe=3.55, comet=0.736),
    "Translate Gemma Refined": dict(accuracy=9.91, fluency=9.76, style=9.67,
                                     metricx_ref=2.42, metricx_qe=3.58, comet=0.7361),
    "Qwen3.6-27B": dict(accuracy=9.84, fluency=9.92, style=9.7,
                         metricx_ref=2.696, metricx_qe=3.79, comet=0.7235),
    "Qwen3.6-27B Refined": dict(accuracy=9.91, fluency=9.93, style=9.76,
                                 metricx_ref=2.686, metricx_qe=3.77, comet=0.724),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@dataclass
class SystemData:
    name: str
    label: str
    accuracy: np.ndarray
    fluency: np.ndarray
    style: np.ndarray
    metricx_ref: np.ndarray
    metricx_qe: np.ndarray
    comet: np.ndarray

    @property
    def n(self) -> int:
        return len(self.accuracy)

    def judge(self, criterion: str) -> np.ndarray:
        return getattr(self, criterion)

    def metric(self, name: str) -> np.ndarray:
        return getattr(self, name)


def load_system(eval_root: Path, name: str) -> SystemData:
    """Load one system's rollup + per-metric files, asserting index alignment.

    ``scores.jsonl``'s own ``metricx`` field is dropped in favour of reading
    ``metricx/scores.jsonl``'s ``prediction`` directly -- confirmed identical
    per-row (both trace back to the same ref-based MetricX run), but reading
    the metric file directly keeps the ref-based/QE (wo_ref) comparison
    symmetric and avoids trusting an unlabelled rollup column.
    """
    sys_dir = eval_root / name
    rollup = read_jsonl(sys_dir / "scores.jsonl")
    metricx_ref_rows = read_jsonl(sys_dir / "metricx" / "scores.jsonl")
    metricx_qe_rows = read_jsonl(sys_dir / "metricx" / "scores_wo_ref.jsonl")
    with (sys_dir / "comet" / "scores.json").open(encoding="utf-8") as fh:
        comet_data = json.load(fh)
    comet_scores = comet_data["paragraph_scores"]

    lengths = {
        "scores.jsonl": len(rollup),
        "metricx/scores.jsonl": len(metricx_ref_rows),
        "metricx/scores_wo_ref.jsonl": len(metricx_qe_rows),
        "comet/scores.json:paragraph_scores": len(comet_scores),
    }
    if len(set(lengths.values())) != 1:
        raise ValueError(f"{name}: misaligned per-file row counts: {lengths}")

    def col(rows: list[dict[str, Any]], key: str) -> np.ndarray:
        values = [row.get(key) if row.get(key) is not None else np.nan for row in rows]
        return np.array(values, dtype=float)

    return SystemData(
        name=name,
        label=SYSTEM_LABELS[name],
        accuracy=col(rollup, "accuracy"),
        fluency=col(rollup, "fluency"),
        style=col(rollup, "style"),
        metricx_ref=col(metricx_ref_rows, "prediction"),
        metricx_qe=col(metricx_qe_rows, "prediction"),
        comet=np.array(comet_scores, dtype=float),
    )


def _paired_valid(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mask = ~np.isnan(a) & ~np.isnan(b)
    return a[mask], b[mask]


def spearman_cell(judge: np.ndarray, metric: np.ndarray) -> dict[str, Any]:
    """Paragraph-level Spearman rho, dropping rows with a null/missing judge
    score (or, defensively, a null metric value). scipy's default tie handling
    (average ranks) is used throughout -- see the validation section for the
    reconciliation against the colleague's numbers."""
    j, m = _paired_valid(judge, metric)
    n = len(j)
    if n < 2:
        return {"rho": None, "n": n}
    rho, _p = stats.spearmanr(j, m)
    return {"rho": round(float(rho), 4), "n": int(n)}


def tie_stats(values: np.ndarray) -> dict[str, Any]:
    finite = values[~np.isnan(values)]
    n = int(finite.size)
    if n == 0:
        return {"n": 0, "distinct_values": 0, "modal_value": None,
                "modal_share": None, "share_9_10": None, "mean": None}
    vals, counts = np.unique(finite, return_counts=True)
    modal_idx = int(np.argmax(counts))
    return {
        "n": n,
        "distinct_values": int(vals.size),
        "modal_value": float(vals[modal_idx]),
        "modal_share": round(float(counts[modal_idx] / n), 4),
        "share_9_10": round(float(np.isin(finite, [9, 10]).sum() / n), 4),
        "mean": round(float(finite.mean()), 4),
    }


def paired_deltas(initial: SystemData, refined: SystemData) -> dict[str, Any]:
    """Paragraph-index-aligned initial->refined deltas: mean shift per judge
    criterion/metric, sign-agreement rate (oriented so +1 always means "the
    metric moved the same direction as an improving translation"), and
    Kendall tau-b on the raw, unoriented deltas."""
    if initial.n != refined.n:
        raise ValueError(f"{initial.name} vs {refined.name}: paragraph count mismatch "
                          f"({initial.n} vs {refined.n}) -- cannot pair by index")

    metric_deltas = {name: refined.metric(name) - initial.metric(name) for name, _sign in METRICS}
    judge_deltas = {c: refined.judge(c) - initial.judge(c) for c in CRITERIA}

    result: dict[str, Any] = {
        "pair": f"{initial.label} -> {refined.label}",
        "n": initial.n,
        "mean_delta_judge": {c: round(float(np.nanmean(d)), 4) for c, d in judge_deltas.items()},
        "mean_delta_metric": {
            name: round(float(np.nanmean(d)), 4) for name, d in metric_deltas.items()
        },
        "sign_agreement": {},
        "kendall_tau_b": {},
    }
    for criterion in CRITERIA:
        dj = judge_deltas[criterion]
        result["sign_agreement"][criterion] = {}
        result["kendall_tau_b"][criterion] = {}
        for metric_name, sign in METRICS:
            dm = metric_deltas[metric_name]
            mask = ~np.isnan(dj) & ~np.isnan(dm)
            dj_v, dm_v = dj[mask], dm[mask]

            oriented = sign * dm_v
            nonzero = (dj_v != 0) & (oriented != 0)
            agreement = (
                float(np.mean(np.sign(dj_v[nonzero]) == np.sign(oriented[nonzero])))
                if nonzero.sum() else None
            )
            result["sign_agreement"][criterion][metric_name] = {
                "agreement_rate": round(agreement, 4) if agreement is not None else None,
                "n_nonzero_both": int(nonzero.sum()),
                "n_paired": int(mask.sum()),
            }

            tau = float("nan")
            if len(dj_v) >= 2 and np.any(dj_v != dj_v[0]) and np.any(dm_v != dm_v[0]):
                tau, _p = stats.kendalltau(dj_v, dm_v)
            tau_out = round(float(tau), 4) if tau == tau else None
            result["kendall_tau_b"][criterion][metric_name] = tau_out
    return result


def build_correlation_table(systems: dict[str, SystemData]) -> dict[str, dict[str, dict[str, Any]]]:
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for sd in systems.values():
        table[sd.label] = {}
        for criterion in CRITERIA:
            judge = sd.judge(criterion)
            table[sd.label][criterion] = {
                metric_name: spearman_cell(judge, sd.metric(metric_name))
                for metric_name, _sign in METRICS
            }
    return table


def build_headline(systems: dict[str, SystemData]) -> dict[str, dict[str, Any]]:
    headline: dict[str, dict[str, Any]] = {}
    for sd in systems.values():
        headline[sd.label] = {
            "judge": {c: tie_stats(sd.judge(c)) for c in CRITERIA},
            "metricx_ref_mean": round(float(np.nanmean(sd.metricx_ref)), 4),
            "metricx_qe_mean": round(float(np.nanmean(sd.metricx_qe)), 4),
            "comet_mean": round(float(np.nanmean(sd.comet)), 4),
        }
    return headline


def build_validation(corr_table: dict[str, dict[str, dict[str, Any]]],
                      headline: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare our computed Spearman/headline numbers against the colleague's
    screenshot, per metric variant, to determine which MetricX column
    ("ref"-based vs. "qe"/wo_ref) his reported "MetX" used."""
    variant_residuals: dict[str, list[float]] = {"metricx_ref": [], "metricx_qe": []}
    cells: list[dict[str, Any]] = []
    for label, targets in REFERENCE_SPEARMAN.items():
        for criterion, (target_metx, target_comet) in targets.items():
            computed = corr_table[label][criterion]
            resid_ref = computed["metricx_ref"]["rho"] - target_metx
            resid_qe = computed["metricx_qe"]["rho"] - target_metx
            resid_comet = computed["comet"]["rho"] - target_comet
            variant_residuals["metricx_ref"].append(resid_ref)
            variant_residuals["metricx_qe"].append(resid_qe)
            cells.append({
                "system": label, "criterion": criterion,
                "target_metx": target_metx, "computed_metricx_ref": computed["metricx_ref"]["rho"],
                "resid_metricx_ref": round(resid_ref, 4),
                "computed_metricx_qe": computed["metricx_qe"]["rho"],
                "resid_metricx_qe": round(resid_qe, 4),
                "target_comet": target_comet, "computed_comet": computed["comet"]["rho"],
                "resid_comet": round(resid_comet, 4),
            })

    mean_abs_resid = {
        variant: round(float(np.mean(np.abs(resids))), 4)
        for variant, resids in variant_residuals.items()
    }
    best_variant = min(mean_abs_resid, key=lambda v: mean_abs_resid[v])

    headline_cells: list[dict[str, Any]] = []
    for label, targets in REFERENCE_HEADLINE.items():
        h = headline[label]
        for criterion in CRITERIA:
            headline_cells.append({
                "system": label, "field": criterion,
                "target": targets[criterion], "computed": h["judge"][criterion]["mean"],
                "resid": round(h["judge"][criterion]["mean"] - targets[criterion], 4),
            })
        metric_fields = (
            ("metricx_ref", "metricx_ref_mean"),
            ("metricx_qe", "metricx_qe_mean"),
            ("comet", "comet_mean"),
        )
        for field, key in metric_fields:
            headline_cells.append({
                "system": label, "field": field,
                "target": targets[field], "computed": h[key],
                "resid": round(h[key] - targets[field], 4),
            })

    return {
        "spearman_cells": cells,
        "mean_abs_residual_by_metricx_variant": mean_abs_resid,
        "best_matching_metricx_variant": best_variant,
        "headline_cells": headline_cells,
    }


def print_report(corr_table: dict[str, dict[str, dict[str, Any]]],
                  headline: dict[str, dict[str, Any]],
                  deltas: list[dict[str, Any]],
                  validation: dict[str, Any]) -> None:
    print("=" * 100)
    print("PARAGRAPH-LEVEL SPEARMAN: judge criterion x metric (n per cell in parens)")
    print("=" * 100)
    for label, per_criterion in corr_table.items():
        print(f"\n{label}")
        print(f"  {'criterion':<10}{'metricx_ref':>16}{'metricx_qe':>16}{'comet':>16}")
        for criterion, cells in per_criterion.items():
            row = f"  {criterion:<10}"
            for metric_name in ("metricx_ref", "metricx_qe", "comet"):
                c = cells[metric_name]
                row += f"{c['rho']:>+10.4f}(n={c['n']:>3}) "
            print(row)

    print("\n" + "=" * 100)
    print("TIE STATS & HEADLINE MEANS")
    print("=" * 100)
    for label, h in headline.items():
        print(f"\n{label}")
        for criterion in CRITERIA:
            t = h["judge"][criterion]
            print(f"  {criterion:<10} mean={t['mean']:.4f}  modal={t['modal_value']} "
                  f"(share {t['modal_share']:.2%})  %9-10={t['share_9_10']:.2%}  "
                  f"distinct={t['distinct_values']}")
        print(f"  metricx_ref mean={h['metricx_ref_mean']:.4f}   "
              f"metricx_qe mean={h['metricx_qe_mean']:.4f}   comet mean={h['comet_mean']:.4f}")

    print("\n" + "=" * 100)
    print("PAIRED REFINEMENT DELTAS (initial -> refined)")
    print("=" * 100)
    for d in deltas:
        print(f"\n{d['pair']} (n={d['n']})")
        print(f"  mean delta judge:  {d['mean_delta_judge']}")
        print(f"  mean delta metric: {d['mean_delta_metric']}")
        for criterion in CRITERIA:
            print(f"  {criterion}:")
            for metric_name, _sign in METRICS:
                sa = d["sign_agreement"][criterion][metric_name]
                tau = d["kendall_tau_b"][criterion][metric_name]
                print(f"    vs {metric_name:<12} sign_agreement={sa['agreement_rate']} "
                      f"(n_nonzero_both={sa['n_nonzero_both']}/{sa['n_paired']})   tau_b={tau}")

    print("\n" + "=" * 100)
    print("VALIDATION vs. colleague's screenshot (paragraph-level Spearman)")
    print("=" * 100)
    print(f"  {'system':<24}{'criterion':<10}{'target':>9}{'metricx_ref':>13}{'resid_ref':>11}"
          f"{'metricx_qe':>13}{'resid_qe':>10}{'target_cmt':>11}{'comet':>9}{'resid_cmt':>11}")
    for c in validation["spearman_cells"]:
        print(f"  {c['system']:<24}{c['criterion']:<10}{c['target_metx']:>9.4f}"
              f"{c['computed_metricx_ref']:>13.4f}{c['resid_metricx_ref']:>11.4f}"
              f"{c['computed_metricx_qe']:>13.4f}{c['resid_metricx_qe']:>10.4f}"
              f"{c['target_comet']:>11.4f}{c['computed_comet']:>9.4f}{c['resid_comet']:>11.4f}")
    mean_abs = validation["mean_abs_residual_by_metricx_variant"]
    print(f"\n  mean |residual| using metricx_ref as MetX: {mean_abs['metricx_ref']:.4f}")
    print(f"  mean |residual| using metricx_qe  as MetX: {mean_abs['metricx_qe']:.4f}")
    print(f"  => best-matching MetricX variant: {validation['best_matching_metricx_variant']}")

    print("\n  headline means vs. colleague's table:")
    print(f"  {'system':<24}{'field':<12}{'target':>9}{'computed':>10}{'resid':>9}")
    for c in validation["headline_cells"]:
        print(f"  {c['system']:<24}{c['field']:<12}{c['target']:>9.4f}"
              f"{c['computed']:>10.4f}{c['resid']:>9.4f}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT,
                     help="root holding <system>/{scores.jsonl,metricx/,comet/} "
                          "(default: %(default)s)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                     help="JSON output path (default: %(default)s)")
    args = ap.parse_args()

    systems = {name: load_system(args.eval_root, name) for name in SYSTEM_LABELS}

    corr_table = build_correlation_table(systems)
    headline = build_headline(systems)
    deltas = [
        paired_deltas(systems[initial], systems[refined]) for initial, refined in REFINEMENT_PAIRS
    ]
    validation = build_validation(corr_table, headline)

    print_report(corr_table, headline, deltas, validation)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "eval_root": str(args.eval_root),
        "systems": {sd.label: sd.name for sd in systems.values()},
        "spearman": corr_table,
        "headline": headline,
        "refinement_deltas": deltas,
        "validation_vs_colleague_screenshot": validation,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
