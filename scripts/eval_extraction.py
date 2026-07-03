#!/usr/bin/env python3
"""Recall/precision of extraction strategies vs a non-circular gold, split by case.

Gold (data/seed/terminology_gold.jsonl) is built by scripts/merge_goldens.py from
three hand-authored sources cross-checked against live Wikidata — no code path
reads extracted_surfaces.json when assembling it, so scoring against it here is
not circular.

Usage (from the worktree root, with PYTHONPATH=src):
  python scripts/eval_extraction.py
  python scripts/eval_extraction.py --surfaces data/seed/extracted_surfaces.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.eval_harness import extraction_prf
from palimpsest.terminology.extract import _capitalized_surfaces, deterministic_surfaces

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data/seed/terminology_gold.jsonl"
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
METRICS_OUT = ROOT / "reports/terminology/extraction_metrics.json"

CASES = ("all", "lowercase", "uppercase")


def _load_gold() -> dict[int, set[str]]:
    gold: dict[int, set[str]] = {}
    for line in GOLD.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        gold.setdefault(row["paragraph_id"], set()).add(row["surface"])
    return gold


def _load_sources() -> dict[int, str]:
    sources: dict[int, str] = {}
    for line in SEED.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        sources[row["id"]] = row["source"]
    return sources


def _load_llm_surfaces(path: Path) -> dict[int, set[str]]:
    """Load a persisted {paragraph_id, surfaces:[{surface,category}]} file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, set[str]] = {}
    for para in data:
        out[para["paragraph_id"]] = {s["surface"] for s in para.get("surfaces", [])}
    return out


def _split(surfaces: set[str]) -> tuple[set[str], set[str]]:
    low = {s for s in surfaces if s[:1].islower()}
    up = surfaces - low
    return low, up


def _micro_pool(per_para: dict[int, set[str]]) -> set[tuple[int, str]]:
    """Union of (paragraph_id, surface) pairs across paragraphs (per-paragraph pooling)."""
    pool: set[tuple[int, str]] = set()
    for pid, surfaces in per_para.items():
        for s in surfaces:
            pool.add((pid, s))
    return pool


def _score_extractor(per_para: dict[int, set[str]], gold: dict[int, set[str]]) -> dict:
    extracted_pool = _micro_pool(per_para)
    gold_pool = _micro_pool(gold)

    def _case_pool(pool: set[tuple[int, str]], want_lower: bool | None) -> set[tuple[int, str]]:
        if want_lower is None:
            return pool
        return {(pid, s) for pid, s in pool if s[:1].islower() == want_lower}

    result: dict[str, dict] = {}
    for case, want_lower in (("all", None), ("lowercase", True), ("uppercase", False)):
        ex = _case_pool(extracted_pool, want_lower)
        go = _case_pool(gold_pool, want_lower)
        result[case] = extraction_prf(ex, go)
    return result


def build_metrics(surfaces_path: str | None) -> dict:
    gold = _load_gold()
    sources = _load_sources()
    pids = sorted(gold)

    old_caps = {pid: {s["surface"] for s in _capitalized_surfaces(sources[pid])} for pid in pids}
    deterministic = {pid: {s["surface"] for s in deterministic_surfaces(sources[pid])} for pid in pids}

    metrics = {
        "old_caps": _score_extractor(old_caps, gold),
        "deterministic": _score_extractor(deterministic, gold),
    }

    if surfaces_path:
        llm = _load_llm_surfaces(Path(surfaces_path))
        llm = {pid: llm.get(pid, set()) for pid in pids}
        metrics["llm"] = _score_extractor(llm, gold)

    return metrics


def _print_table(metrics: dict) -> None:
    header = f"{'extractor':<14}{'case':<12}{'recall':>8}{'precision':>11}{'f1':>8}"
    print(header)
    print("-" * len(header))
    for extractor, by_case in metrics.items():
        for case in CASES:
            m = by_case[case]
            print(f"{extractor:<14}{case:<12}{m['recall']:>8.4f}{m['precision']:>11.4f}{m['f1']:>8.4f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--surfaces", default=None,
                     help="path to a persisted extracted_surfaces.json to score as 'llm' (optional; skipped if omitted)")
    args = ap.parse_args()

    metrics = build_metrics(args.surfaces)
    _print_table(metrics)

    METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)
    METRICS_OUT.write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {METRICS_OUT.relative_to(ROOT)}")

    det_low_recall = metrics["deterministic"]["lowercase"]["recall"]
    caps_low_recall = metrics["old_caps"]["lowercase"]["recall"]
    print(f"\nSC1 check: deterministic lowercase recall = {det_low_recall:.4f} "
          f"({'>=' if det_low_recall >= 0.5 else '<'} 0.5 target); "
          f"old_caps lowercase recall = {caps_low_recall:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
