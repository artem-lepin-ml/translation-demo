#!/usr/bin/env python3
"""Build 6 sorted views of a judge's per-criterion JSONLs for human review.

For a directory like ``data/pilot/evaluation/<run>/<variant>/<judge>/``
containing ``<criterion>_scores.jsonl`` files, writes under ``review/``:

  - ``by_paragraph.jsonl``                (ascending paragraph id)
  - ``by_<criterion>_desc.jsonl`` × N     (descending score, nulls last,
                                           ties broken by ascending id)

Each row consolidates all criteria scores + llm_reports + usage for the
paragraph. Originals are not modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CRITERION_SUFFIX = "_scores.jsonl"


def _load_criterion(path: Path) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def _consolidate(judge_dir: Path) -> tuple[list[str], list[dict]]:
    paths = sorted(judge_dir.glob(f"*{CRITERION_SUFFIX}"))
    if not paths:
        raise SystemExit(f"no *{CRITERION_SUFFIX} files under {judge_dir}")

    criteria = [p.name[: -len(CRITERION_SUFFIX)] for p in paths]
    per_crit = {c: _load_criterion(p) for c, p in zip(criteria, paths)}

    all_ids: set[int] = set()
    for crit in criteria:
        all_ids.update(per_crit[crit].keys())

    pair_for_pid: dict[int, tuple[str, str]] = {}
    for pid in all_ids:
        for crit in criteria:
            row = per_crit[crit].get(pid)
            if row is not None:
                pair_for_pid[pid] = (row.get("source", ""), row.get("translated", ""))
                break

    consolidated: list[dict] = []
    for pid in sorted(all_ids):
        source, translated = pair_for_pid[pid]
        scores: dict[str, int | None] = {}
        criteria_block: dict[str, dict] = {}
        for crit in criteria:
            row = per_crit[crit].get(pid)
            score = row.get("score") if row else None
            scores[crit] = score
            criteria_block[crit] = {
                "score": score,
                "llm_report": row.get("llm_report") if row else None,
                "usage": row.get("usage") if row else None,
            }
        consolidated.append(
            {
                "id": pid,
                "source": source,
                "translated": translated,
                "scores": scores,
                "criteria": criteria_block,
            }
        )
    return criteria, consolidated


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("judge_dir", type=Path,
                        help="path to <run>/<variant>/<judge>/ directory")
    parser.add_argument("--review-subdir", default="review",
                        help="output subdir name under judge_dir (default: review)")
    args = parser.parse_args()

    criteria, rows = _consolidate(args.judge_dir)
    out_dir = args.judge_dir / args.review_subdir

    _write_jsonl(out_dir / "by_paragraph.jsonl", rows)
    for crit in criteria:
        sorted_rows = sorted(
            rows,
            key=lambda r, c=crit: (
                r["scores"][c] is None,
                -(r["scores"][c] if r["scores"][c] is not None else 0),
                r["id"],
            ),
        )
        _write_jsonl(out_dir / f"by_{crit}_desc.jsonl", sorted_rows)

    print(f"[review] {len(rows)} rows → {out_dir} "
          f"({1 + len(criteria)} files: by_paragraph + by_<crit>_desc × {len(criteria)})")


if __name__ == "__main__":
    main()
