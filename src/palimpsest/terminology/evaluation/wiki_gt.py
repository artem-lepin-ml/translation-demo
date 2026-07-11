"""Wiki ground-truth builder (W3): Parsoid fetch, anchor->QID GT tuples,
chronology filter.

Corpus selection lives in scripts/select_wiki_corpus.py (corpus selection).

See docs/superpowers/specs/2026-07-03-wiki-eval-design.md E-D5..E-D8,
E-D17 and Sec.11 for the pinned contracts this module implements.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from palimpsest.terminology.evaluation.tokenize import (
    _UNICODE_SPACE_RE,
    _is_dropped,
    char_to_token_index,
    flatten,
    tokens,
)
from palimpsest.terminology.wikidata import USER_AGENT, WIKIPEDIA_API, _ssl_context

REST_HTML_URL = "https://ru.wikipedia.org/api/rest_v1/page/html/{title}"

# E-D8 / Sec.11: closed, versioned chronology P31 exclusion set.
CHRONO_P31_VERSION = "chrono_p31_v1"
CHRONO_P31_QIDS = frozenset(
    {
        "Q3186692",  # calendar year
        "Q39911",  # decade
        "Q578",  # century
        "Q3311614",  # millennium
        "Q29964144",  # year BC
        "Q14795564",  # point in time / date
        "Q18340514",  # events in a specific year or time period
    }
)

# Brackets that visually "attach" a glyph to its neighbour even though bracket
# chars are punctuation, not letters/digits/marks (e.g. the "ə" in "(ə)").
_ATTACHING_BRACKETS = frozenset("()[]{}⟨⟩«»<>")

# Wikipedia namespace prefixes that never denote a main-namespace article.
_NON_MAIN_PREFIXES = (
    "Category:", "File:", "Template:", "Help:", "Wikipedia:", "Talk:",
    "User:", "Portal:", "Special:", "Media:", "MediaWiki:", "Module:",
    "Служебная:", "Категория:", "Файл:", "Шаблон:", "Справка:", "Википедия:",
    "Обсуждение:", "Участник:", "Портал:",
)


class WikiFetchError(Exception):
    """Raised when a Parsoid/REST fetch fails after retries (E-D17)."""


@dataclass
class GtCounters:
    n_anchors: int = 0
    n_no_qid: int = 0
    n_redlink: int = 0
    n_excluded_chrono: int = 0
    n_excluded_nonmain: int = 0
    n_excluded_symbol: int = 0

    def as_dict(self) -> dict:
        return {
            "n_anchors": self.n_anchors,
            "n_no_qid": self.n_no_qid,
            "n_redlink": self.n_redlink,
            "n_excluded_chrono": self.n_excluded_chrono,
            "n_excluded_nonmain": self.n_excluded_nonmain,
            "n_excluded_symbol": self.n_excluded_symbol,
        }


@dataclass
class AnchorTarget:
    """Auditability record for one extracted anchor (E-D7)."""

    surface: str
    anchor_target_title: str
    canonical_title: str | None
    qid: str | None


@dataclass
class ExtractResult:
    tuples: list[tuple[int, str, str, int]] = field(default_factory=list)
    counters: GtCounters = field(default_factory=GtCounters)
    anchor_targets: list[AnchorTarget] = field(default_factory=list)


# ── HTML fetch (E-D5) ───────────────────────────────────────────────────────


def fetch_html(title: str, cache_dir: str | Path, *, timeout: int = 15, retries: int = 5) -> str:
    """GET Parsoid/REST HTML for `title`, caching to `<cache_dir>/<safe-title>.html`.

    Cache hit reads from disk with zero network. Raises WikiFetchError after
    exhausting retries on transient failure (E-D17).
    """
    cache_path = Path(cache_dir) / f"{_safe_filename(title)}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    url = REST_HTML_URL.format(title=urllib.parse.quote(title.replace(" ", "_"), safe=""))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = _ssl_context()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                html = resp.read().decode("utf-8")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(html, encoding="utf-8")
            return html
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(min(5, 2**attempt))
                continue
    raise WikiFetchError(f"fetch failed for {title!r} after {retries} attempts: {last_exc}")


def _safe_filename(title: str) -> str:
    return re.sub(r"[^\w\-.]", "_", title, flags=re.UNICODE)


# ── anchor extraction (E-D6, E-D7, E-D8) ────────────────────────────────────


def _is_main_namespace_href(href: str) -> bool:
    if not href:
        return False
    if href.startswith(("http://", "https://", "//")):
        return False
    title = _title_from_href(href)
    if title is None:
        return False
    return not any(title.startswith(prefix) for prefix in _NON_MAIN_PREFIXES)


def _title_from_href(href: str) -> str | None:
    if href.startswith("./"):
        raw = href[2:]
    elif href.startswith("/wiki/"):
        raw = href[len("/wiki/") :]
    else:
        return None
    raw = raw.split("#", 1)[0]
    return urllib.parse.unquote(raw).replace("_", " ")


def _attaches(ch: str) -> bool:
    return unicodedata.category(ch)[0] in ("L", "N", "M") or ch in _ATTACHING_BRACKETS


def _is_symbol_fragment(text: str, pos: int, surface: str) -> bool:
    """A single-char anchor glued into a larger token (IPA/translit/nav glyph).

    Ru-wiki IPA/transcription templates link every phoneme/diacritic to its
    own article, so a naive per-`<a>` walk mistakes each glyph for a gold
    mention. Distinguish those from legit standalone single-char anchors
    (e.g. "У", or "V" in "V век") by checking whether `surface` has a
    non-space neighbour glued to it in `text` at `pos`.
    """
    if len(surface.strip()) != 1:
        return False
    before = text[pos - 1] if pos > 0 else " "
    after = text[pos + len(surface)] if pos + len(surface) < len(text) else " "
    return _attaches(before) or _attaches(after)


def extract_gt(
    html: str,
    title_to_qid: dict[str, dict | None],
    *,
    p31_of: Callable[[str], set[str]] | None = None,
) -> ExtractResult:
    """Extract GT tuples from anchors in `html`.

    `title_to_qid` maps anchor target title -> {"qid": ..., "canonical_title": ...}
    or None (redlink / no entry). `p31_of(qid) -> set[str]` supplies target P31
    values for the chronology filter (E-D8); defaults to "no P31 info" (empty set).
    """
    if p31_of is None:
        p31_of = lambda _qid: set()  # noqa: E731

    text = flatten(html)

    soup = BeautifulSoup(html, "lxml")
    for tag in list(soup.find_all(True)):
        if tag.decomposed:
            continue
        if _is_dropped(tag):
            tag.decompose()

    result = ExtractResult()

    # Walk paragraphs in document order, tracking a running char offset into
    # `text` (paragraphs are joined by "\n" in flatten()) so anchor surface
    # text maps to the correct global token index. Re-run the same NFC/space
    # normalization flatten() applies to each paragraph's raw text, so the
    # offset search below lines up with `text`.
    offset = 0
    for p in soup.find_all("p"):
        p_text = _UNICODE_SPACE_RE.sub(" ", unicodedata.normalize("NFC", p.get_text()))

        anchors = p.find_all("a")
        cursor = offset  # search position within `text` for this paragraph
        for a in anchors:
            surface_raw = a.get_text()
            surface = _UNICODE_SPACE_RE.sub(" ", unicodedata.normalize("NFC", surface_raw))
            if not surface.strip():
                continue
            href = a.get("href", "")

            char_pos = text.find(surface, cursor)
            if char_pos == -1:
                char_pos = text.find(surface, offset)
            if char_pos == -1:
                continue  # surface not found in flattened text; skip defensively

            if _is_symbol_fragment(text, char_pos, surface):
                result.counters.n_excluded_symbol += 1
                cursor = char_pos + len(surface)
                continue

            if not _is_main_namespace_href(href):
                result.counters.n_excluded_nonmain += 1
                cursor = char_pos + len(surface)
                continue

            result.counters.n_anchors += 1
            target_title = _title_from_href(href)
            entry = title_to_qid.get(target_title)

            if entry is None:
                result.counters.n_redlink += 1
                result.anchor_targets.append(
                    AnchorTarget(surface, target_title or "", None, None)
                )
                cursor = char_pos + len(surface)
                continue

            qid = entry.get("qid")
            canonical_title = entry.get("canonical_title", target_title)
            if not qid:
                result.counters.n_no_qid += 1
                result.anchor_targets.append(
                    AnchorTarget(surface, target_title or "", canonical_title, None)
                )
                cursor = char_pos + len(surface)
                continue

            if p31_of(qid) & CHRONO_P31_QIDS:
                result.counters.n_excluded_chrono += 1
                result.anchor_targets.append(
                    AnchorTarget(surface, target_title or "", canonical_title, qid)
                )
                cursor = char_pos + len(surface)
                continue

            token_index = char_to_token_index(text, char_pos)
            span_len = len(tokens(surface))
            result.tuples.append((token_index, surface, qid, span_len))
            result.anchor_targets.append(
                AnchorTarget(surface, target_title or "", canonical_title, qid)
            )
            cursor = char_pos + len(surface)

        offset += len(p_text) + 1  # +1 for the "\n" flatten() inserts

    result.tuples.sort(key=lambda t: (t[0], t[1], t[2]))
    return result


# ── title -> QID batched mapping (E-D7) ─────────────────────────────────────

_MAX_REDIRECT_HOPS = 10


def _follow_redirect_chain(title: str, redirects: dict[str, str]) -> str:
    """Follow `redirects` (from -> to, one hop per map entry) to a fixed point.

    A double (or longer) redirect A->B->C is only resolved one hop by a
    single `.get()` lookup; this loops until no further hop exists, with a
    depth guard against cycles (MediaWiki forbids redirect cycles, but a
    stale/partial `redirects` map from the API could still loop).
    """
    seen = {title}
    resolved = title
    for _ in range(_MAX_REDIRECT_HOPS):
        nxt = redirects.get(resolved)
        if nxt is None or nxt in seen:
            break
        resolved = nxt
        seen.add(resolved)
    return resolved


def titles_to_qids(
    titles: Iterable[str], *, lang: str = "ru", timeout: int = 15, retries: int = 5
) -> dict[str, dict | None]:
    """Own batched pageprops fetcher: ≤50 pipe-joined titles per call.

    Returns {title: {"qid": ..., "canonical_title": ...} | None}. None means
    the title has no page (redlink). A page without a wikibase_item maps to
    {"qid": None, "canonical_title": ...}.
    """
    titles = list(dict.fromkeys(titles))  # de-dup, preserve order
    out: dict[str, dict | None] = {}
    ctx = _ssl_context()
    base = WIKIPEDIA_API.format(lang=lang)

    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        params = {
            "action": "query",
            "prop": "pageprops",
            "ppprop": "wikibase_item",
            "titles": "|".join(batch),
            "redirects": "1",
            "format": "json",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        data: dict = {}
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    data = json.loads(resp.read())
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(min(5, 2**attempt))
                    continue
        else:
            raise WikiFetchError(f"pageprops batch failed after {retries} attempts: {last_exc}")

        query = data.get("query", {})
        redirects = {r["from"]: r["to"] for r in query.get("redirects", [])}
        normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
        pages = query.get("pages", {})

        canonical_by_title: dict[str, str] = {}
        qid_by_canonical: dict[str, str | None] = {}
        for page in pages.values():
            page_title = page.get("title", "")
            qid = page.get("pageprops", {}).get("wikibase_item")
            is_missing = "missing" in page
            qid_by_canonical[page_title] = None if is_missing else qid

        for orig in batch:
            resolved = normalized.get(orig, orig)
            resolved = _follow_redirect_chain(resolved, redirects)
            canonical_by_title[orig] = resolved

        for orig in batch:
            canonical = canonical_by_title[orig]
            if canonical not in qid_by_canonical:
                out[orig] = None
                continue
            qid = qid_by_canonical[canonical]
            if qid is None and canonical not in pages_present(pages):
                out[orig] = None
                continue
            out[orig] = {"qid": qid, "canonical_title": canonical}

    return out


def pages_present(pages: dict) -> set[str]:
    return {p.get("title", "") for p in pages.values() if "missing" not in p}


def memoized_titles_to_qids(
    titles_to_qids_fn: Callable[..., dict[str, dict | None]] = titles_to_qids,
) -> Callable[[Iterable[str]], dict[str, dict | None]]:
    """Wrap `titles_to_qids_fn` in an in-memory cache keyed by title.

    `cmd_build_gt` and `build_gt` itself both need the anchor-title -> QID
    mapping for every article; without this wrapper each resolves the same
    anchor titles independently, doubling network traffic (spec: build-gt
    should call the batch fetcher once per title and reuse). Only titles not
    yet cached are fetched on each call.
    """
    cache: dict[str, dict | None] = {}

    def wrapped(titles: Iterable[str]) -> dict[str, dict | None]:
        titles = list(dict.fromkeys(titles))
        missing = [t for t in titles if t not in cache]
        if missing:
            cache.update(titles_to_qids_fn(missing))
        return {t: cache[t] for t in titles}

    return wrapped


# ── orchestration ────────────────────────────────────────────────────────────


def build_gt(
    titles: dict[str, str],
    cache_dir: str | Path,
    out_path: str | Path,
    *,
    stratum_of: Callable[[str], str] | None = None,
    p31_of: Callable[[str], set[str]] | None = None,
    fetch_fn: Callable[[str, str | Path], str] = fetch_html,
    titles_to_qids_fn: Callable[..., dict[str, dict | None]] = titles_to_qids,
) -> dict:
    """Orchestrate fetch -> extract -> serialize `gt.jsonl` + a build-level summary.

    `titles` maps article title -> its own QID (article page's Wikidata item).
    Fails loud if the fetch/parse failure rate exceeds 10% (E-D17 / spec Sec.3.1).

    Returns the build-level summary dict (also written to
    `<out_path>.summary.json`): `n_fetch_failed` (Parsoid/REST fetch failed
    after retries) and `n_malformed_html` (fetch succeeded but produced no
    tokens) are counted as DISTINCT counters per E-D17 -- conflating a
    transient network failure with a permanent malformed-page fact would hide
    reproducibility risk, per the spec.
    """
    stratum_of = stratum_of or (lambda _t: "typical")

    records = []
    n_fetch_failed = 0
    n_malformed_html = 0
    n_title_to_qid_failed = 0
    sorted_titles = sorted(titles.keys())

    for title in sorted_titles:
        try:
            html = fetch_fn(title, cache_dir)
        except WikiFetchError:
            n_fetch_failed += 1
            continue

        text = flatten(html)
        flat_tokens = tokens(text)
        if not flat_tokens:
            n_malformed_html += 1
            continue

        anchor_titles = sorted(_collect_anchor_titles(html))
        if anchor_titles:
            try:
                title_to_qid = titles_to_qids_fn(anchor_titles)
            except WikiFetchError:
                # Transient batch failure (spec Sec.3.1): exclude just this
                # article, count separately, never abort the whole run.
                n_title_to_qid_failed += 1
                continue
        else:
            title_to_qid = {}

        extracted = extract_gt(html, title_to_qid, p31_of=p31_of)

        records.append(
            {
                "title": title,
                "qid": titles[title],
                "stratum": stratum_of(title),
                "tokens": flat_tokens,
                "gt_tuples": [list(t) for t in extracted.tuples],
                "counters": extracted.counters.as_dict(),
                "chrono_p31_version": CHRONO_P31_VERSION,
                "chrono_p31_hash": _chrono_p31_hash(),
            }
        )

    total = len(sorted_titles)
    n_failed = n_fetch_failed + n_malformed_html + n_title_to_qid_failed
    if total and n_failed / total > 0.10:
        raise WikiFetchError(
            f"fetch/parse failure rate {n_failed}/{total} exceeds 10% threshold "
            f"(n_fetch_failed={n_fetch_failed}, n_malformed_html={n_malformed_html}, "
            f"n_title_to_qid_failed={n_title_to_qid_failed})"
        )

    records.sort(key=lambda r: r["title"])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "n_titles": total,
        "n_articles_written": len(records),
        "n_fetch_failed": n_fetch_failed,
        "n_malformed_html": n_malformed_html,
        "n_title_to_qid_failed": n_title_to_qid_failed,
    }
    summary_path = out_path.with_name(out_path.name + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    return summary


def _collect_anchor_titles(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    out: set[str] = set()
    for p in soup.find_all("p"):
        for a in p.find_all("a"):
            href = a.get("href", "")
            if _is_main_namespace_href(href):
                title = _title_from_href(href)
                if title:
                    out.add(title)
    return out


def _chrono_p31_hash() -> str:
    return hashlib.sha256(",".join(sorted(CHRONO_P31_QIDS)).encode("utf-8")).hexdigest()[:16]
