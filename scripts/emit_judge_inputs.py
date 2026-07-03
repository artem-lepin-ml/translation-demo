#!/usr/bin/env python3
"""Emit judge inputs for the LLM strategies (G3/hybrid grounding, P3 pairing).

The judge is a subagent, not this process, so we serialise everything it needs —
candidate entities per grounding term, the translation + canonical forms per
pairing term — into one JSON file. A subagent answers it into judgments.json,
which eval_strategies.py then folds into scored rows.

Output: reports/terminology/judge_inputs.json
  {"grounding": [{surface, lemma, context, candidates:[{qid,label,description}]}...],
   "pairing":   [{surface, context, target, canon_en:[...]}...]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.base import TermMention
from palimpsest.terminology.grounding.candidates import generate_candidates
from palimpsest.terminology.wikidata import WikidataClient

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
GOLD = ROOT / "data/seed/terminology_gold.jsonl"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
OUT = ROOT / "reports/terminology/judge_inputs.json"


def main() -> int:
    rows = {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}
    gold = [json.loads(l) for l in GOLD.open(encoding="utf-8")]
    wd = WikidataClient(cache_path=CACHE)

    grounding, pairing = [], []
    for g in gold:
        src = rows[g["paragraph_id"]]["source"]
        i = src.find(g["surface"])
        ctx = src[max(0, i - 60): i + len(g["surface"]) + 60] if i >= 0 else (g.get("context") or "")
        gen = generate_candidates(wd, TermMention(surface=g["surface"], lemma=g["lemma"], context=ctx))
        grounding.append({
            "surface": g["surface"], "lemma": g["lemma"], "context": ctx,
            "candidates": [{"qid": c["qid"], "label": c["label"], "description": c["description"]}
                           for c in gen["candidates"]],
        })
        if g.get("gold_pair_accuracy"):
            canon = [g.get("canon_en")] if g.get("canon_en") else []
            canon += [a for a in (g.get("aliases_en") or []) if a not in canon]
            pairing.append({
                "surface": g["surface"], "context": ctx,
                "target": rows[g["paragraph_id"]].get("translated", ""),
                "canon_en": canon,
            })

    OUT.write_text(json.dumps({"grounding": grounding, "pairing": pairing},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"judge inputs: {len(grounding)} grounding + {len(pairing)} pairing  →  {OUT.relative_to(ROOT)}")
    print(f"live api calls this run: {wd.n_calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
