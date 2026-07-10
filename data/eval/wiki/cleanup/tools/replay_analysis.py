#!/usr/bin/env python3
# Provenance: written during the 2026-07-10 wiki-eval v2 session (ner-vs-disambig analysis).
# What it does: replays candidate retrieval offline to decompose FN errors into NER vs disambig.
# Paths inside may assume the original scratchpad CWD -- adjust before rerunning.
"""Offline NER-vs-disambiguation error decomposition for the gemini pilot
(wiki-eval v2, 10-article pilot). PURELY OFFLINE: no LLM calls, no network --
candidate retrieval is replayed strictly from the committed Wikidata cache
via ``OfflineWikidataClient`` (raises on any cache miss instead of fetching).

Run: PYTHONPATH=src uv run --no-sync python3 <this file>

Writes full JSON to replay_output.json in this directory; the markdown
report is authored from that JSON (every number traceable to this script).
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from palimpsest.terminology.base import GroundingConfig, TermMention
from palimpsest.terminology.evaluation import metrics as M
from palimpsest.terminology.grounding.candidates import generate_candidates
from palimpsest.terminology.grounding.match import norm
from palimpsest.terminology.wikidata import WikidataClient

ROOT = Path("/home/user/translation-demo")
RUN_DIR = ROOT / "reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z"
PRED_PATH = RUN_DIR / "pred.jsonl"
METRICS_PATH = RUN_DIR / "metrics.json"
META_PATH = RUN_DIR / "meta.json"
GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"
TIER_PATH = ROOT / "data/eval/wiki/tier_assignment.json"
CACHE_PATH = ROOT / "reports/terminology/wikidata_cache.jsonl"

SCRATCH = Path("/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/ner_vs_disambig")

EXPECTED_GATE = {
    "named": {"tp": 255, "fn": 47, "fp": 106, "gold_units": 302},
    "term": {"tp": 32, "fn": 45, "fp": 62, "gold_units": 77},
    "n_ambiguous_gold_units": 15,
    "n_gold_mentions_dropped_by_tier": 50,
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


class OfflineWikidataClient(WikidataClient):
    """Cache-only replay client: never performs a network round-trip.

    ``_fetch`` is overridden to answer strictly from the in-memory cache dict
    (loaded once at __init__ from CACHE_PATH, same loader as the base class);
    a miss is recorded and raises RuntimeError instead of calling urllib --
    the SAME exception type ``generate_candidates``'s only caller
    (``LabelFirstGrounding.ground``) expects, but here we catch it ourselves
    per-mention in the replay loop. ``_store`` is overridden to hard-fail so
    a bug can never accidentally append to the real, read-only cache file.
    """

    def __init__(self, cache_path: Path) -> None:
        super().__init__(cache_path=cache_path)
        self.miss_keys: list[str] = []

    def _fetch(self, base: str, params: dict) -> dict:  # noqa: D401
        params = {**params, "format": "json", "maxlag": "5"}
        key = base + "?" + urllib.parse.urlencode(sorted(params.items()))
        if key in self._cache:
            self.n_cache_hits += 1
            return self._cache[key]
        self.miss_keys.append(key)
        raise RuntimeError(f"OFFLINE REPLAY cache miss: {key}")

    def _store(self, key: str, value: dict) -> None:  # pragma: no cover - must never fire
        raise RuntimeError("OFFLINE REPLAY: _store must never be called (network path disabled)")


def overlaps(a_index: int, a_len: int, b_index: int, b_len: int) -> bool:
    return a_index < b_index + b_len and b_index < a_index + a_len


# ── Step 0: load ─────────────────────────────────────────────────────────────

def main() -> None:
    pred_records = load_jsonl(PRED_PATH)
    assert len(pred_records) == 1203, len(pred_records)
    committed_metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))

    gt_all = load_jsonl(GT_PATH)
    pred_titles = {r["title"] for r in pred_records}
    gt_pilot = [r for r in gt_all if r["title"] in pred_titles]
    assert len(gt_pilot) == 10, len(gt_pilot)
    assert {r["title"] for r in gt_pilot} == pred_titles

    tier_assignment: dict[str, int] = json.loads(TIER_PATH.read_text(encoding="utf-8"))

    pred_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in pred_records:
        pred_by_title[r["title"]].append(r)

    # ── Step 1: reconciliation gate ────────────────────────────────────────
    articles_for_v3: list[M.ArticleUnits] = []
    for rec in gt_pilot:
        gt_tuples = [tuple(t) for t in rec["gt_tuples"]]
        pred_tuples = [
            (r["index"], r["surface"], r["qid"], r["span_len"])
            for r in pred_by_title.get(rec["title"], []) if r.get("qid")
        ]
        articles_for_v3.append({"gt_tuples": gt_tuples, "pred_tuples": pred_tuples})

    v3_result = M.aggregate_corpus_v3(articles_for_v3, tier_assignment=tier_assignment)

    gate_ok = True
    gate_report = {}
    for cls in ("named", "term"):
        for k in ("tp", "fn", "fp", "gold_units"):
            got = v3_result["classes"][cls][k]
            want = EXPECTED_GATE[cls][k]
            gate_report[f"{cls}.{k}"] = {"got": got, "want": want, "match": got == want}
            gate_ok &= (got == want)
    for k in ("n_ambiguous_gold_units", "n_gold_mentions_dropped_by_tier"):
        got = v3_result[k]
        want = EXPECTED_GATE[k]
        gate_report[k] = {"got": got, "want": want, "match": got == want}
        gate_ok &= (got == want)
    # Also cross-check against the run's own committed metrics.json.
    committed_match = True
    for cls in ("named", "term"):
        for k in ("tp", "fn", "fp", "gold_units"):
            committed_match &= (v3_result["classes"][cls][k] == committed_metrics["classes"][cls][k])
    committed_match &= (v3_result["n_ambiguous_gold_units"] == committed_metrics["n_ambiguous_gold_units"])
    committed_match &= (v3_result["n_gold_mentions_dropped_by_tier"] == committed_metrics["n_gold_mentions_dropped_by_tier"])

    if not gate_ok:
        out = {"STOPPED": True, "reason": "reconciliation gate mismatch", "gate_report": gate_report}
        (SCRATCH / "replay_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        raise SystemExit("RECONCILIATION GATE FAILED -- see replay_output.json")

    print("Reconciliation gate: ALL MATCH (own hardcoded expectations + committed metrics.json)")
    print(f"  committed metrics.json match: {committed_match}")

    # ── Step 2: exact unit sets (mirrors aggregate_corpus_v3 internals) ────
    # gold_class[(title, qid)] = cls ; pred_qid_present[(title,qid)] = surfaces list
    gold_class: dict[tuple[str, str], str] = {}
    gold_ambiguous: dict[tuple[str, str], bool] = {}
    gold_surfaces_by_unit: dict[tuple[str, str], list[str]] = {}
    pred_surfaces_by_unit: dict[tuple[str, str], list[str]] = {}
    n_ambiguous_check = 0
    n_dropped_check = 0

    for rec in gt_pilot:
        title = rec["title"]
        gold_surfaces: dict[str, list[str]] = defaultdict(list)
        for t in rec["gt_tuples"]:
            qid = t[2]
            if tier_assignment.get(qid, 0) != 0:
                n_dropped_check += 1
                continue
            gold_surfaces[qid].append(t[1])
        pred_surfaces: dict[str, list[str]] = defaultdict(list)
        for r in pred_by_title.get(title, []):
            if r.get("qid"):
                pred_surfaces[r["qid"]].append(r["surface"])

        for qid, surfaces in gold_surfaces.items():
            cls, amb = M._classify(surfaces)
            gold_class[(title, qid)] = cls
            gold_ambiguous[(title, qid)] = amb
            gold_surfaces_by_unit[(title, qid)] = surfaces
            n_ambiguous_check += amb
        for qid, surfaces in pred_surfaces.items():
            pred_surfaces_by_unit[(title, qid)] = surfaces

    assert n_ambiguous_check == v3_result["n_ambiguous_gold_units"]
    assert n_dropped_check == v3_result["n_gold_mentions_dropped_by_tier"]

    tp_units: list[tuple[str, str, str]] = []  # (title, qid, cls)
    fn_units: list[tuple[str, str, str]] = []
    fp_units: list[tuple[str, str, str]] = []

    for (title, qid), cls in gold_class.items():
        if (title, qid) in pred_surfaces_by_unit:
            tp_units.append((title, qid, cls))
        else:
            fn_units.append((title, qid, cls))
    for (title, qid), surfaces in pred_surfaces_by_unit.items():
        if (title, qid) in gold_class:
            continue
        cls, _amb = M._classify(surfaces)
        fp_units.append((title, qid, cls))

    # self-consistency check against aggregate_corpus_v3's own counts
    for cls in ("named", "term"):
        assert sum(1 for t in tp_units if t[2] == cls) == v3_result["classes"][cls]["tp"]
        assert sum(1 for t in fn_units if t[2] == cls) == v3_result["classes"][cls]["fn"]
        assert sum(1 for t in fp_units if t[2] == cls) == v3_result["classes"][cls]["fp"]
    print("Unit-set self-consistency check (TP/FN/FP set sizes == aggregate_corpus_v3 counts): OK")

    # ── Step 3: candidate replay for ALL 1203 pred mentions ────────────────
    config = GroundingConfig(use_lemma=True, use_cirrus=True, use_sitelink=False, match_aliases=True)
    wd = OfflineWikidataClient(CACHE_PATH)

    replay: list[dict] = []  # parallel to pred_records
    n_cache_miss = 0
    for r in pred_records:
        mention = TermMention(surface=r["surface"], lemma=r["lemma"] or r["surface"], lang="ru")
        try:
            gen = generate_candidates(wd, mention, config)
            cand_qids = sorted({c["qid"] for c in gen["candidates"]})
            miss = False
        except RuntimeError:
            cand_qids = None
            miss = True
            n_cache_miss += 1
        replay.append({
            "title": r["title"], "index": r["index"], "surface": r["surface"], "lemma": r["lemma"],
            "qid": r["qid"], "span_len": r["span_len"], "resolved_by": r["resolved_by"],
            "candidate_qids": cand_qids, "cache_miss": miss,
        })

    miss_rate = n_cache_miss / len(pred_records)
    print(f"Candidate replay: {len(pred_records)} mentions, cache misses={n_cache_miss} ({miss_rate:.2%})")
    print(f"  distinct missed keys: {len(set(wd.miss_keys))}")
    partial = miss_rate > 0.02

    # ── Sanity checks ───────────────────────────────────────────────────────
    resolved_grounded = [r for r in replay if r["resolved_by"] in ("exact_label", "llm_disambiguation")]
    resolved_grounded_known = [r for r in resolved_grounded if not r["cache_miss"]]
    n_qid_in_cands = sum(1 for r in resolved_grounded_known if r["qid"] in (r["candidate_qids"] or []))
    sanity_grounded_pct = n_qid_in_cands / len(resolved_grounded_known) if resolved_grounded_known else float("nan")

    resolved_nocand = [r for r in replay if r["resolved_by"] == "no_candidates"]
    resolved_nocand_known = [r for r in resolved_nocand if not r["cache_miss"]]
    n_nocand_empty = sum(1 for r in resolved_nocand_known if r["candidate_qids"] == [])
    sanity_nocand_pct = n_nocand_empty / len(resolved_nocand_known) if resolved_nocand_known else float("nan")

    print(f"Sanity: chosen qid in replayed candidates: {n_qid_in_cands}/{len(resolved_grounded_known)} "
          f"({sanity_grounded_pct:.2%}) [of {len(resolved_grounded)} total, {len(resolved_grounded)-len(resolved_grounded_known)} cache-miss excluded]")
    print(f"Sanity: no_candidates -> empty replayed set: {n_nocand_empty}/{len(resolved_nocand_known)} "
          f"({sanity_nocand_pct:.2%}) [of {len(resolved_nocand)} total, {len(resolved_nocand)-len(resolved_nocand_known)} cache-miss excluded]")

    # index replay by (title, index) for span lookups (index is unique per mention
    # occurrence within an article in this pipeline: one extractor emission per position)
    replay_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in replay:
        replay_by_title[r["title"]].append(r)

    # gt anchors by (title, qid) -> list of (index, span_len, surface)
    anchors_by_unit: dict[tuple[str, str], list[tuple[int, int, str]]] = defaultdict(list)
    # ALL surviving (tier-filtered) anchors per article, regardless of unit membership -- used in C/D
    anchors_by_title: dict[str, list[tuple[int, int, str, str]]] = defaultdict(list)  # (index, span_len, surface, qid)
    for rec in gt_pilot:
        title = rec["title"]
        for t in rec["gt_tuples"]:
            idx, surf, qid, slen = t[0], t[1], t[2], t[3]
            if tier_assignment.get(qid, 0) != 0:
                continue
            anchors_by_unit[(title, qid)].append((idx, slen, surf))
            anchors_by_title[title].append((idx, slen, surf, qid))

    # ═══════════════════════════════ ANALYSIS A ═══════════════════════════
    a_buckets = {
        "named": Counter(), "term": Counter(),
    }
    a_disambig_subbuckets = {"named": Counter(), "term": Counter()}
    a_examples: list[dict] = []

    for (title, qid, cls) in fn_units:
        anchors = anchors_by_unit[(title, qid)]
        article_mentions = replay_by_title.get(title, [])
        overlapping = [
            m for m in article_mentions
            if any(overlaps(m["index"], m["span_len"], a_idx, a_len) for (a_idx, a_len, _s) in anchors)
        ]
        if not overlapping:
            bucket = "not_extracted"
        else:
            known = [m for m in overlapping if not m["cache_miss"]]
            unknown = [m for m in overlapping if m["cache_miss"]]
            if not known and unknown:
                bucket = "replay_unknown_all_cache_miss"
            else:
                all_empty = known and all((m["candidate_qids"] == []) for m in known)
                any_nonempty = any((m["candidate_qids"]) for m in known)
                gold_in_any = any(qid in (m["candidate_qids"] or []) for m in known)
                if gold_in_any:
                    bucket = "disambig_miss"
                elif any_nonempty:
                    bucket = "retrieval_miss"
                elif all_empty:
                    bucket = "no_candidates"
                else:
                    bucket = "retrieval_miss"  # mixed empty/unknown, conservative

        a_buckets[cls][bucket] += 1

        subbucket = None
        if bucket == "disambig_miss":
            eligible = [m for m in overlapping if not m["cache_miss"] and qid in (m["candidate_qids"] or [])]
            eligible.sort(key=lambda m: m["index"])
            exact_wrong = [m for m in eligible if m["resolved_by"] == "exact_label" and m["qid"] and m["qid"] != qid]
            llm_wrong = [m for m in eligible if m["resolved_by"] == "llm_disambiguation" and m["qid"] and m["qid"] != qid]
            rejected = [m for m in eligible if m["resolved_by"] == "judge_rejected"]
            if exact_wrong:
                subbucket = "resolved_to_different_qid (exact_label)"
            elif llm_wrong:
                subbucket = "resolved_to_different_qid (llm_disambiguation)"
            elif rejected:
                subbucket = "judge_rejected (qid=null)"
            else:
                subbucket = f"other ({sorted({m['resolved_by'] for m in eligible})})"
            a_disambig_subbuckets[cls][subbucket] += 1

        a_examples.append({
            "title": title, "qid": qid, "cls": cls, "bucket": bucket, "subbucket": subbucket,
            "n_overlapping_mentions": len(overlapping),
        })

    # ═══════════════════════════════ ANALYSIS B ═══════════════════════════
    # B1: article-pooled oracle recall
    oracle_pool_by_title: dict[str, set[str]] = {}
    for title, mentions in replay_by_title.items():
        pool: set[str] = set()
        for m in mentions:
            if m["candidate_qids"]:
                pool.update(m["candidate_qids"])
        oracle_pool_by_title[title] = pool

    b_oracle = {"named": {"matched": 0, "total": 0}, "term": {"matched": 0, "total": 0}}
    for (title, qid), cls in gold_class.items():
        b_oracle[cls]["total"] += 1
        if qid in oracle_pool_by_title.get(title, set()):
            b_oracle[cls]["matched"] += 1

    # B2: stricter overlap-restricted oracle recall
    b_oracle_overlap = {"named": {"matched": 0, "total": 0}, "term": {"matched": 0, "total": 0}}
    for (title, qid), cls in gold_class.items():
        anchors = anchors_by_unit[(title, qid)]
        article_mentions = replay_by_title.get(title, [])
        overlapping = [
            m for m in article_mentions
            if any(overlaps(m["index"], m["span_len"], a_idx, a_len) for (a_idx, a_len, _s) in anchors)
        ]
        unit_pool: set[str] = set()
        for m in overlapping:
            if m["candidate_qids"]:
                unit_pool.update(m["candidate_qids"])
        b_oracle_overlap[cls]["total"] += 1
        if qid in unit_pool:
            b_oracle_overlap[cls]["matched"] += 1

    # candidate-set-size stats for escalated (judge-seen) mentions
    escalated = [r for r in replay if r["resolved_by"] in ("llm_disambiguation", "judge_rejected") and not r["cache_miss"]]
    escalated_sizes = [len(r["candidate_qids"] or []) for r in escalated]
    b_escalated_size = {
        "n": len(escalated_sizes),
        "mean": statistics.mean(escalated_sizes) if escalated_sizes else None,
        "median": statistics.median(escalated_sizes) if escalated_sizes else None,
        "min": min(escalated_sizes) if escalated_sizes else None,
        "max": max(escalated_sizes) if escalated_sizes else None,
        "histogram": dict(sorted(Counter(escalated_sizes).items())),
        "share_exactly_1": (Counter(escalated_sizes)[1] / len(escalated_sizes)) if escalated_sizes else None,
    }

    # |S_p_oracle| per article
    per_article_pool_size = {title: len(pool) for title, pool in oracle_pool_by_title.items()}
    b_pool_size_stats = {
        "mean": statistics.mean(per_article_pool_size.values()),
        "median": statistics.median(per_article_pool_size.values()),
        "min": min(per_article_pool_size.values()),
        "max": max(per_article_pool_size.values()),
        "per_article": per_article_pool_size,
    }

    # actual R (from v3, for comparison)
    actual_r = {cls: v3_result["classes"][cls]["R_doc"]["value"] for cls in ("named", "term")}

    # ═══════════════════════════════ ANALYSIS C ═══════════════════════════
    c_buckets = {"named": Counter(), "term": Counter()}
    c_swap_true_wrong_pick = {"named": Counter(), "term": Counter()}
    swapped_away_from: set[tuple[str, str]] = set()  # (title, gold_qid) that some FP unit swapped away from

    for (title, fp_qid, cls) in fp_units:
        fp_mentions = [m for m in replay_by_title.get(title, []) if m["qid"] == fp_qid]
        other_anchors = [
            (idx, slen, surf, gqid) for (idx, slen, surf, gqid) in anchors_by_title.get(title, [])
            if gqid != fp_qid
        ]
        swap_pairs = []  # (mention, overlapped_gold_qid)
        for m in fp_mentions:
            for (a_idx, a_len, a_surf, a_qid) in other_anchors:
                if overlaps(m["index"], m["span_len"], a_idx, a_len):
                    swap_pairs.append((m, a_qid))

        if swap_pairs:
            bucket = "disambig_swap"
            true_wrong_pick = any(
                (not m["cache_miss"]) and (a_qid in (m["candidate_qids"] or []))
                for (m, a_qid) in swap_pairs
            )
            c_swap_true_wrong_pick[cls]["true_wrong_pick (right answer available)" if true_wrong_pick
                                         else "forced_swap (right answer never surfaced)"] += 1
            for (_m, a_qid) in swap_pairs:
                swapped_away_from.add((title, a_qid))
        else:
            bucket = "no_gold_overlap"
        c_buckets[cls][bucket] += 1

    # cross-check: how many FN disambig_miss units have a corresponding swap FP
    disambig_miss_units = [(title, qid, cls) for (title, qid, cls) in fn_units
                            if any(ex["title"] == title and ex["qid"] == qid and ex["bucket"] == "disambig_miss"
                                   for ex in a_examples)]
    n_disambig_miss_with_swap = sum(1 for (title, qid, _cls) in disambig_miss_units if (title, qid) in swapped_away_from)

    # ═══════════════════════════════ ANALYSIS D ═══════════════════════════
    # D: span-level, QID-agnostic NER quality
    d_recall = {"named": {"hit": 0, "total": 0}, "term": {"hit": 0, "total": 0}}
    per_article_recall: dict[str, dict] = {}
    for rec in gt_pilot:
        title = rec["title"]
        article_mentions = replay_by_title.get(title, [])
        art_hit, art_total = 0, 0
        for t in rec["gt_tuples"]:
            idx, surf, qid, slen = t[0], t[1], t[2], t[3]
            if tier_assignment.get(qid, 0) != 0:
                continue
            cls = gold_class.get((title, qid))
            if cls is None:
                # shouldn't happen: qid survived tier filter so it's in gold_class
                cls, _ = M._classify([surf])
            hit = any(overlaps(m["index"], m["span_len"], idx, slen) for m in article_mentions)
            d_recall[cls]["total"] += 1
            art_total += 1
            if hit:
                d_recall[cls]["hit"] += 1
                art_hit += 1
        per_article_recall[title] = {"hit": art_hit, "total": art_total,
                                      "recall": (art_hit / art_total) if art_total else None}

    recall_values = [v["recall"] for v in per_article_recall.values() if v["recall"] is not None]
    d_recall_spread = {
        "min": min(recall_values) if recall_values else None,
        "min_article": min((k for k in per_article_recall if per_article_recall[k]["recall"] is not None),
                            key=lambda k: per_article_recall[k]["recall"]) if recall_values else None,
        "max": max(recall_values) if recall_values else None,
        "max_article": max((k for k in per_article_recall if per_article_recall[k]["recall"] is not None),
                            key=lambda k: per_article_recall[k]["recall"]) if recall_values else None,
    }

    # D precision: fraction of 1203 pred mentions overlapping >=1 tier-filtered gold anchor
    d_precision = {"named": {"hit": 0, "total": 0}, "term": {"hit": 0, "total": 0}}
    for r in pred_records:
        title = r["title"]
        anchors = anchors_by_title.get(title, [])
        hit = any(overlaps(r["index"], r["span_len"], a_idx, a_len) for (a_idx, a_len, _s, _q) in anchors)
        cls, _amb = M._classify([r["surface"]])
        d_precision[cls]["total"] += 1
        if hit:
            d_precision[cls]["hit"] += 1

    # D precision dedup variant: unique (title, norm(lemma-or-surface)) groups
    dedup_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in pred_records:
        key = (r["title"], norm(r["lemma"] or r["surface"]))
        dedup_groups[key].append(r)
    dedup_hit, dedup_total = 0, 0
    for (title, _key), members in dedup_groups.items():
        anchors = anchors_by_title.get(title, [])
        dedup_total += 1
        if any(overlaps(m["index"], m["span_len"], a_idx, a_len)
               for m in members for (a_idx, a_len, _s, _q) in anchors):
            dedup_hit += 1

    # ── assemble output ────────────────────────────────────────────────────
    out = {
        "reconciliation_gate": {"ok": gate_ok, "committed_metrics_match": committed_match, "detail": gate_report},
        "replay": {
            "n_mentions": len(pred_records),
            "n_cache_miss": n_cache_miss,
            "miss_rate": miss_rate,
            "n_distinct_missed_keys": len(set(wd.miss_keys)),
            "missed_keys_sample": wd.miss_keys[:20],
            "partial_due_to_misses": partial,
            "n_cache_hits_this_replay": wd.n_cache_hits,
            "n_network_calls_this_replay": wd.n_calls,
        },
        "sanity": {
            "grounded_qid_in_candidates": {
                "n": n_qid_in_cands, "denom": len(resolved_grounded_known),
                "pct": sanity_grounded_pct, "total_grounded_records": len(resolved_grounded),
                "cache_miss_excluded": len(resolved_grounded) - len(resolved_grounded_known),
            },
            "no_candidates_replayed_empty": {
                "n": n_nocand_empty, "denom": len(resolved_nocand_known),
                "pct": sanity_nocand_pct, "total_no_candidates_records": len(resolved_nocand),
                "cache_miss_excluded": len(resolved_nocand) - len(resolved_nocand_known),
            },
        },
        "A_fn_decomposition": {
            "buckets": {cls: dict(a_buckets[cls]) for cls in ("named", "term")},
            "disambig_subbuckets": {cls: dict(a_disambig_subbuckets[cls]) for cls in ("named", "term")},
            "n_fn": {cls: sum(a_buckets[cls].values()) for cls in ("named", "term")},
        },
        "B_oracle_recall": {
            "article_pooled": {
                cls: {**b_oracle[cls], "R_oracle": (b_oracle[cls]["matched"] / b_oracle[cls]["total"]) if b_oracle[cls]["total"] else None}
                for cls in ("named", "term")
            },
            "overlap_restricted": {
                cls: {**b_oracle_overlap[cls], "R_oracle_overlap": (b_oracle_overlap[cls]["matched"] / b_oracle_overlap[cls]["total"]) if b_oracle_overlap[cls]["total"] else None}
                for cls in ("named", "term")
            },
            "actual_R_doc": actual_r,
            "escalated_candidate_set_size": b_escalated_size,
            "pool_size_per_article": b_pool_size_stats,
        },
        "C_precision_decomposition": {
            "buckets": {cls: dict(c_buckets[cls]) for cls in ("named", "term")},
            "swap_subbuckets": {cls: dict(c_swap_true_wrong_pick[cls]) for cls in ("named", "term")},
            "n_fp": {cls: sum(c_buckets[cls].values()) for cls in ("named", "term")},
            "n_disambig_miss_units_A": len(disambig_miss_units),
            "n_disambig_miss_with_corresponding_swap_fp": n_disambig_miss_with_swap,
        },
        "D_span_level_ner": {
            "recall": {
                cls: {**d_recall[cls], "rate": (d_recall[cls]["hit"] / d_recall[cls]["total"]) if d_recall[cls]["total"] else None}
                for cls in ("named", "term")
            },
            "recall_overall": {
                "hit": sum(d_recall[c]["hit"] for c in d_recall),
                "total": sum(d_recall[c]["total"] for c in d_recall),
            },
            "recall_spread_per_article": d_recall_spread,
            "recall_per_article": per_article_recall,
            "precision": {
                cls: {**d_precision[cls], "rate": (d_precision[cls]["hit"] / d_precision[cls]["total"]) if d_precision[cls]["total"] else None}
                for cls in ("named", "term")
            },
            "precision_overall": {
                "hit": sum(d_precision[c]["hit"] for c in d_precision),
                "total": sum(d_precision[c]["total"] for c in d_precision),
                "rate": sum(d_precision[c]["hit"] for c in d_precision) / sum(d_precision[c]["total"] for c in d_precision),
            },
            "precision_dedup": {"hit": dedup_hit, "total": dedup_total, "rate": dedup_hit / dedup_total if dedup_total else None},
        },
        "meta_context": {
            "n_pred_mentions": meta["n_pred_mentions"],
            "wikidata_cache_hits_live_run": meta["wikidata"]["cache_hits"],
            "wikidata_network_calls_live_run": meta["wikidata"]["calls"],
        },
    }

    out_path = SCRATCH / "replay_output.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\nwrote {out_path}")

    print("\n=== A: FN decomposition ===")
    for cls in ("named", "term"):
        print(f" {cls}: {dict(a_buckets[cls])}")
    print(" disambig subbuckets:")
    for cls in ("named", "term"):
        print(f"  {cls}: {dict(a_disambig_subbuckets[cls])}")

    print("\n=== B: oracle recall ===")
    print(out["B_oracle_recall"])

    print("\n=== C: precision decomposition ===")
    for cls in ("named", "term"):
        print(f" {cls}: {dict(c_buckets[cls])}  swap-subbucket: {dict(c_swap_true_wrong_pick[cls])}")
    print(f" cross-check: {n_disambig_miss_with_swap}/{len(disambig_miss_units)} disambig_miss FN units have a corresponding swap FP")

    print("\n=== D: span-level NER ===")
    print(out["D_span_level_ner"]["recall"])
    print(out["D_span_level_ner"]["precision"])
    print(out["D_span_level_ner"]["precision_dedup"])
    print(out["D_span_level_ner"]["recall_spread_per_article"])


if __name__ == "__main__":
    main()
