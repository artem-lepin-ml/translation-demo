#!/usr/bin/env python3
"""Emit per-lemma grounding judge inputs for the FULL demo term set.

The demo grounds per distinct lemma (rebuild_demo consumes {lemma: {qid,
difficulty}}). This serialises, for each distinct demo lemma, a representative
occurrence's context plus the shared candidate list, so a subagent can judge it.

Output: reports/terminology/demo_grounding_inputs.json  (list of {lemma, surface, context, candidates})
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.base import TermMention
from palimpsest.terminology.extract import load_mentions
from palimpsest.terminology.grounding.candidates import generate_candidates
from palimpsest.terminology.wikidata import WikidataClient

ROOT = Path(__file__).resolve().parents[1]
MENTIONS = ROOT / "data/seed/terminology_terms.jsonl"
LEMMAS = ROOT / "data/seed/lemmas.json"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
OUT = ROOT / "reports/terminology/demo_grounding_inputs.json"


def main() -> int:
    lemmas = json.loads(LEMMAS.read_text(encoding="utf-8")) if LEMMAS.exists() else {}
    by_para = load_mentions(MENTIONS)
    wd = WikidataClient(cache_path=CACHE)

    # one representative mention per distinct (re-lemmatised) lemma
    rep: dict[str, TermMention] = {}
    for mentions in by_para.values():
        for m in mentions:
            lemma = lemmas.get(m.surface) or m.lemma or m.surface
            m.lemma = lemma
            rep.setdefault(lemma, m)

    items = []
    for lemma, m in rep.items():
        gen = generate_candidates(wd, m)
        items.append({
            "lemma": lemma, "surface": m.surface, "context": m.context,
            "candidates": [{"qid": c["qid"], "label": c["label"], "description": c["description"]}
                           for c in gen["candidates"]],
        })
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    empties = sum(1 for it in items if not it["candidates"])
    print(f"demo grounding inputs: {len(items)} distinct lemmas ({empties} with no candidates)  →  {OUT.relative_to(ROOT)}")
    print(f"live api calls this run: {wd.n_calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
