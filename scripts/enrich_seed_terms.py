"""Enrich data/seed/seed_paragraphs.jsonl terminology with real Wikidata grounding.

Spec: docs/superpowers/specs/2026-07-05-glossary-redesign-impl.md §7.

Deterministic-only (no LLM disambiguation): for every unique ``source_term``
surface across the seed's ``identified_terms``, query live Wikidata
(``wbsearchentities``, ru) once, exact-match the surface against candidate
labels/aliases (reusing ``terminology.grounding.match.norm``/``exact_match``),
and record a real ``qid`` + a decision trace when the match is unambiguous.
Ambiguous or empty results are recorded honestly (``ambiguous_candidates`` /
``no_candidates``) rather than guessed.

Idempotent: an ``identified_terms`` entry that already carries a ``resolved_by``
key is left untouched, so reruns only fill in gaps. Fans a single grounding
result out to every occurrence of the same surface (dedup-once, apply-many).

Run: ``uv run python scripts/enrich_seed_terms.py``.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from palimpsest.terminology.grounding.match import exact_match, norm  # noqa: E402
from palimpsest.terminology.wikidata import WikidataClient  # noqa: E402

SEED_FILE = REPO_ROOT / "data" / "seed" / "seed_paragraphs.jsonl"
CACHE_PATH = REPO_ROOT / "reports" / "terminology" / "wikidata_cache.jsonl"
MAX_CANDIDATES = 4
MIN_INTERVAL = 0.5  # well under 5 req/s to Wikidata — the shared container IP
                     # appears to share Wikidata's rate-limit bucket with other
                     # traffic, so stay conservative rather than tune to the max.

# Deterministic sanity filters: a proper-noun surface search can prefix-collide
# with an unrelated entity that happens to share the same inflected spelling
# (observed live: "Тигра" genitive-of-Тигр/Tigris also exact-matches the
# Winnie-the-Pooh character "Тигра"/Tigger; "Ирака" genitive-of-Ирак/Iraq
# exact-matches an unrelated Muisca ruler "Iraca"; a Wikimedia disambiguation
# page can carry the bare label while the real target item's label has a
# disambiguating suffix). None of this is guessed away with an LLM — these are
# cheap, literal, deterministic rejections so a collision falls through to
# 'ambiguous_candidates' honestly instead of a confidently wrong 'exact_label'.
_FICTION_MARKERS = (
    "персонаж", "мультф", "комикс", "вымышлен", "fictional", "cartoon", "comic",
)
_DISAMBIG_MARKERS = ("disambiguation", "страница значений")  # EN + the RU description Wikidata uses
# Person-role markers: reject a person-shaped candidate for a term tagged
# domain=="place" (surface is a toponym, so a match to a person's Wikidata
# item is definitionally wrong here, not a judgment call).
_PERSON_MARKERS = (
    "ruler", "priest", "king ", "queen ", "politician", "footballer", "born ",
    "died ", "president", "emperor", "monarch", "bishop", "pope", "poet",
    "singer", "writer", "painter", "actor", "actress",
)
# Positive topical allowlist (RU + EN): the whole seed corpus is one document
# about ancient Mesopotamia, so a real match's description should read as
# ancient/historical/geographic. Plain label/alias exact-matching without a
# lemmatizer repeatedly collided with unrelated but well-known modern entities
# that happen to share a Russian inflected form as their own RU label/alias —
# observed live: "Субара" (no distinct case ending from "Субар/Субарту") is
# also a Wikidata RU alias of the car brand "Subaru"; "вавилонский" (the plain
# adjective) is also the name of a village in Altai Krai; "династии" is also a
# 2018 documentary TV series. A blocklist chases one false-friend category at
# a time; requiring a topical hit is the more complete, generalizable guard
# for a single-topic corpus like this one. An empty/unclassifiable description
# fails the allowlist too — that is the intended conservative direction (an
# uninformative description isn't grounds for confident exact_label either).
_PLAUSIBLE_MARKERS = (
    "археолог", "истори", "древн", "мифол", "бог", "богин", "импери", "царь",
    "короле", "правител", "город", "рек", "государств", "цивилизац", "период",
    "династ", "культур", "месопотам", "шумер", "вавилон", "ассири", "аккад",
    "семит", "клинопис", "храм",
    "archaeolog", "histor", "ancient", "myth", "god", "goddess", "empire",
    "king", "ruler", "river", "civiliz", "period", "dynast", "culture",
    "mesopotam", "sumer", "babylon", "assyria", "akkad", "semitic", "temple",
    "cuneiform", "near east",
)


def _is_implausible(description: str, domain: str | None) -> bool:
    d = (description or "").lower()
    if any(m in d for m in _FICTION_MARKERS):
        return True
    if any(m in d for m in _DISAMBIG_MARKERS):
        return True
    if domain == "place" and any(m in d for m in _PERSON_MARKERS):
        return True
    if not any(m in d for m in _PLAUSIBLE_MARKERS):
        return True
    return False


def _entity_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}"


def _search_with_retry(wd: WikidataClient, surface: str, tries: int = 4) -> list[dict]:
    """search_entities wrapped with a script-level backoff — the shared
    container IP hit sustained 429s past WikidataClient's own retry budget."""
    for attempt in range(tries):
        try:
            return wd.search_entities(surface, lang="ru", limit=7)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    return []  # unreachable


def ground_surface(wd: WikidataClient, surface: str, domain: str | None) -> dict:
    """Ground one surface deterministically. Returns the enrichment dict
    (qid, label_en, resolved_by, candidates, trace) — never raises; a
    persistent network failure degrades to 'no_candidates' rather than
    aborting the whole batch."""
    t0 = time.perf_counter()
    calls_before = wd.n_calls
    try:
        hits = _search_with_retry(wd, surface)
    except Exception as exc:
        trace = {
            "query": {"surface_hits": 0},
            "search": {"method": "wbsearchentities", "hits": 0, "error": str(exc)[:200]},
            "label_match": {"exact_matches": 0},
            "decision": {"resolved_by": "no_candidates",
                         "api_calls": wd.n_calls - calls_before,
                         "elapsed_s": round(time.perf_counter() - t0, 3)},
            "resolved_by": "no_candidates",
        }
        return {"qid": None, "label_en": None, "resolved_by": "no_candidates",
                "candidates": [], "trace": trace}
    if wd.n_calls > calls_before:
        time.sleep(MIN_INTERVAL)

    trace = {
        "query": {"surface_hits": len(hits)},
        "search": {"method": "wbsearchentities", "hits": len(hits)},
    }

    if not hits:
        trace["label_match"] = {"exact_matches": 0}
        trace["decision"] = {
            "resolved_by": "no_candidates",
            "api_calls": wd.n_calls - calls_before,
            "elapsed_s": round(time.perf_counter() - t0, 3),
        }
        trace["resolved_by"] = "no_candidates"
        return {"qid": None, "label_en": None, "resolved_by": "no_candidates",
                "candidates": [], "trace": trace}

    # Reuse the grounding module's own norm()/exact_match() rather than
    # reinventing normalization — shape hits as the [{label_ru, aliases_ru}]
    # candidate dicts exact_match() expects.
    shaped = [
        {
            "qid": h["id"],
            "label_ru": h.get("label", ""),
            "aliases_ru": list(h.get("aliases") or []),
            "description": h.get("description", ""),
        }
        for h in hits
    ]
    raw_exact = exact_match([surface], shaped, match_aliases=True)
    exact_hits = [c for c in raw_exact if not _is_implausible(c.get("description", ""), domain)]
    trace["label_match"] = {"exact_matches": len(exact_hits)}

    if len(exact_hits) == 1:
        resolved_by = "exact_label"
        chosen_qid = exact_hits[0]["qid"]
    else:
        # 0 exact matches, or >1 (genuinely ambiguous, or the only exact hit
        # was filtered out as a fiction false-friend) — don't guess.
        resolved_by = "ambiguous_candidates"
        chosen_qid = None

    # Candidate pool for the UI: exact hits first, then fill from the raw
    # search-rank order, deduped by qid, capped at MAX_CANDIDATES.
    ordered_qids: list[str] = []
    for c in exact_hits + shaped:
        if c["qid"] not in ordered_qids:
            ordered_qids.append(c["qid"])
    ordered_qids = ordered_qids[:MAX_CANDIDATES]

    by_qid = {c["qid"]: c for c in shaped}
    exact_qids = {c["qid"] for c in exact_hits}

    trace["decision"] = {
        "resolved_by": resolved_by,
        "api_calls": wd.n_calls - calls_before,
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }
    trace["resolved_by"] = resolved_by

    return {
        "_chosen_qid": chosen_qid,
        "_candidate_qids": ordered_qids,
        "_matched_via": {qid: ("label_ru" if qid in exact_qids else None) for qid in ordered_qids},
        "resolved_by": resolved_by,
        "trace": trace,
        "_by_qid": by_qid,
    }


def enrich_labels(wd: WikidataClient, qids: list[str]) -> dict[str, dict]:
    """Batch-fetch EN labels/descriptions for the final candidate pool —
    one (or a few, ≤50/batch) network calls total instead of one per term."""
    if not qids:
        return {}
    calls_before = wd.n_calls
    entities = wd.get_entities(qids, props="labels|descriptions", languages="en|ru")
    if wd.n_calls > calls_before:
        time.sleep(MIN_INTERVAL)
    out = {}
    for qid, ent in entities.items():
        label_en = ent.get("labels", {}).get("en", {}).get("value")
        label_ru = ent.get("labels", {}).get("ru", {}).get("value")
        desc_en = ent.get("descriptions", {}).get("en", {}).get("value")
        desc_ru = ent.get("descriptions", {}).get("ru", {}).get("value")
        out[qid] = {
            "label": label_en or label_ru or qid,
            "description": desc_en or desc_ru or "",
        }
    return out


def main() -> None:
    lines = [l for l in SEED_FILE.read_text("utf-8").splitlines() if l.strip()]
    rows = [json.loads(l) for l in lines]

    # 1. Collect unique surfaces still needing grounding (+ first-seen domain,
    #    used only for the deterministic implausibility filter above).
    pending: dict[str, str | None] = {}
    for row in rows:
        terminology = row.get("terminology") or {}
        for t in terminology.get("identified_terms") or []:
            surface = t.get("source_term", "")
            if surface and "resolved_by" not in t:
                pending.setdefault(surface, t.get("domain"))

    print(f"unique surfaces total across seed: "
          f"{len({t.get('source_term') for r in rows for t in (r.get('terminology') or {}).get('identified_terms') or [] if t.get('source_term')})}")
    print(f"pending (not yet enriched): {len(pending)}")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    wd = WikidataClient(cache_path=CACHE_PATH)

    results: dict[str, dict] = {}
    for i, (surface, domain) in enumerate(pending.items(), 1):
        results[surface] = ground_surface(wd, surface, domain)
        if i % 20 == 0 or i == len(pending):
            print(f"  grounded {i}/{len(pending)} ({wd.n_calls} live calls so far)")

    # 2. One batched EN-label/description lookup for every candidate qid
    #    across every surface (dedup across the whole run).
    all_qids: list[str] = []
    for r in results.values():
        for qid in r.get("_candidate_qids", []):
            if qid not in all_qids:
                all_qids.append(qid)
    label_map = enrich_labels(wd, all_qids)

    # 3. Materialize final enrichment payloads.
    final: dict[str, dict] = {}
    counts = {"exact_label": 0, "ambiguous_candidates": 0, "no_candidates": 0}
    for surface, r in results.items():
        resolved_by = r["resolved_by"]
        counts[resolved_by] = counts.get(resolved_by, 0) + 1
        candidates = []
        for qid in r.get("_candidate_qids", []):
            meta = label_map.get(qid) or {}
            by_qid = r["_by_qid"].get(qid, {})
            candidates.append({
                "qid": qid,
                "label": meta.get("label") or by_qid.get("label_ru") or qid,
                "description": meta.get("description") or by_qid.get("description") or "",
                "url": _entity_url(qid),
                **({"matched_via": "label_ru"} if r["_matched_via"].get(qid) else {}),
            })
        chosen_qid = r.get("_chosen_qid")
        label_en = None
        if chosen_qid:
            label_en = (label_map.get(chosen_qid) or {}).get("label")
        final[surface] = {
            "qid": chosen_qid,
            "label_en": label_en,
            "resolved_by": resolved_by,
            "candidates": candidates,
            "trace": r["trace"],
        }

    # 4. Fan out to every identified_terms entry with that surface, in place.
    n_filled = 0
    for row in rows:
        terminology = row.get("terminology") or {}
        for t in terminology.get("identified_terms") or []:
            surface = t.get("source_term", "")
            if surface and "resolved_by" not in t and surface in final:
                t.update(final[surface])
                n_filled += 1

    SEED_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8"
    )

    print(f"filled {n_filled} identified_terms entries across {len(final)} unique surfaces")
    print(f"resolved_by counts: {counts}")
    print(f"live Wikidata calls this run: {wd.n_calls}")


if __name__ == "__main__":
    main()
