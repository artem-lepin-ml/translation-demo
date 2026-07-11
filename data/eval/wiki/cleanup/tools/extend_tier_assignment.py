#!/usr/bin/env python3
# Provenance: written 2026-07-10 to extend tier_assignment.json to the 5
# replacement articles (f4c3d00) that post-date the original tier build
# (0d89242, snapshotted from docs/experiments/2026-07-05-model-comparison/
# drafts/recall-tiers-analysis.md). The original classifier tool ("tiers.py"
# per that doc) was never committed to the repo -- only its rule DESCRIPTIONS
# survive in tier_defs.json. The classifier below reimplements those rules
# and was calibrated against all 3868 QIDs already in tier_assignment.json
# (99.97% exact match on drop_level; the single residual mismatch, Q17004545,
# is explained by a P31 change on Wikidata since the original snapshot -- see
# docs/reports/ for the calibration writeup) before being applied to the QIDs
# below. Where the rule text alone underdetermines a bucket (e.g. "unit of
# area" vs "unit of length", "material" vs "type of material"), the actual
# bucket membership was reverse-engineered from necessary/sufficient
# conditions over the known 3868 drop_level values, not guessed from the
# prose alone.
"""Extend data/eval/wiki/tier_assignment.json to cover QIDs newly introduced
into gt.jsonl by the 5-article replacement swap (f4c3d00), reusing the same
P31-class noise-bucket classification rules as the original tier build
(data/eval/wiki/tier_defs.json: META, CALENDAR, LANGUAGE_WRITING,
TAXON_SCIENCE, UNIT_STANDARD, ACADEMIC_ABSTRACT; "dropped iff EVERY P31 class
is a noise class; no-P31 or any-domain-P31 -> kept").

P31 data is resolved in priority order: an optional extra (scratch) Wikidata
cache first, then the repo's reports/terminology/wikidata_cache.jsonl, then a
live Wikidata fetch as a last resort (via palimpsest.terminology.wikidata.
WikidataClient, written to --fetch-cache-out so reports/ is never touched).

Run:
  cd /home/user/translation-demo && PYTHONPATH=src uv run --no-sync python3 \\
      data/eval/wiki/cleanup/tools/extend_tier_assignment.py \\
      [--extra-cache <path>] [--fetch-cache-out <path>] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/home/user/translation-demo")
sys.path.insert(0, str(ROOT / "src"))
from palimpsest.terminology.wikidata import WikidataClient  # noqa: E402

GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"
TIER_PATH = ROOT / "data/eval/wiki/tier_assignment.json"
REPO_WD_CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"

# ── noise-bucket classifier (data/eval/wiki/tier_defs.json rule_description) ──
T1_BUCKETS = {"META", "CALENDAR"}
T2_BUCKETS = {"META", "CALENDAR", "LANGUAGE_WRITING", "TAXON_SCIENCE", "UNIT_STANDARD", "ACADEMIC_ABSTRACT"}

_META_RE = re.compile(r"disambiguation|\blist\b|categor|duplicat", re.IGNORECASE)
_META_EXACT = {"name convention"}

_CALENDAR_EXACT = {"year", "decade", "century", "millennium", "calendar month", "temporal entity"}

_LANGUAGE_WRITING_RE = re.compile(
    r"language|writing system|\bscript\b|\balphabet\b|\bdialect\b|"
    r"transcription|romani[sz]ation|cyrillization|phoneme|\bphone\b|"
    r"part of speech|\bletter\b|hieroglyph|proto-language|chronolect|"
    r"genetic unit|linguistic term|syllabary|abjad|Aegean scripts|"
    r"IPA symbol|modifier letter|punctuation mark",
    re.IGNORECASE,
)
_LANGUAGE_WRITING_EXACT = {"stylistic device"}

_TAXON_SCIENCE_EXACT = {
    "taxon", "material", "chemical element", "organisms known by a particular common name",
    "simple substance", "chalcophile element",
}
_TAXON_SCIENCE_RE = re.compile(r"^mineral ", re.IGNORECASE)

_UNIT_STANDARD_EXACT = {
    "unit of mass", "unit of area", "ISO standard",
    "SI-accepted non-SI unit", "non-SI unit mentioned in and accepted with the SI",
}

_ACADEMIC_ABSTRACT_EXACT = {
    "concept", "quality", "activity", "economic activity", "form of government", "form of state",
    "political system", "political concept", "legal term or legal concept",
    "service", "occurrence", "hobby", "type of world view",
    "academic discipline", "field of study", "academic major", "periodization",
    "aspect of history", "culture of an area", "history of a country or state",
    "history of a city", "history of a geographic region",
    "aspect of history in a geographic region", "languages of a country",
}
_ACADEMIC_ABSTRACT_RE = re.compile(r"^branch of ", re.IGNORECASE)

# Small override set for classes an exact/keyword rule cannot separate from
# real domain classes by label text alone (none needed for the current QID
# batch; kept as the documented extension point the original tool also had).
OVERRIDES: dict[str, str] = {}


def class_bucket(label: str | None) -> str | None:
    """Noise bucket for a P31 class's English label, or None if it is a
    real/domain class (not noise), per tier_defs.json."""
    if not label:
        return None
    lbl = label.strip()
    if lbl in OVERRIDES:
        return OVERRIDES[lbl]
    if lbl in _META_EXACT or _META_RE.search(lbl):
        return "META"
    if lbl in _CALENDAR_EXACT:
        return "CALENDAR"
    if lbl in _LANGUAGE_WRITING_EXACT or _LANGUAGE_WRITING_RE.search(lbl):
        return "LANGUAGE_WRITING"
    if lbl in _TAXON_SCIENCE_EXACT or _TAXON_SCIENCE_RE.search(lbl):
        return "TAXON_SCIENCE"
    if lbl in _UNIT_STANDARD_EXACT:
        return "UNIT_STANDARD"
    if lbl in _ACADEMIC_ABSTRACT_EXACT or _ACADEMIC_ABSTRACT_RE.search(lbl):
        return "ACADEMIC_ABSTRACT"
    return None


def drop_level(class_labels: list[str | None]) -> int:
    """T1/T2 drop_level for a target given the English labels of its P31
    classes. No P31 (empty list) -> kept (0)."""
    if not class_labels:
        return 0
    buckets = [class_bucket(lbl) for lbl in class_labels]
    if any(b is None for b in buckets):
        return 0
    if all(b in T1_BUCKETS for b in buckets):
        return 1
    if all(b in T2_BUCKETS for b in buckets):
        return 2
    return 0  # unreachable given T1_BUCKETS subset T2_BUCKETS


# ── P31 resolution: extra (scratch) cache -> repo cache -> live network ──────
def load_cache_entities(cache_path: Path) -> dict[str, dict]:
    """QID -> entity dict, from every wbgetentities response in a wikidata
    cache JSONL file, irrespective of the exact ``props``/``languages`` the
    original query used (batched calls interleave many unrelated lookups)."""
    index: dict[str, dict] = {}
    if not cache_path.exists():
        return index
    with cache_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if "action=wbgetentities" not in rec["key"]:
                continue
            for qid, data in rec["value"].get("entities", {}).items():
                # a later, richer response (more claims/labels) wins
                if qid not in index or len(json.dumps(data)) > len(json.dumps(index[qid])):
                    index[qid] = data
    return index


def p31_class_ids(entity: dict | None) -> list[str]:
    out: list[str] = []
    for claim in (entity or {}).get("claims", {}).get("P31", []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id"):
            out.append(value["id"])
    return out


def resolve_targets(
    qids: list[str], extra_idx: dict[str, dict], repo_idx: dict[str, dict], fetch_cache_out: Path,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Resolve each target QID's entity (for its P31 classes), and return the
    per-QID source ('scratch'/'repo'/'network') used, in that priority order."""
    resolved: dict[str, dict] = {}
    source: dict[str, str] = {}
    need_network: list[str] = []
    for qid in qids:
        if qid in extra_idx and "claims" in extra_idx[qid]:
            resolved[qid] = extra_idx[qid]
            source[qid] = "scratch"
        elif qid in repo_idx and "claims" in repo_idx[qid]:
            resolved[qid] = repo_idx[qid]
            source[qid] = "repo"
        else:
            need_network.append(qid)
            source[qid] = "network"

    if need_network:
        wd = WikidataClient(cache_path=str(fetch_cache_out))
        for i in range(0, len(need_network), 50):
            batch = need_network[i : i + 50]
            entities = wd.get_entities(batch)
            resolved.update(entities)
    return resolved, source


def resolve_class_labels(
    class_ids: set[str], extra_idx: dict[str, dict], repo_idx: dict[str, dict], fetch_cache_out: Path,
) -> dict[str, str | None]:
    """EN label for each P31 class QID, same priority order as targets."""
    labels: dict[str, str | None] = {}
    need_network: list[str] = []
    for cid in class_ids:
        for idx in (extra_idx, repo_idx):
            en = idx.get(cid, {}).get("labels", {}).get("en", {}).get("value")
            if en:
                labels[cid] = en
                break
        if cid not in labels:
            need_network.append(cid)

    if need_network:
        wd = WikidataClient(cache_path=str(fetch_cache_out))
        for i in range(0, len(need_network), 50):
            batch = need_network[i : i + 50]
            entities = wd.get_entities(batch, props="labels", languages="en")
            for cid, data in entities.items():
                labels[cid] = data.get("labels", {}).get("en", {}).get("value")
    return labels


def missing_qids(tier_assignment: dict[str, int]) -> list[str]:
    gt_records = [json.loads(line) for line in GT_PATH.open(encoding="utf-8") if line.strip()]
    all_qids: set[str] = set()
    for rec in gt_records:
        for t in rec["gt_tuples"]:
            all_qids.add(t[2])
    return sorted(q for q in all_qids if q not in tier_assignment)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extra-cache", type=Path, default=None,
                         help="optional scratch Wikidata cache checked before the repo cache")
    parser.add_argument("--fetch-cache-out", type=Path,
                         default=ROOT / "data/eval/wiki/cleanup/tier_extension_fetch_cache.jsonl",
                         help="where live-network fetches (if any) are appended -- never reports/")
    parser.add_argument("--dry-run", action="store_true", help="report only, do not write tier_assignment.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    tier_assignment: dict[str, int] = json.loads(TIER_PATH.read_text(encoding="utf-8"))
    new_qids = missing_qids(tier_assignment)
    if not new_qids:
        print("no missing QIDs -- tier_assignment.json already covers all of gt.jsonl")
        return

    extra_idx = load_cache_entities(args.extra_cache) if args.extra_cache else {}
    repo_idx = load_cache_entities(REPO_WD_CACHE)

    entities, source = resolve_targets(new_qids, extra_idx, repo_idx, args.fetch_cache_out)

    all_class_ids: set[str] = set()
    for qid in new_qids:
        all_class_ids |= set(p31_class_ids(entities.get(qid)))
    class_labels = resolve_class_labels(all_class_ids, extra_idx, repo_idx, args.fetch_cache_out)

    new_levels: dict[str, int] = {}
    for qid in new_qids:
        class_ids = p31_class_ids(entities.get(qid))
        labels = [class_labels.get(cid) for cid in class_ids]
        new_levels[qid] = drop_level(labels)

    source_counts = Counter(source[q] for q in new_qids)
    level_counts = Counter(new_levels.values())
    print(f"resolved {len(new_qids)} new QIDs: "
          f"scratch={source_counts.get('scratch', 0)} repo={source_counts.get('repo', 0)} "
          f"network={source_counts.get('network', 0)}")
    print(f"drop_level distribution: 0={level_counts.get(0, 0)} "
          f"1={level_counts.get(1, 0)} 2={level_counts.get(2, 0)}")

    if args.dry_run:
        print("--dry-run: not writing tier_assignment.json")
        return

    # merge + re-sort by QID string (matches the existing file's key convention:
    # one "QID": level per line, no trailing newline before the closing brace)
    merged = {**tier_assignment, **new_levels}
    ordered = {qid: merged[qid] for qid in sorted(merged)}
    TIER_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {TIER_PATH} ({len(ordered)} QIDs, {len(new_qids)} new)")


if __name__ == "__main__":
    main()
