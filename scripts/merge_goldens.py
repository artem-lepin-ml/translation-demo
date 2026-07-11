#!/usr/bin/env python3
"""Merge the three hand-built golden sets into one unified, non-circular golden.

Sources (all over the same 16-paragraph pilot corpus, hand-authored, third-source
verified — never a strategy's output):
  - gold_sources/terminology_gold_manual.jsonl  (mine, 38: both signals)
  - gold_sources/grounding_gold.jsonl        (term-grounding, 65: grounding + candidates + source_url)
  - gold_sources/pairing_gold.jsonl          (term-pairing, 74: rich pairing hard cases)

Merge is keyed by the normalised lemma/surface. Where sources disagree on gold_qid
or gold_difficulty, a hand-resolved override (RESOLVE) — decided by direct Wikidata
verification — wins; the rationale is in the consolidation design doc §D7. Rows keep
the richest available annotation and gain a paragraph_id (located in the seed corpus)
so the eval harness can build a mention/target for every row.

Output: data/seed/terminology_gold.jsonl  + a reconciliation report on stdout.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/seed/gold_sources"
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
OUT = ROOT / "data/seed/terminology_gold.jsonl"

# ── conflict resolutions (verified against live Wikidata; see design §D7) ──────
# Each entry: the correct (gold_qid, gold_difficulty) for a term the sources disputed.
RESOLVE = {
    # wrong-QID disputes (a source picked a homonym/person/unrelated item)
    "фивы":          ("Q11225429", "yellow"),  # Greek Thebes (context: Boeotian/Athenian leagues), not Egyptian Q101583
    "хуанхэ":        ("Q7355", "green"),        # Yellow River; Q133281391 is a *person* named Huang He
    "чунь-цю":       ("Q185047", "yellow"),     # Spring-and-Autumn *period*; genuinely ambiguous vs the Annals Q747720
    "элам":          ("Q128904", "green"),      # Elam civilization; Q15975213 is "Solomon Hill"
    # difficulty disputes — my v1 golden over-labelled groundable terms as red.
    # Keys are the nominative LEMMA (the merge is keyed by lemma), not the surface.
    "авилум":        ("Q8210588", "green"),     # awīlum social class (thin item, exact concept)
    "мушкенум":      ("Q1586330", "green"),     # muškēnum (P31 = social class)
    "вардум":        ("Q9370997", "yellow"),    # wardu (slave); Q48536397 is a surname stub
    "байляньдун":    ("Q803830", "green"),      # Bailiandong archaeological site
    "цзэнпиянь":     ("Q189538", "green"),      # Zengpiyan archaeological site
    "умман-манда":   ("Q7881701", "green"),     # Umman Manda people group (exists)
    # difficulty disputes — homonym vs single-notable calls, resolved to notability rule
    "аккад":         ("Q150996", "green"),      # single exact "Akkad" city → green
    "ашшур":         ("Q200200", "green"),      # Assur city dominant (2/3 sources green)
    "саргон":        ("Q199461", "green"),      # Sargon of Akkad (context of Akkad founding)
    "кадашман-харбе":("Q879879", "yellow"),     # Kadashman-Harbe I & II → real homonym
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def load(name: str) -> list[dict]:
    return [json.loads(l) for l in (SRC / name).open(encoding="utf-8") if l.strip()]


def surf(r: dict) -> str:
    return r.get("surface") or r.get("source_surface") or ""


def unify(r: dict, origin: str) -> dict:
    """Map a source row into the unified schema."""
    return {
        "surface": surf(r),
        "lemma": r.get("lemma") or surf(r),
        "paragraph_id": r.get("paragraph_id"),
        "char_start": r.get("char_start"),
        "char_end": r.get("char_end"),
        "context": r.get("context"),
        "gold_qid": r.get("gold_qid") or None,
        "gold_difficulty": r.get("gold_difficulty") or r.get("difficulty"),
        "gold_candidates": r.get("gold_candidates"),
        "canon_en": r.get("canon_en") or r.get("expected_en"),
        "aliases_en": r.get("aliases_en"),
        "gold_target_surface": r.get("gold_target_surface"),
        "gold_pair_accuracy": r.get("gold_pair_accuracy"),
        "gold_recommended": r.get("gold_recommended"),
        "category": r.get("category") or "other",
        "source_url": r.get("source_url"),
        "notes": r.get("notes"),
        "_sources": [origin],
    }


def prefer(dst: dict, src: dict) -> None:
    """Fill dst's empty fields from src; keep the richest annotation.

    pairing labels + canon come preferentially from whoever *has* them (pairing74);
    context/candidates/source_url from whoever has them (grounding65); paragraph_id
    and char spans from whoever has them (mine / pairing74).
    """
    for k, v in src.items():
        if k == "_sources":
            dst["_sources"] = sorted(set(dst["_sources"]) | set(v))
            continue
        if dst.get(k) in (None, "", []) and v not in (None, "", []):
            dst[k] = v


def locate_paragraph(row: dict, paras: dict) -> int | None:
    """Assign a paragraph_id for grounding-only rows by matching context, then surface."""
    if row.get("paragraph_id") in paras:
        return row["paragraph_id"]
    ctx = (row.get("context") or "").strip()
    s = row["surface"]
    # 1) a distinctive slice of the grounding context
    if ctx:
        probe = ctx[:60]
        for pid, p in paras.items():
            if probe and probe in p["source"]:
                return pid
    # 2) fall back to any paragraph containing the surface (or its stem)
    stem = s[: max(4, len(s) - 2)]
    for pid, p in paras.items():
        if s in p["source"] or stem in p["source"]:
            return pid
    return None


def main() -> int:
    paras = {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}
    lemmas_path = ROOT / "data/seed/lemmas.json"
    lemmas = json.loads(lemmas_path.read_text(encoding="utf-8")) if lemmas_path.exists() else {}

    merged: dict[str, dict] = {}
    # order matters for prefer(): pairing74 first (richest pairing), then grounding65
    # (context/candidates), then mine (paragraph_id anchor) — prefer() only fills gaps.
    for name, origin in [("pairing_gold.jsonl", "pairing"),
                         ("grounding_gold.jsonl", "grounding"),
                         ("terminology_gold_manual.jsonl", "mine")]:
        for r in load(name):
            u = unify(r, origin)
            # apply the nominative lemma BEFORE keying — pairing rows carry no lemma, so
            # without this "Аккаде" (pairing) and "Аккад" (grounding) key differently and
            # both survive un-deduped, producing conflicting grounding labels for one term.
            u["lemma"] = lemmas.get(u["surface"]) or u["lemma"]
            k = norm(u["lemma"]) or norm(u["surface"])
            if k in merged:
                prefer(merged[k], u)
            else:
                merged[k] = u

    # apply conflict resolutions
    resolved = []
    for k, (qid, diff) in RESOLVE.items():
        if k in merged:
            before = (merged[k]["gold_qid"], merged[k]["gold_difficulty"])
            merged[k]["gold_qid"] = qid
            merged[k]["gold_difficulty"] = diff
            merged[k]["_resolved"] = True
            resolved.append((k, before, (qid, diff)))

    # assign paragraph_id everywhere so the eval harness can build a mention/target
    unlocated = []
    for k, row in merged.items():
        pid = locate_paragraph(row, paras)
        if pid is None:
            unlocated.append(row["surface"])
        row["paragraph_id"] = pid

    rows = [r for r in merged.values() if r["paragraph_id"] is not None and r["gold_difficulty"]]
    rows.sort(key=lambda r: (r["paragraph_id"], r["surface"]))

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    # ── reconciliation report ──────────────────────────────────────────────────
    from collections import Counter
    diff_dist = Counter(r["gold_difficulty"] for r in rows)
    pair_dist = Counter(r.get("gold_pair_accuracy") for r in rows if r.get("gold_pair_accuracy"))
    prov = Counter(tuple(r["_sources"]) for r in rows)
    print(f"merged golden: {len(rows)} rows  →  {OUT.relative_to(ROOT)}")
    print(f"difficulty dist: {dict(diff_dist)}")
    print(f"pairing-labelled: {sum(pair_dist.values())}  dist: {dict(pair_dist)}")
    print(f"with gold_qid: {sum(1 for r in rows if r['gold_qid'])}  "
          f"with source_url: {sum(1 for r in rows if r.get('source_url'))}")
    print(f"provenance (source combos): {dict(prov)}")
    print(f"\nconflicts resolved: {len(resolved)}")
    for k, before, after in sorted(resolved):
        print(f"  {k:16} {before} -> {after}")
    if unlocated:
        print(f"\nUNLOCATED (dropped): {unlocated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
