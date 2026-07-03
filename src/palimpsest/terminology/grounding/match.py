"""Deterministic exact-label matching for the G6 label_first strategy.

``norm()`` folds a Russian label/query into a comparison key so that exact
matches survive incidental spelling/encoding noise (spec §3.2). ``exact_match``
tests a set of queries (typically lemma + surface) against a candidate list
under that key.
"""
from __future__ import annotations

import re
import unicodedata

# RU-Wikidata labels are inconsistent about ё/е, and hyphens in transliterated
# names ("Кадашман-Харбе") arrive as different Unicode codepoints depending on
# OCR/translation source. Folding both trades a theoretical false-merge (two
# distinct entities differing only by ё/е) for far fewer honest greens
# escalating to the judge — accepted knowingly as risk R7 (spec §11).
_DASH_RE = re.compile("[‐-―−]")
_WS_RE = re.compile(r"\s+")
_YO_MAP = str.maketrans({"ё": "е", "Ё": "Е"})


def norm(s: str) -> str:
    """Fold ``s`` into a comparison key: NFC, dash, ё/е, whitespace, case."""
    s = unicodedata.normalize("NFC", s)
    s = _DASH_RE.sub("-", s)
    s = s.translate(_YO_MAP)
    s = _WS_RE.sub(" ", s).strip()
    return s.casefold()


def exact_match(queries: list[str], candidates: list[dict], *, match_aliases: bool) -> list[dict]:
    """Return candidates whose label (or, if enabled, an alias) exact-matches a query.

    Each returned dict is the candidate plus a ``matched`` key:
    ``{"kind": "label_ru" | "alias_ru" | "alias_en", "value": ..., "query": ...}``.
    A label match always takes precedence over an alias match for the same
    candidate, regardless of query order.
    """
    normed_queries = [(q, norm(q)) for q in queries]
    hits = []
    for cand in candidates:
        matched = None
        label_ru = cand.get("label_ru")
        if label_ru:
            normed_label = norm(label_ru)
            for query, normed_query in normed_queries:
                if normed_query == normed_label:
                    matched = {"kind": "label_ru", "value": label_ru, "query": query}
                    break
        if matched is None and match_aliases:
            for kind, aliases_key in (("alias_ru", "aliases_ru"), ("alias_en", "aliases_en")):
                for alias in cand.get(aliases_key, []):
                    normed_alias = norm(alias)
                    for query, normed_query in normed_queries:
                        if normed_query == normed_alias:
                            matched = {"kind": kind, "value": alias, "query": query}
                            break
                    if matched:
                        break
                if matched:
                    break
        if matched:
            hits.append({**cand, "matched": matched})
    return hits
