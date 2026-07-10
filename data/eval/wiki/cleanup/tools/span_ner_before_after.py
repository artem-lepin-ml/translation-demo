#!/usr/bin/env python3
# Provenance: written 2026-07-10 for the wiki-eval v2 gold-cleanup follow-up
# (span-level NER recall/precision before vs after the 2026-07 gold cleanup).
# Ports Section D's method verbatim from replay_analysis.py (same overlaps(),
# same M._classify pooled-surface classification, same tier filter, same dedup
# precision variant) -- no new overlap definition invented, no candidate-replay
# machinery needed since D never touches QIDs/Wikidata.
# What it does: recomputes span-level (QID-agnostic) NER recall/precision on
# the 2026-07-10 gemini pilot (1203 pred.jsonl mentions), gold BEFORE (the
# pre-cleanup snapshot the published report used) vs AFTER (current gt.jsonl
# restricted to still-present pilot articles, minus the live semantic
# exclusions from anchor_exclusions_draft.json applied IN-MEMORY only).
# PURELY OFFLINE: reads only committed files -- pred.jsonl, gt.jsonl (current,
# read-only) plus `git show` for the pre-cleanup snapshot, tier_assignment.json,
# anchor_exclusions_draft.json. No LLM calls, no network. gt.jsonl is never
# written to; nothing under reports/ is written or modified (pred.jsonl is
# read-only evidence here).
#
# Run: PYTHONPATH=src uv run --no-sync python3 <this file>
"""Span-level NER recall/precision on the gemini pilot, before vs after the
2026-07 gold-cleanup campaign (IPA-anchor fix 4c77b7c, 5-article corpus swap
f4c3d00, DRAFT semantic anchor exclusions in anchor_exclusions_draft.json).

Methodology (span overlap, tier filter, named/term classification): Section D
of docs/reports/wiki-eval-v2-pilot-ner-vs-disambig.md -- reused, not
reinvented. Full before/after narrative: docs/reports/wiki-eval-v2-span-ner-before-after-cleanup.md

Deterministic: reads only committed git state (fixed revisions) and the
current worktree's committed files, so two runs produce byte-identical output.
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path

from palimpsest.terminology.evaluation import metrics as M
from palimpsest.terminology.grounding.match import norm

ROOT = Path("/home/user/translation-demo")
RUN_DIR = ROOT / "reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z"
PRED_PATH = RUN_DIR / "pred.jsonl"
GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"
TIER_PATH = ROOT / "data/eval/wiki/tier_assignment.json"
EXCL_PATH = ROOT / "data/eval/wiki/anchor_exclusions_draft.json"

# Pre-cleanup gold snapshot the published report (commit 61bd46e) used -- the
# commit immediately before the first gold change (4c77b7c, IPA-anchor drop).
PRE_CLEANUP_GT_REV = "4c77b7c~1"

# The 5 non-ancient articles replaced wholesale by f4c3d00 -- kept here for
# documentation/cross-check only. Article status below is derived from actual
# gt.jsonl title membership, never from this hardcoded list.
REPLACED_ARTICLE_TITLES = {
    "Гелиополиты", "Керченский пролив", "Кесарево безумие", "Стигия", "Яффа",
}

# The published report's Section D recall cells (named 93.46%, term 62.11%,
# overall 87.76%) -- the baseline reproduction gate below must hit these
# exactly or the script stops before computing "after".
EXPECTED_BASELINE = {
    "named": {"hit": 400, "total": 428},
    "term": {"hit": 59, "total": 95},
}

SCRATCH = Path(
    "/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/span_ner_before_after"
)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def load_jsonl_text(text: str) -> list[dict]:
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def git_show(rev: str, path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout


def overlaps(a_index: int, a_len: int, b_index: int, b_len: int) -> bool:
    return a_index < b_index + b_len and b_index < a_index + a_len


def gold_class_map(gt_tuples: list[tuple], tier_assignment: dict) -> dict[str, str]:
    """qid -> named/term, pooled over its tier-filtered anchor surfaces --
    mirrors replay_analysis.py's Step-2 per-unit classification verbatim
    (M._classify over pooled surfaces, tier filter applied first)."""
    surfaces_by_qid: dict[str, list[str]] = defaultdict(list)
    for idx, surf, qid, slen in gt_tuples:
        if tier_assignment.get(qid, 0) != 0:
            continue
        surfaces_by_qid[qid].append(surf)
    return {qid: M._classify(surfaces)[0] for qid, surfaces in surfaces_by_qid.items()}


def span_recall(
    gt_by_title: dict[str, list[tuple]], pred_by_title: dict[str, list[dict]], tier_assignment: dict
) -> tuple[dict, dict]:
    """Mention-level recall over gold anchors, tier-filtered -- verbatim port
    of replay_analysis.py's Analysis-D recall loop."""
    recall = {"named": {"hit": 0, "total": 0}, "term": {"hit": 0, "total": 0}}
    per_article: dict[str, dict] = {}
    for title, gt_tuples in gt_by_title.items():
        article_mentions = pred_by_title.get(title, [])
        gold_class = gold_class_map(gt_tuples, tier_assignment)
        art_hit, art_total = 0, 0
        for idx, surf, qid, slen in gt_tuples:
            if tier_assignment.get(qid, 0) != 0:
                continue
            cls = gold_class[qid]
            hit = any(overlaps(m["index"], m["span_len"], idx, slen) for m in article_mentions)
            recall[cls]["total"] += 1
            art_total += 1
            if hit:
                recall[cls]["hit"] += 1
                art_hit += 1
        per_article[title] = {
            "hit": art_hit, "total": art_total, "recall": (art_hit / art_total) if art_total else None,
        }
    return recall, per_article


def build_anchors_by_title(gt_by_title: dict[str, list[tuple]], tier_assignment: dict) -> dict[str, list[tuple]]:
    anchors: dict[str, list[tuple]] = defaultdict(list)
    for title, gt_tuples in gt_by_title.items():
        for idx, surf, qid, slen in gt_tuples:
            if tier_assignment.get(qid, 0) != 0:
                continue
            anchors[title].append((idx, slen, surf, qid))
    return anchors


def span_precision(anchors_by_title: dict[str, list[tuple]], pred_records: list[dict]) -> dict:
    """Fraction of pred mentions overlapping >=1 tier-filtered gold anchor --
    verbatim port of replay_analysis.py's Analysis-D precision loop. Severe
    lower bound (Wikipedia links only first mentions), same caveat as the
    published report."""
    precision = {"named": {"hit": 0, "total": 0}, "term": {"hit": 0, "total": 0}}
    for r in pred_records:
        anchors = anchors_by_title.get(r["title"], [])
        hit = any(overlaps(r["index"], r["span_len"], a_idx, a_len) for (a_idx, a_len, _s, _q) in anchors)
        cls, _amb = M._classify([r["surface"]])
        precision[cls]["total"] += 1
        if hit:
            precision[cls]["hit"] += 1
    return precision


def span_precision_dedup(anchors_by_title: dict[str, list[tuple]], pred_records: list[dict]) -> dict:
    """Dedup precision variant: group pred mentions by (title, norm(lemma or
    surface)); a group is a hit if ANY member overlaps a gold anchor --
    verbatim port of replay_analysis.py's dedup-precision loop."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in pred_records:
        groups[(r["title"], norm(r["lemma"] or r["surface"]))].append(r)
    hit, total = 0, 0
    for (title, _key), members in groups.items():
        anchors = anchors_by_title.get(title, [])
        total += 1
        if any(
            overlaps(m["index"], m["span_len"], a_idx, a_len) for m in members for (a_idx, a_len, _s, _q) in anchors
        ):
            hit += 1
    return {"hit": hit, "total": total}


def overall(cell_by_class: dict) -> dict:
    hit = sum(c["hit"] for c in cell_by_class.values())
    total = sum(c["total"] for c in cell_by_class.values())
    return {"hit": hit, "total": total, "rate": (hit / total) if total else None}


def rate(cell: dict) -> dict:
    return {**cell, "rate": (cell["hit"] / cell["total"]) if cell["total"] else None}


def main() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)

    pred_records = load_jsonl(PRED_PATH)
    assert len(pred_records) == 1203, len(pred_records)
    pred_titles = sorted({r["title"] for r in pred_records})
    assert len(pred_titles) == 10, len(pred_titles)
    pred_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in pred_records:
        pred_by_title[r["title"]].append(r)

    tier_assignment: dict = json.loads(TIER_PATH.read_text(encoding="utf-8"))

    # ---- pilot article status: kept vs replaced -------------------------------
    # Derived from CURRENT gt.jsonl title membership, not from the hardcoded
    # REPLACED_ARTICLE_TITLES hint above (that set is documentation only).
    gt_current_records = load_jsonl(GT_PATH)
    gt_current_by_title = {r["title"]: r for r in gt_current_records}
    pilot_status = []
    kept_titles: list[str] = []
    for title in pred_titles:
        status = "kept" if title in gt_current_by_title else "replaced"
        pilot_status.append({"title": title, "status": status})
        if status == "kept":
            kept_titles.append(title)
    n_replaced = sum(1 for p in pilot_status if p["status"] == "replaced")
    assert not (set(pred_titles) & REPLACED_ARTICLE_TITLES), "pilot title unexpectedly in the replaced-title hint list"

    # ---- pre-cleanup gold snapshot (what the published report used) -----------
    gt_pre_by_title = {r["title"]: r for r in load_jsonl_text(git_show(PRE_CLEANUP_GT_REV, "data/eval/wiki/gt.jsonl"))}

    # Sanity required by the task: pre-fix (4c77b7c~1) vs post-fix (4c77b7c)
    # gt_tuples for the 10 pilot titles must be identical -- the IPA fix
    # touched 4 OTHER articles, none in this pilot.
    gt_postipa_by_title = {r["title"]: r for r in load_jsonl_text(git_show("4c77b7c", "data/eval/wiki/gt.jsonl"))}
    ipa_fix_identical_for_pilot = all(
        [tuple(t) for t in gt_pre_by_title[t]["gt_tuples"]] == [tuple(t) for t in gt_postipa_by_title[t]["gt_tuples"]]
        for t in pred_titles
    )

    baseline_gt_by_title = {t: [tuple(x) for x in gt_pre_by_title[t]["gt_tuples"]] for t in pred_titles}

    # ---- Baseline reproduction (sanity gate) -----------------------------------
    baseline_recall, baseline_per_article = span_recall(baseline_gt_by_title, pred_by_title, tier_assignment)
    baseline_reproduced = all(baseline_recall[cls] == EXPECTED_BASELINE[cls] for cls in ("named", "term"))

    if not baseline_reproduced:
        out = {"STOPPED": True, "reason": "baseline reproduction gate mismatch",
               "got": baseline_recall, "want": EXPECTED_BASELINE}
        (SCRATCH / "output.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
        raise SystemExit("BASELINE REPRODUCTION GATE FAILED -- see output.json")

    baseline_anchors = build_anchors_by_title(baseline_gt_by_title, tier_assignment)
    baseline_precision = span_precision(baseline_anchors, pred_records)
    baseline_precision_dedup = span_precision_dedup(baseline_anchors, pred_records)

    # ---- After: current gt.jsonl (kept pilot titles only), minus live exclusions
    excl_data = json.loads(EXCL_PATH.read_text(encoding="utf-8"))
    excl_by_title: dict[str, set] = defaultdict(set)
    for e in excl_data["exclusions"]:
        if e["title"] in kept_titles:
            excl_by_title[e["title"]].add((e["token_index"], e["anchor_text"], e["qid"], e["span_len"]))

    after_gt_by_title: dict[str, list[tuple]] = {}
    excluded_counts: dict[str, dict] = {}
    for title in kept_titles:
        before_tuples = [tuple(t) for t in gt_current_by_title[title]["gt_tuples"]]
        ex_set = excl_by_title.get(title, set())
        matched = [t for t in before_tuples if t in ex_set]
        unmatched_ex = ex_set - set(before_tuples)
        assert not unmatched_ex, (title, unmatched_ex)
        after_tuples = [t for t in before_tuples if t not in ex_set]
        n_tier0_removed = sum(1 for t in matched if tier_assignment.get(t[2], 0) == 0)
        after_gt_by_title[title] = after_tuples
        excluded_counts[title] = {
            "n_gt_tuples_before": len(before_tuples),
            "n_gt_tuples_after": len(after_tuples),
            "n_exclusion_entries_matched": len(matched),
            "n_tier0_anchors_removed": n_tier0_removed,
        }

    after_recall, after_per_article = span_recall(after_gt_by_title, pred_by_title, tier_assignment)
    after_anchors = build_anchors_by_title(after_gt_by_title, tier_assignment)
    after_precision = span_precision(after_anchors, pred_records)
    after_precision_dedup = span_precision_dedup(after_anchors, pred_records)

    # cross-check: total tier-0 anchors removed must equal the before/after
    # recall-denominator delta exactly.
    total_before = sum(baseline_recall[c]["total"] for c in baseline_recall)
    total_after = sum(after_recall[c]["total"] for c in after_recall)
    n_tier0_removed_sum = sum(v["n_tier0_anchors_removed"] for v in excluded_counts.values())
    assert total_before - total_after == n_tier0_removed_sum, (total_before, total_after, n_tier0_removed_sum)

    out = {
        "pilot_articles": pilot_status,
        "n_replaced": n_replaced,
        "ipa_fix_identical_for_pilot_titles": ipa_fix_identical_for_pilot,
        "baseline": {
            "gold_snapshot": PRE_CLEANUP_GT_REV,
            "gate": "reproduced" if baseline_reproduced else "MISMATCH",
            "recall": {cls: rate(baseline_recall[cls]) for cls in ("named", "term")},
            "recall_overall": overall(baseline_recall),
            "precision": {cls: rate(baseline_precision[cls]) for cls in ("named", "term")},
            "precision_overall": overall(baseline_precision),
            "precision_dedup": rate(baseline_precision_dedup),
            "recall_per_article": baseline_per_article,
        },
        "after": {
            "gold_snapshot": "gt.jsonl HEAD minus live anchor_exclusions_draft.json exclusions (in-memory)",
            "recall": {cls: rate(after_recall[cls]) for cls in ("named", "term")},
            "recall_overall": overall(after_recall),
            "precision": {cls: rate(after_precision[cls]) for cls in ("named", "term")},
            "precision_overall": overall(after_precision),
            "precision_dedup": rate(after_precision_dedup),
            "recall_per_article": after_per_article,
        },
        "excluded_anchor_counts_per_article": excluded_counts,
    }

    out_path = SCRATCH / "output.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {out_path}")
    print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
