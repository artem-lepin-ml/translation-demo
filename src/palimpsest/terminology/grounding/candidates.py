"""Shared Wikidata candidate generation for the G6 label_first strategy.

Search order, widening only when thin:

  1. ``wbsearchentities(lemma)`` — only if ``config.use_lemma`` and the lemma
     differs from the surface (Russian is heavily inflected; the nominative
     lemma recovers hits the inflected surface misses).
  2. ``wbsearchentities(surface)``
  3. if 0 hits total and ``config.use_cirrus``: CirrusSearch full-text
     (``list=search``) over both forms — recovers inflected/rare terms the
     prefix search misses.
  4. if still 0 and ``config.use_sitelink``: Wikipedia RU-title → Wikidata
     item — last resort for historicisms. Independently gatable from rung 3
     because it shares its title->QID mapping with the wiki-eval reference
     annotations (evaluation circularity, see docs/stages/wiki-eval.md).

Every search call is logged to ``queries`` (feeds ``GroundingTrace`` v1).
Candidates are enriched, redirect-canonicalised, and returned as plain dicts
plus a ``canon_by_qid`` map of canonical EN forms for pairing. No type
filtering: the judge disambiguates from the description text instead of a
type blocklist (spec D3/Q1).
"""
from __future__ import annotations

from ..base import GroundingConfig, TermMention
from ..wikidata import (
    WikidataClient,
    aliases_of,
    canonical_en_forms,
    label_of,
)


def _description(entity: dict, lang: str = "en") -> str:
    return entity.get("descriptions", {}).get(lang, {}).get("value", "")


def generate_candidates(wd: WikidataClient, mention: TermMention,
                         config: GroundingConfig = GroundingConfig()) -> dict:
    """Return ``{candidates, canon_by_qid, source, n_hits, queries}`` for a mention.

    ``candidates`` is a list of ``{qid, label_ru, label_en, description,
    aliases_ru, aliases_en}`` dicts in search-rank order, insertion-order
    deduplicated by QID (a documented determinism invariant — spec §3.1, not
    an implementation accident).
    """
    queries: list[dict] = []

    forms, seen_form = [], set()
    if config.use_lemma and mention.lemma and mention.lemma != mention.surface:
        forms.append(mention.lemma)
    if mention.surface not in forms:
        forms.append(mention.surface)
    forms = [f for f in forms if f and not (f in seen_form or seen_form.add(f))]

    hits, seen_qid = [], set()
    for q in forms:
        results = wd.search_entities(q, lang=mention.lang, limit=config.search_limit)
        queries.append({"q": q, "kind": "lemma" if q == mention.lemma else "surface",
                         "mechanism": "wbsearchentities", "n_hits": len(results)})
        for h in results:
            if h["id"] not in seen_qid:
                seen_qid.add(h["id"])
                hits.append(h)

    source = "wbsearchentities" if hits else "none"
    if not hits and config.use_cirrus:  # prefix search missed entirely → full-text CirrusSearch recovers inflected/rare terms
        for q in forms:
            results = wd.search_cirrus(q, limit=config.search_limit)
            queries.append({"q": q, "kind": "lemma" if q == mention.lemma else "surface",
                             "mechanism": "cirrus", "n_hits": len(results)})
            for h in results:
                if h["id"] not in seen_qid:
                    seen_qid.add(h["id"])
                    hits.append(h)
        if hits:
            source = "cirrus"
    if not hits and config.use_sitelink:  # last resort: RU Wikipedia page → Wikidata item
        wiki_title = mention.lemma or mention.surface
        qid = wd.wikipedia_wikibase_item(wiki_title, lang=mention.lang)
        queries.append({"q": wiki_title, "kind": "lemma" if wiki_title == mention.lemma else "surface",
                         "mechanism": "wikipedia_wikibase_item", "n_hits": 1 if qid else 0})
        if qid:
            hits, source = [{"id": qid}], "wikipedia_langlink"

    if not hits:
        return {"candidates": [], "canon_by_qid": {}, "source": "none", "n_hits": 0, "queries": queries}

    qids = [h["id"] for h in hits[:config.enrich_top]]
    entities = wd.get_entities(qids)
    candidates: list[dict] = []
    canon_by_qid: dict[str, list[str]] = {}
    for qid in qids:
        ent = entities.get(qid)
        if not ent:
            continue
        cqid = ent.get("id", qid)  # canonicalise redirects to the target QID
        candidates.append({
            "qid": cqid,
            "label_ru": label_of(ent, "ru"),
            "label_en": label_of(ent, "en"),
            "description": _description(ent, "en") or _description(ent, "ru"),
            "aliases_ru": aliases_of(ent, "ru"),
            "aliases_en": aliases_of(ent, "en"),
        })
        canon_by_qid[cqid] = canonical_en_forms(ent)
    return {"candidates": candidates, "canon_by_qid": canon_by_qid,
            "source": source, "n_hits": len(hits), "queries": queries}
