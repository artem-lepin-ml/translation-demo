#!/usr/bin/env python3
"""Evaluate grounding/pairing strategies against the unified golden → metrics.json.

Runs G1 (api_first) and P1 (link_locate) natively. G3 / G5 (hybrid) / P3 (LLM) are
scored from a judgments file produced by subagents (``--judgments``), since the LLM
calls go through subagents, not this process. Grounding is scored on all 129 gold
terms; pairing on the pairing-labeled terms using the GOLD grounding (so pairing is
judged independently of grounding errors). Hybrid reuses G1's difficulty with the
judge's QID (see ``_hybrid_rows``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology import eval_harness as H
from palimpsest.terminology.base import PairRequest, TermMention
from palimpsest.terminology.grounding import ApiFirstGrounding
from palimpsest.terminology.pairing import LinkLocatePairing
from palimpsest.terminology.wikidata import WikidataClient, canonical_en_forms

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
GOLD = ROOT / "data/seed/terminology_gold.jsonl"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
METRICS = ROOT / "reports/terminology/metrics.json"


def _seed_rows():
    return {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}


def _gold():
    return [json.loads(l) for l in GOLD.open(encoding="utf-8")]


def _canon_forms(g: dict, wd) -> list[str]:
    """Canonical EN forms for pairing: from the grounded QID when present, always
    augmented with the golden's own canon_en/aliases_en (robust for thin/QID-less items)."""
    canon = []
    qid = g.get("gold_qid")
    if qid:
        canon = canonical_en_forms(wd.get_entities([qid]).get(qid, {}))
    for extra in ([g.get("canon_en")] if g.get("canon_en") else []) + (g.get("aliases_en") or []):
        if extra and extra not in canon:
            canon.append(extra)
    return canon


def _mention(g, rows) -> TermMention:
    src = rows[g["paragraph_id"]]["source"]
    i = src.find(g["surface"])
    ctx = src[max(0, i - 40): i + len(g["surface"]) + 40] if i >= 0 else ""
    return TermMention(surface=g["surface"], lemma=g["lemma"], context=ctx,
                       char_start=i, char_end=i + len(g["surface"]) if i >= 0 else -1,
                       category=g["category"])


def eval_grounding_native(strategy, gold, rows) -> list[dict]:
    out = []
    for g in gold:
        r = strategy.ground(_mention(g, rows))
        out.append({
            "surface": g["surface"], "category": g["category"],
            "gold_qid": g["gold_qid"], "gold_difficulty": g["gold_difficulty"],
            "pred_qid": r.grounded.qid if r.grounded else None, "pred_difficulty": r.difficulty,
            "latency_ms": r.latency_ms, "n_api_calls": r.n_api_calls,
        })
    return out


def eval_pairing_native(strategy, gold, rows, wd) -> list[dict]:
    out = []
    for g in gold:
        if not g.get("gold_pair_accuracy"):
            continue  # only pairing-labeled terms
        canon = _canon_forms(g, wd)
        target = rows[g["paragraph_id"]].get("translated", "")
        r = strategy.pair(PairRequest(surface=g["surface"], context="", target=target,
                                      qid=g.get("gold_qid"), canon_en=canon, difficulty=g["gold_difficulty"]))
        out.append({
            "surface": g["surface"], "category": g["category"],
            "gold_difficulty": g["gold_difficulty"], "gold_pair": g["gold_pair_accuracy"],
            "gold_recommended": g.get("gold_recommended"),
            "pred_pair": r.pair_accuracy, "pred_recommended": r.recommended,
            "latency_ms": r.latency_ms,
        })
    return out


def _hybrid_rows(g1_rows: list[dict], grounding_judgments: dict) -> list[dict]:
    """Hybrid = api_first difficulty (robust) + judge-picked QID (when it resolved one).

    Mirrors grounding/hybrid.py: keep api_first's pred_difficulty; swap pred_qid to
    the judge's choice on non-red terms where the judge named a QID.
    """
    out = []
    for r in g1_rows:
        j = grounding_judgments.get(r["surface"]) or {}
        pred_qid = r["pred_qid"]
        if r["pred_difficulty"] != "red" and j.get("qid"):
            pred_qid = j["qid"]
        out.append({**r, "pred_qid": pred_qid})  # difficulty stays api_first's
    return out


def _rows_from_judgments(judgments: dict, gold, kind: str) -> list[dict]:
    """Fold an LLM-judgment file (surface→verdict) into scoring rows."""
    out = []
    for g in gold:
        j = judgments.get(g["surface"])
        if j is None:
            continue
        if kind == "grounding":
            out.append({"surface": g["surface"], "category": g["category"], "gold_qid": g["gold_qid"],
                        "gold_difficulty": g["gold_difficulty"], "pred_qid": j.get("qid"),
                        "pred_difficulty": j.get("difficulty", "yellow"), "latency_ms": 0.0, "n_api_calls": 0})
        elif g.get("gold_pair_accuracy"):
            out.append({"surface": g["surface"], "category": g["category"],
                        "gold_difficulty": g["gold_difficulty"], "gold_pair": g["gold_pair_accuracy"],
                        "gold_recommended": g.get("gold_recommended"), "pred_pair": j.get("verdict"),
                        "pred_recommended": j.get("recommended"), "latency_ms": 0.0})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judgments", type=Path, help="LLM judgments JSON {grounding:{surface:..}, pairing:{surface:..}}")
    args = ap.parse_args()

    rows = _seed_rows()
    gold = _gold()
    wd = WikidataClient(cache_path=CACHE)

    g1 = eval_grounding_native(ApiFirstGrounding(wd), gold, rows)
    p1 = eval_pairing_native(LinkLocatePairing(wd), gold, rows, wd)

    grounding = {"api_first": H.score_grounding(g1)}
    pairing = {"link_locate": H.score_pairing(p1)}

    if args.judgments and args.judgments.exists():
        j = json.loads(args.judgments.read_text(encoding="utf-8"))
        if j.get("grounding"):
            grounding["llm_judge"] = H.score_grounding(_rows_from_judgments(j["grounding"], gold, "grounding"))
            grounding["hybrid"] = H.score_grounding(_hybrid_rows(g1, j["grounding"]))
        if j.get("pairing"):
            pairing["llm_judge"] = H.score_pairing(_rows_from_judgments(j["pairing"], gold, "pairing"))

    # extraction recall proxy: did extraction surface each gold term?
    extracted = {json.loads(l)["surface"] for l in (ROOT / "data/seed/terminology_terms.jsonl").open(encoding="utf-8")}
    gold_surfaces = {g["surface"] for g in gold}
    ext_recall = round(len(gold_surfaces & extracted) / len(gold_surfaces), 4)

    metrics = {
        "meta": {
            "golden_n": len(gold),
            "golden_distribution": {v: sum(1 for g in gold if g["gold_difficulty"] == v) for v in ("green", "yellow", "red")},
            "environment": "no CUDA; live Wikidata; LLM via subagents",
            "strategies_run": ["G1 api_first", "P1 link_locate"] + (["G3 llm_judge", "G5 hybrid", "P3 llm_judge"] if args.judgments else []),
            "strategies_code_only_not_run": ["G2 mgenre (GPU)", "P2 neural_align (GPU)"],
            "note": "Grounding tournament: G1 vs G3 vs G5(hybrid). Pairing: P1 vs P3. G2/P2 code-only (GPU), not run.",
        },
        "extraction": {"recall_on_gold_terms": ext_recall, "gold_terms_found": len(gold_surfaces & extracted),
                       "gold_terms_total": len(gold_surfaces),
                       "note": "Recall proxy on gold entities; full precision needs a gold extraction set (future work)."},
        "grounding": grounding,
        "pairing": pairing,
        "difficulty_accuracy_note": "qid_accuracy_on_groundable = grounded.qid == gold_qid among gold green/yellow.",
    }
    metrics["selection"] = {
        "grounding": H.select_winner({k: v for k, v in grounding.items()}, "qid_accuracy_on_groundable"),
        "pairing": H.select_winner({k: {**v, "qid_accuracy_on_groundable": v["verdict"]["macro_f1"]}
                                    for k, v in pairing.items()}, "qid_accuracy_on_groundable"),
    }
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    gm = grounding["api_first"]
    print(f"golden={len(gold)} dist={metrics['meta']['golden_distribution']}  extraction recall={ext_recall}")
    print(f"G1 grounding: qid_acc={gm['qid_accuracy_on_groundable']} difficulty_macroF1={gm['difficulty']['macro_f1']} "
          f"red_acc={gm['red_accuracy']} p50={gm['latency_ms']['p50']}ms")
    pm = pairing["link_locate"]
    print(f"P1 pairing:   verdict_macroF1={pm['verdict']['macro_f1']} null_acc={pm['null_accuracy_on_red']} "
          f"rec_acc={pm['recommended_accuracy']}")
    print(f"→ {METRICS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
