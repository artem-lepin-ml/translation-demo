#!/usr/bin/env python3
# Provenance: written 2026-07-10 to produce the final §3.1 dataset-statistics
# cascade for the paper, once tier_assignment.json covers the full 100-article
# gt.jsonl (see extend_tier_assignment.py).
"""Compute the gold mentions/entities/QIDs cascade (raw -> deterministic T2
tier filter -> manual anchor exclusions) over the current gt.jsonl, and write
it to data/eval/wiki/dataset_stats.json so the paper cites one source of
truth instead of re-deriving the numbers by hand.

Stage order matters: the T2 tier filter (data/eval/wiki/tier_assignment.json,
kept iff drop_level==0) is applied FIRST, the manual anchor exclusions
(data/eval/wiki/anchor_exclusions.json, identity
(token_index, anchor_text, qid, span_len) scoped by title) SECOND -- some
exclusions target anchors the tier filter already dropped, counted in
``overlap_excl_already_t2dropped`` rather than double-subtracted.

"entities" = distinct (article, QID) pairs; "qids" = distinct QIDs corpus-wide.
The final stage's named/term split pools each surviving entity's gold anchor
surfaces through the same ``_classify`` rule aggregate_corpus_v3 uses for
scoring (uppercase first letter of any surface -> named).

Run:
  cd /home/user/translation-demo && PYTHONPATH=src uv run --no-sync python3 \\
      data/eval/wiki/cleanup/tools/compute_dataset_stats.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from palimpsest.terminology.evaluation.metrics import _classify

ROOT = Path("/home/user/translation-demo")
GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"
TIER_PATH = ROOT / "data/eval/wiki/tier_assignment.json"
EXCL_PATH = ROOT / "data/eval/wiki/anchor_exclusions.json"
OUT_PATH = ROOT / "data/eval/wiki/dataset_stats.json"

Identity = tuple[int, str, str, int]


def git_rev(path: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", str(path)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    rev = result.stdout.strip()
    if not rev:
        raise SystemExit(f"HARD ERROR: `git log` returned no revision for {path}")
    return rev


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def main() -> None:
    gt = load_jsonl(GT_PATH)
    tier_assignment: dict[str, int] = json.loads(TIER_PATH.read_text(encoding="utf-8"))
    exclusions = json.loads(EXCL_PATH.read_text(encoding="utf-8"))["exclusions"]

    excl_by_title: dict[str, set[Identity]] = {}
    for e in exclusions:
        excl_by_title.setdefault(e["title"], set()).add(
            (e["token_index"], e["anchor_text"], e["qid"], e["span_len"])
        )

    raw_mentions = t2_mentions = final_mentions = 0
    raw_entities: set[tuple[str, str]] = set()
    t2_entities: set[tuple[str, str]] = set()
    final_entities: set[tuple[str, str]] = set()
    raw_qids: set[str] = set()
    t2_qids: set[str] = set()
    final_qids: set[str] = set()
    overlap_excl_already_t2dropped = 0
    final_surfaces_by_entity: dict[tuple[str, str], list[str]] = {}

    for rec in gt:
        title = rec["title"]
        excl_ids = excl_by_title.get(title, set())
        for t in rec["gt_tuples"]:
            idx, surf, qid, slen = t[0], t[1], t[2], t[3]
            identity = (idx, surf, qid, slen)

            raw_mentions += 1
            raw_entities.add((title, qid))
            raw_qids.add(qid)

            t2_kept = tier_assignment.get(qid, 0) == 0
            if t2_kept:
                t2_mentions += 1
                t2_entities.add((title, qid))
                t2_qids.add(qid)

            is_excluded = identity in excl_ids
            if is_excluded and not t2_kept:
                overlap_excl_already_t2dropped += 1

            if t2_kept and not is_excluded:
                final_mentions += 1
                final_entities.add((title, qid))
                final_qids.add(qid)
                final_surfaces_by_entity.setdefault((title, qid), []).append(surf)

    final_split = {"named": 0, "term": 0}
    for surfaces in final_surfaces_by_entity.values():
        cls, _ambiguous = _classify(surfaces)
        final_split[cls] += 1

    stats = {
        "generated_by": "data/eval/wiki/cleanup/tools/compute_dataset_stats.py",
        "gt_rev": git_rev(GT_PATH),
        "tier_rev": f"{len(tier_assignment)} QIDs ({git_rev(TIER_PATH)})",
        "exclusions_rev": git_rev(EXCL_PATH),
        "cascade": {
            "mentions": {"raw": raw_mentions, "t2": t2_mentions, "final": final_mentions},
            "entities": {"raw": len(raw_entities), "t2": len(t2_entities), "final": len(final_entities)},
            "qids": {"raw": len(raw_qids), "t2": len(t2_qids), "final": len(final_qids)},
        },
        "overlap_excl_already_t2dropped": overlap_excl_already_t2dropped,
        "final_split": final_split,
    }

    OUT_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
