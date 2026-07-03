#!/usr/bin/env python3
"""Rebuild the demo Term[] with the consolidated tournament winners.

Grounding: G3 (llm_judge) — per-lemma decisions from reports/terminology/g3_groundings.json
({lemma: {qid, difficulty}}); lemmas absent there (no candidates) are red.

Pairing: P1 (link_locate, deterministic) as the baseline, with the curated P3
(llm_judge) verdicts overlaid on the hard cases from
reports/terminology/judgments_pairing.json ({surface: {verdict, target_surface,
recommended}}). This shows the yellow/red pairing calls P3 wins on (Tadmor→Palmyra,
nomadic→nome) without a full per-occurrence LLM pairing pass; production would run
full P3 with a P1→P3 escalation (see docs/stages/terminology.md).

Output: data/seed/terminology_out.json  (loaded into demo.db by load_terms.py).
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
LEMMAS = ROOT / "data/seed/lemmas.json"
G3 = ROOT / "reports/terminology/g3_groundings.json"
PAIR_P3 = ROOT / "reports/terminology/judgments_pairing.json"
OUT = ROOT / "data/seed/terminology_out.json"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"


def main() -> int:
    rows = {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}
    lemmas = json.loads(LEMMAS.read_text(encoding="utf-8")) if LEMMAS.exists() else {}
    by_para = load_mentions(MENTIONS)
    g3 = json.loads(G3.read_text(encoding="utf-8"))
    p3 = json.loads(PAIR_P3.read_text(encoding="utf-8")) if PAIR_P3.exists() else {}
    wd = WikidataClient(cache_path=CACHE)

    qids = sorted({v["qid"] for v in g3.values() if v.get("qid")})
    ents = wd.get_entities(qids)

    out, counts = {}, {"green": 0, "yellow": 0, "red": 0}
    pair_counts = {"green": 0, "yellow": 0, "red": 0, "null": 0}
    p3_overlaid = 0
    for pid, mentions in by_para.items():
        terms, target = [], rows[pid].get("translated", "")
        for m in mentions:
            lemma = lemmas.get(m.surface) or m.lemma or m.surface
            dec = g3.get(lemma, {"qid": None, "difficulty": "red"})
            difficulty, qid = dec.get("difficulty", "red"), dec.get("qid")
            if difficulty == "red" or not qid:
                terms.append(_term(m, "red", None, [], None, None, None))
                counts["red"] += 1
                pair_counts["null"] += 1
                continue
            ent = ents.get(qid, {})
            grounded = WikidataRef.from_qid(qid, label_of(ent, "en") or label_of(ent, "ru") or m.surface,
                                            ent.get("descriptions", {}).get("en", {}).get("value", ""))
            canon = canonical_en_forms(ent)
            # P1 baseline, then overlay the curated P3 verdict when we have one for this surface
            ts, pa, rec = pair_from_forms(canon, target)
            j = p3.get(m.surface)
            if j and j.get("verdict"):
                ts, pa, rec = j.get("target_surface", ts), j["verdict"], j.get("recommended")
                p3_overlaid += 1
            terms.append(_term(m, difficulty, grounded, [grounded], ts, pa, rec))
            counts[difficulty] += 1
            pair_counts[pa or "null"] += 1
        out[str(pid)] = terms

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(counts.values())
    print(f"rebuilt {total} terms (G3 grounding + P1/P3 pairing) → {OUT.relative_to(ROOT)}")
    print(f"  difficulty:   {counts}")
    print(f"  pairAccuracy: {pair_counts}  (P3 overlaid on {p3_overlaid} occurrences)")
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
