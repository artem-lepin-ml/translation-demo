#!/usr/bin/env python3
"""Rebuild the demo Term[] using the tournament winners: G3 grounding + P1 pairing.

G3 (LLM) grounding decisions come per-lemma from reports/terminology/g3_groundings.json
({lemma: {qid, difficulty}}); lemmas absent there (no candidates) are red. Pairing
is P1 (link_locate) — the pairing tournament winner. Output overwrites
data/seed/terminology_out.json for the demo DB load.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.base import WikidataRef
from palimpsest.terminology.extract import load_mentions
from palimpsest.terminology.verdict import pair_from_forms
from palimpsest.terminology.wikidata import WikidataClient, canonical_en_forms, label_of

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
MENTIONS = ROOT / "data/seed/terminology_terms.jsonl"
G3 = ROOT / "reports/terminology/g3_groundings.json"
OUT = ROOT / "data/seed/terminology_out.json"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"


def main() -> int:
    rows = {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}
    by_para = load_mentions(MENTIONS)
    g3 = json.loads(G3.read_text(encoding="utf-8"))
    wd = WikidataClient(cache_path=CACHE)

    # enrich all chosen QIDs once
    qids = sorted({v["qid"] for v in g3.values() if v.get("qid")})
    ents = wd.get_entities(qids)

    out, counts, pair_counts = {}, {"green": 0, "yellow": 0, "red": 0}, {"green": 0, "yellow": 0, "red": 0, "null": 0}
    for pid, mentions in by_para.items():
        terms = []
        target = rows[pid].get("translated", "")
        for m in mentions:
            dec = g3.get(m.lemma, {"qid": None, "difficulty": "red"})
            difficulty = dec.get("difficulty", "red")
            qid = dec.get("qid")
            if difficulty == "red" or not qid:
                terms.append(_term(m, "red", None, [], None, None, None))
                counts["red"] += 1
                pair_counts["null"] += 1
                continue
            ent = ents.get(qid, {})
            grounded = WikidataRef.from_qid(qid, label_of(ent, "en") or label_of(ent, "ru") or m.surface,
                                            ent.get("descriptions", {}).get("en", {}).get("value", ""))
            canon = canonical_en_forms(ent)
            ts, pa, rec = pair_from_forms(canon, target)
            terms.append(_term(m, difficulty, grounded, [grounded], ts, pa, rec))
            counts[difficulty] += 1
            pair_counts[pa or "null"] += 1
        out[str(pid)] = terms
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(counts.values())
    print(f"rebuilt {total} terms (G3 grounding + P1 pairing) → {OUT.relative_to(ROOT)}")
    print(f"  difficulty:   {counts}")
    print(f"  pairAccuracy: {pair_counts}")
    return 0


def _term(m, difficulty, grounded, candidates, ts, pa, rec) -> dict:
    return {
        "sourceSurface": m.surface, "sourceLemma": m.lemma or m.surface, "context": m.context,
        "charStart": m.char_start, "charEnd": m.char_end, "difficulty": difficulty,
        "grounded": grounded.as_dict() if grounded else None,
        "candidates": [c.as_dict() for c in candidates],
        "targetSurface": ts, "pairAccuracy": pa, "recommended": rec, "note": m.category or "",
    }


if __name__ == "__main__":
    raise SystemExit(main())
