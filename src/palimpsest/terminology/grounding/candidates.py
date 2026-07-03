"""Shared Wikidata candidate generation for grounding strategies.

Every grounding strategy uses this one path, so api_first, llm_judge and hybrid
see identical candidate sets and the tournament is a fair comparison. Search
order, widening only when thin:

  1. ``wbsearchentities`` (prefix over labels/aliases, source language)
  2. CirrusSearch full-text (``list=search``) — recovers inflected/rare terms the
     prefix search misses (the main lever against a high red rate)
  3. Wikipedia RU-title → Wikidata item — last resort for historicisms

Candidates are enriched, type-filtered, redirect-canonicalised, and returned as
plain dicts plus a ``canon_by_qid`` map of canonical EN forms for pairing.
"""
from __future__ import annotations

from ..base import TermMention
from ..verdict import passes_type_filter
from ..wikidata import (
    WikidataClient,
    aliases_of,
    canonical_en_forms,
    instance_and_subclass_of,
    label_of,
    sitelink_title,
)


def _description(entity: dict, lang: str = "en") -> str:
    return entity.get("descriptions", {}).get(lang, {}).get("value", "")


def generate_candidates(wd: WikidataClient, mention: TermMention, *,
                        search_limit: int = 7, enrich_top: int = 5) -> dict:
    """Return ``{candidates, canon_by_qid, source, n_hits}`` for a mention.

    ``candidates`` is a list of ``{qid, label, description, aliases, types,
    notable}`` dicts in search-rank order, already type-filtered.
    """
    # Russian is heavily inflected: search the nominative lemma first, then the
    # exact surface. Search is cached, so probing both forms is free on reruns.
    queries, seen_q = [], set()
    for q in (mention.lemma, mention.surface):
        if q and q not in seen_q:
            seen_q.add(q)
            queries.append(q)

    hits, seen_qid = [], set()
    for q in queries:
        for h in wd.search_entities(q, lang=mention.lang, limit=search_limit):
            if h["id"] not in seen_qid:
                seen_qid.add(h["id"])
                hits.append(h)

    source = "wbsearchentities" if hits else "none"
    if not hits:  # prefix search missed entirely → full-text CirrusSearch recovers inflected/rare terms
        for q in queries:
            for h in wd.search_cirrus(q, limit=search_limit):
                if h["id"] not in seen_qid:
                    seen_qid.add(h["id"])
                    hits.append(h)
        if hits:
            source = "cirrus"
    if not hits:  # last resort: RU Wikipedia page → Wikidata item
        qid = wd.wikipedia_wikibase_item(mention.lemma or mention.surface, lang=mention.lang)
        if qid:
            hits, source = [{"id": qid}], "wikipedia_langlink"

    if not hits:
        return {"candidates": [], "canon_by_qid": {}, "source": "none", "n_hits": 0}

    qids = [h["id"] for h in hits[:enrich_top]]
    entities = wd.get_entities(qids)
    candidates: list[dict] = []
    canon_by_qid: dict[str, list[str]] = {}
    for qid in qids:
        ent = entities.get(qid)
        if not ent:
            continue
        cqid = ent.get("id", qid)  # canonicalise redirects to the target QID
        types = instance_and_subclass_of(ent)
        if not passes_type_filter(types):
            continue
        ru_label = label_of(ent, "ru")
        candidates.append({
            "qid": cqid,
            "label": label_of(ent, "en") or ru_label or mention.surface,
            "description": _description(ent, "en") or _description(ent, "ru"),
            # exact-match set: RU label is the primary name to match the RU surface/lemma,
            # plus RU+EN aliases. Without the RU label, clear greens fall to yellow.
            "aliases": ([ru_label] if ru_label else []) + aliases_of(ent, "ru") + aliases_of(ent, "en"),
            "types": types,
            "notable": bool(sitelink_title(ent, "enwiki")),
        })
        canon_by_qid[cqid] = canonical_en_forms(ent)
    return {"candidates": candidates, "canon_by_qid": canon_by_qid,
            "source": source, "n_hits": len(hits)}
