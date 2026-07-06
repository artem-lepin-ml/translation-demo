"""Minimal live Wikidata client — stdlib only, polite, cached.

Etiquette (Wikidata API guidelines): a descriptive User-Agent, ``maxlag=5``
(parsed from the JSON body, not just the HTTP code), ``Retry-After``-honoring
backoff on 429/5xx (see ``_retry_after``), and a local JSONL cache so reruns
are fast and reproducible. No third-party dependency: everything goes through
``urllib``.
"""
from __future__ import annotations

import json
import re
import ssl
import threading
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

# Bound on concurrent live Wikidata network calls per client instance (politeness,
# ticket 002b/article-level parallelism): article workers share ONE WikidataClient
# so its cache is warm across articles, but concurrent cache-miss lookups from
# several article threads must not hammer the API unbounded. Deliberately
# separate from the in-memory cache lock below -- that lock only ever protects
# short dict/file operations, never a network round-trip.
DEFAULT_NETWORK_CONCURRENCY = 3


def _ssl_context() -> ssl.SSLContext:
    try:
        return ssl.create_default_context()
    except Exception:  # pragma: no cover - environment fallback
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


class WikidataClient:
    """Thread safety (ticket 002b): article-level parallelism shares ONE instance
    across concurrent article workers so the cache stays warm across articles.
    ``_cache_lock`` protects the in-memory dict and the cache-file append (both
    are short, in-process operations); it is NEVER held during a network
    round-trip. ``_network_sem`` bounds concurrent live HTTP calls separately
    (``DEFAULT_NETWORK_CONCURRENCY``, politeness) -- deliberately not the same
    lock as the cache, so cache hits/misses across threads never block on
    network I/O and multiple genuine cache misses can be in flight at once.
    """

    def __init__(self, cache_path: str | Path | None = None, timeout: int = 15,
                 network_concurrency: int = DEFAULT_NETWORK_CONCURRENCY) -> None:
        self.timeout = timeout
        self._ctx = _ssl_context()
        self.n_calls = 0  # network calls only (cache hits excluded) -- kept for existing callers
        # Usage counters (run-metadata evidence, wiki_eval.py meta.json "wikidata" block):
        # thread-safe under the same `_cache_lock` as `n_calls` -- lightweight bookkeeping
        # only, no behavior change to `_fetch`'s control flow.
        self.n_cache_hits = 0
        self.total_network_seconds = 0.0
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        self._network_sem = threading.Semaphore(network_concurrency)
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.open(encoding="utf-8"):
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    self._cache[rec["key"]] = rec["value"]

    @property
    def n_network_calls(self) -> int:
        """Alias of ``n_calls`` under the usage-counters' naming (meta.json's
        ``wikidata.calls``); kept as a property rather than a second counter
        so there is exactly one write site to stay consistent."""
        return self.n_calls

    # ── low-level ────────────────────────────────────────────────────────────
    def _fetch(self, base: str, params: dict) -> dict:
        params = {**params, "format": "json", "maxlag": "5"}
        key = base + "?" + urllib.parse.urlencode(sorted(params.items()))
        with self._cache_lock:
            if key in self._cache:
                self.n_cache_hits += 1
                return self._cache[key]
        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        # Cache miss -- do the network round-trip bounded by _network_sem, held
        # for the whole retry loop (including backoff sleeps) so at most
        # `network_concurrency` conversations with the API are ever open at once.
        # A thundering herd on an identical concurrent miss (two threads fetch
        # the same key before either has stored it) is accepted -- a redundant
        # fetch, not a correctness bug -- per the minimal-locking directive.
        with self._network_sem:
            for attempt in range(5):
                call_started = time.monotonic()
                try:
                    with self._cache_lock:
                        self.n_calls += 1
                    with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                        raw = resp.read()
                    data = json.loads(raw) if raw else {}
                except urllib.error.HTTPError as exc:  # 429/5xx → back off; other 4xx is deterministic
                    with self._cache_lock:
                        self.total_network_seconds += time.monotonic() - call_started
                    if (exc.code == 429 or exc.code >= 500) and attempt < 4:
                        time.sleep(_retry_after(exc.headers, attempt))
                        continue
                    raise
                except (json.JSONDecodeError, urllib.error.URLError) as exc:  # empty/malformed body, transient net
                    with self._cache_lock:
                        self.total_network_seconds += time.monotonic() - call_started
                    if attempt < 4:
                        time.sleep(min(5, 2 ** attempt))
                        continue
                    raise RuntimeError(f"Wikidata fetch failed after retries: {exc}") from exc
                with self._cache_lock:
                    self.total_network_seconds += time.monotonic() - call_started
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
        with self._cache_lock:
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
    """Backoff before retrying attempt N (0-based): the server's Retry-After
    when present, else an escalating 2s*(attempt+1) fallback -- and never LESS
    than that fallback even with a header, so consecutive 429s always slow us
    down further. Capped at 120s.

    History (2026-07-05 matrix canary crash): the original cap was 10s with a
    2**attempt fallback capped at 8s -- a sustained Wikidata 429 storm (their
    real Retry-After is often 60s+) blew through all 5 attempts in <40s and an
    exhausted-retries HTTPError killed the whole run. Honoring the server's
    figure (bounded) is both politer and the only thing that actually survives
    a storm.
    """
    fallback = 2.0 * (attempt + 1)
    raw = headers.get("Retry-After") if headers else None
    try:
        return min(120.0, max(float(raw), fallback))
    except (TypeError, ValueError):
        return min(120.0, fallback)
