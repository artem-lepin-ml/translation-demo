#!/usr/bin/env python3
"""Build consolidated reports/<judge>.jsonl for any judge subdir missing one.

Scans `data/pilot/evaluation/<run>/<variant>/` for directories that look
like a per-judge bucket (contain all 5 `<criterion>_scores.jsonl` files)
but have no corresponding `reports/<judge>.jsonl`. For each match, joins
the criterion files with `comparison.jsonl` and writes the consolidated
form the viewer reads.

Idempotent: skips judges whose report already exists. Safe to re-run
after every data sync from collaborators.

Usage:
    uv run python scripts/03_build_judge_reports.py
    uv run python scripts/03_build_judge_reports.py --force  # rebuild all
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CRITERIA = ("accuracy", "terminology", "fluency", "cultural", "style")
EVAL_ROOT = Path(__file__).resolve().parents[1] / "data/pilot/evaluation"


def _has_all_criterion_files(judge_dir: Path) -> bool:
    return all((judge_dir / f"{c}_scores.jsonl").is_file() for c in CRITERIA)


def _find_pending(force: bool) -> list[tuple[Path, str]]:
    """Yield (variant_dir, judge) pairs that need a consolidated report."""
    pending: list[tuple[Path, str]] = []
    if not EVAL_ROOT.is_dir():
        return pending
    for run_dir in sorted(p for p in EVAL_ROOT.iterdir() if p.is_dir()):
        for variant_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            if not (variant_dir / "comparison.jsonl").is_file():
                continue
            for child in sorted(variant_dir.iterdir()):
                if not child.is_dir() or child.name == "reports":
                    continue
                if not _has_all_criterion_files(child):
                    continue
                report = variant_dir / "reports" / f"{child.name}.jsonl"
                if report.is_file() and not force:
                    continue
                pending.append((variant_dir, child.name))
    return pending


def _build_report(variant_dir: Path, judge: str) -> Path:
    judge_dir = variant_dir / judge
    out_path = variant_dir / "reports" / f"{judge}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pairs: dict[int, tuple[str, str]] = {}
    with (variant_dir / "comparison.jsonl").open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            pairs[row["id"]] = (row.get("source", ""), row.get("translated", ""))

    per_crit: dict[str, dict[int, tuple[int | None, dict | None]]] = {}
    all_ids: set[int] = set()
    for crit in CRITERIA:
        per_crit[crit] = {}
        with (judge_dir / f"{crit}_scores.jsonl").open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                per_crit[crit][row["id"]] = (row.get("score"), row.get("llm_report"))
                all_ids.add(row["id"])

    tmp = out_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for pid in sorted(all_ids):
            source, translated = pairs.get(pid, ("", ""))
            row: dict = {"id": pid, "source": source, "translated": translated}
            for crit in CRITERIA:
                entry = per_crit[crit].get(pid)
                if entry is None:
                    row[crit] = None
                else:
                    score, llm_report = entry
                    row[crit] = llm_report if score is not None else None
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(out_path)
    return out_path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true",
                   help="rebuild even if reports/<judge>.jsonl already exists")
    args = p.parse_args()

    pending = _find_pending(args.force)
    if not pending:
        print("nothing to build — all judges already have consolidated reports")
        return 0

    for variant_dir, judge in pending:
        rel = variant_dir.relative_to(EVAL_ROOT)
        out = _build_report(variant_dir, judge)
        n = sum(1 for _ in out.open())
        print(f"  built {rel}/reports/{judge}.jsonl  ({n} rows)")
    print(f"done — {len(pending)} report(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
