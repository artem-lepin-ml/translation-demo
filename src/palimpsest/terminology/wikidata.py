"""Minimal live Wikidata client — stdlib only, polite, cached.

Etiquette (Wikidata API guidelines): a descriptive User-Agent, ``maxlag=5``
(parsed from the JSON body, not just the HTTP code), ``Retry-After`` on 429/503,
and a local JSONL cache so reruns are fast and reproducible. No third-party
dependency: everything goes through ``urllib``.
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"
USER_AGENT = (
    "Palimpsest-terminology/1.0 "
    "(https://github.com/palimpsest; a.lepin.student@gmail.com) python-urllib"
)

# Type QIDs to drop as grounding noise.
DISAMBIGUATION = "Q4167410"
SCHOLARLY_ARTICLE = "Q13442814"

# Anachronistic senses that cannot appear in an ancient/historical text. Dropping
# them removes the classic "top search hit is a modern football club / band"
# error (e.g. Спарта → "AC Sparta Prague" instead of the ancient city-state).
ANACHRONISTIC_TYPES = {
    "Q476028",    # association football club
    "Q215380",    # musical group
    "Q2088357",   # musical ensemble
    "Q11424",     # film
    "Q482994",    # album
    "Q7889",      # video game
    "Q4830453",   # business
    "Q891723",    # public company
    "Q431289",    # brand
    "Q1616075",   # television station
    "Q41298",     # magazine
    "Q3918",      # university (modern institution)
    "Q57305",     # railway station
    "Q1420",      # motor car
}


def _ssl_context() -> ssl.SSLContext:
    try:
        return ssl.create_default_context()
    except Exception:  # pragma: no cover - environment fallback
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


class WikidataClient:
    def __init__(self, cache_path: str | Path | None = None, timeout: int = 15) -> None:
        self.timeout = timeout
        self._ctx = _ssl_context()
        self.n_calls = 0  # network calls only (cache hits excluded)
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.open(encoding="utf-8"):
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    self._cache[rec["key"]] = rec["value"]

    # ── low-level ────────────────────────────────────────────────────────────
    def _fetch(self, base: str, params: dict) -> dict:
        params = {**params, "format": "json", "maxlag": "5"}
        key = base + "?" + urllib.parse.urlencode(sorted(params.items()))
        if key in self._cache:
            return self._cache[key]
        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(5):
            try:
                self.n_calls += 1
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    raw = resp.read()
                data = json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:  # 429/503 → back off
                if exc.code in (429, 503) and attempt < 4:
                    time.sleep(_retry_after(exc.headers, attempt))
                    continue
                raise
            except (json.JSONDecodeError, urllib.error.URLError) as exc:  # empty/malformed body, transient net
                if attempt < 4:
                    time.sleep(min(5, 2 ** attempt))
                    continue
                raise RuntimeError(f"Wikidata fetch failed after retries: {exc}") from exc
            # maxlag returns HTTP 200 with an error body — retry, and NEVER cache an error
            if isinstance(data, dict) and data.get("error"):
                if data["error"].get("code") == "maxlag" and attempt < 4:
                    time.sleep(min(5, 2 ** attempt))
                    continue
                raise RuntimeError(f"Wikidata API error: {data['error']}")
            self._store(key, data)
            return data
        raise RuntimeError("Wikidata fetch exhausted retries without a response")

    def _store(self, key: str, value: dict) -> None:
        self._cache[key] = value
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")

    # ── API surface ──────────────────────────────────────────────────────────
    def search_entities(self, term: str, lang: str = "ru", limit: int = 7) -> list[dict]:
        """wbsearchentities — candidate generation in the source language."""
        data = self._fetch(
            API,
            {"action": "wbsearchentities", "search": term, "language": lang,
             "uselang": lang, "type": "item", "limit": str(limit)},
        )
        return data.get("search", [])

    def search_cirrus(self, term: str, limit: int = 7) -> list[dict]:
        """Full-text CirrusSearch fallback.

        ``wbsearchentities`` is prefix-only over labels/aliases, so it misses
        inflected forms and terms that only appear mid-label. CirrusSearch
        (``list=search``) does a full-text match over the whole item, recovering
        rare historicisms the prefix search drops. Returns ``[{"id": qid}]`` in
        relevance order, shaped like ``search_entities`` for a uniform merge.
        """
        data = self._fetch(
            API,
            {"action": "query", "list": "search", "srsearch": term, "srlimit": str(limit)},
        )
        return [{"id": s["title"]} for s in data.get("query", {}).get("search", [])
                if s.get("title", "").startswith("Q")]

    def get_entities(self, qids: list[str], props: str = "labels|aliases|descriptions|claims|sitelinks",
                     languages: str = "en|ru") -> dict[str, dict]:
        """wbgetentities — enrich QIDs in batches of ≤50."""
        out: dict[str, dict] = {}
        for i in range(0, len(qids), 50):
            batch = qids[i:i + 50]
            data = self._fetch(
                API,
                {"action": "wbgetentities", "ids": "|".join(batch),
                 "props": props, "languages": languages},
            )
            out.update(data.get("entities", {}))
        return out

    def wikipedia_wikibase_item(self, title: str, lang: str = "ru") -> str | None:
        """Follow a Wikipedia page to its Wikidata QID via pageprops."""
        data = self._fetch(
            WIKIPEDIA_API.format(lang=lang),
            {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
             "titles": title, "redirects": "1"},
        )
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                return qid
        return None


# ── entity helpers (pure) ─────────────────────────────────────────────────────
def instance_and_subclass_of(entity: dict) -> list[str]:
    """P31 (instance of) + P279 (subclass of) target QIDs."""
    out: list[str] = []
    claims = entity.get("claims", {})
    for prop in ("P31", "P279"):
        for claim in claims.get(prop, []):
            snak = claim.get("mainsnak", {})
            if snak.get("snaktype") != "value":
                continue  # somevalue/novalue → skip
            dv = snak.get("datavalue", {}).get("value", {})
            qid = dv.get("id")
            if qid:
                out.append(qid)
    return out


def label_of(entity: dict, lang: str = "en") -> str | None:
    return entity.get("labels", {}).get(lang, {}).get("value")


def aliases_of(entity: dict, lang: str = "en") -> list[str]:
    return [a["value"] for a in entity.get("aliases", {}).get(lang, [])]


def sitelink_title(entity: dict, wiki: str = "enwiki") -> str | None:
    return entity.get("sitelinks", {}).get(wiki, {}).get("title")


# Common nouns that must never become a standalone pairing form (would false-match
# "Kingdom of Sumer" → "Kingdom"). Short forms are only derived for name-like labels.
_COMMON_HEAD = {
    "kingdom", "empire", "city", "state", "republic", "dynasty", "war", "battle",
    "sea", "river", "mountain", "gulf", "region", "province", "peace", "treaty",
    "league", "union", "confederacy", "culture", "period", "lament", "laws", "law",
}


def _short_form(name: str) -> str | None:
    """Derive a plain name from a full label: 'Sargon of Akkad' → 'Sargon'."""
    head = re.split(r"\s+(?:of|the|son|daughter|and)\s+|,\s*", name, maxsplit=1)[0].strip()
    head = re.sub(r"\s+(?:[IVXLC]+|[A-Z])$", "", head).strip()  # drop regnal numeral
    if head and head != name and head.lower() not in _COMMON_HEAD and re.search(r"[A-Za-z]", head):
        return head
    return None


def canonical_en_forms(entity: dict) -> list[str]:
    """Ordered, de-duplicated Latin-script EN strings for pairing/location.

    Includes label + EN aliases + enwiki title, plus a derived short form for
    name-like labels so 'Sargon of Akkad' also matches a translation's 'Sargon'.
    Non-Latin aliases (e.g. cuneiform) are dropped.
    """
    forms: list[str] = []
    raw = [label_of(entity, "en"), *aliases_of(entity, "en"), sitelink_title(entity, "enwiki")]
    for value in raw:
        if value and re.search(r"[A-Za-z]", value) and value not in forms:
            forms.append(value)
    label = label_of(entity, "en") or sitelink_title(entity, "enwiki") or ""
    short = _short_form(label)
    if short and short not in forms:
        forms.append(short)
    return forms


def _retry_after(headers, attempt: int) -> float:
    raw = headers.get("Retry-After") if headers else None
    try:
        return min(10.0, float(raw))
    except (TypeError, ValueError):
        return min(8.0, 2 ** attempt)
