#!/usr/bin/env python3
"""Export the 100-article wiki corpus to Danil's flat-array translation
pipeline input format, plus a sidecar index and a stratified pilot selection.

Spec: docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md Sec.2/4 (Ph-1
item 1). Reads data/eval/wiki/titles.txt + the cached Parsoid HTML under
data/eval/wiki/pages/ the same way the wiki-eval harness does (`_safe_filename`
+ `flatten()`, see docs/reports/python-pro-wiki-corpus-cleanliness-check.md for
the prior read-only audit that established the 2 553-paragraph baseline this
script hard-asserts against).

Writes (all under data/eval/wiki/, none of it committed by this script):
  wiki_original.json  -- flat JSON array of paragraph strings, matching the
                          serialization style of bouquet_original.json.
  wiki_index.json     -- sidecar array of {i, title, section, par_idx,
                          n_tokens}, same length/order as wiki_original.json.
  pilot_articles.json -- 10-article stratified pilot (Sec.4 Ph1) + a
                          5-paragraph smoke subset.

Run: uv run python scripts/export_wiki_corpus.py
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from palimpsest.terminology.evaluation.tokenize import flatten, tokens  # noqa: E402
from palimpsest.terminology.evaluation.wiki_gt import _safe_filename  # noqa: E402

DEFAULT_TITLES = ROOT / "data/eval/wiki/titles.txt"
DEFAULT_CACHE = ROOT / "data/eval/wiki/pages"
DEFAULT_OUT_DIR = ROOT / "data/eval/wiki"
DEFAULT_BOUQUET = ROOT / "external/gse-translation/data/bouquet/bouquet_original.json"

EXPECTED_N_ARTICLES = 100
EXPECTED_N_PARAGRAPHS = 2553
MARKER = "[источник не указан"
N_DECILES = 10


@dataclass
class Article:
    title: str
    section: str
    paragraphs: list[str] = field(default_factory=list)

    @property
    def n_paragraphs(self) -> int:
        return len(self.paragraphs)

    @property
    def n_tokens(self) -> int:
        return sum(len(tokens(p)) for p in self.paragraphs)


def load_titles(titles_path: Path) -> list[tuple[str, str]]:
    """Parse `title<TAB>section` lines, in file order."""
    lines = titles_path.read_text(encoding="utf-8").splitlines()
    rows = [tuple(line.split("\t", 1)) for line in lines if line.strip()]
    return rows  # type: ignore[return-value]


def load_article(title: str, section: str, cache_dir: Path) -> Article:
    """Resolve `title`'s cached HTML via the exact wiki_gt._safe_filename
    convention, flatten it, and keep only non-empty paragraphs."""
    html_path = cache_dir / f"{_safe_filename(title)}.html"
    if not html_path.exists():
        raise FileNotFoundError(f"no cached HTML for {title!r} at {html_path}")
    html = html_path.read_text(encoding="utf-8")
    text = flatten(html)
    paragraphs = [p for p in text.split("\n") if p]
    return Article(title=title, section=section, paragraphs=paragraphs)


def build_corpus(titles_path: Path, cache_dir: Path) -> list[Article]:
    rows = load_titles(titles_path)
    if len(rows) != EXPECTED_N_ARTICLES:
        raise AssertionError(f"expected {EXPECTED_N_ARTICLES} titles, got {len(rows)}")

    articles = [load_article(title, section, cache_dir) for title, section in rows]

    n_total = sum(a.n_paragraphs for a in articles)
    if n_total != EXPECTED_N_PARAGRAPHS:
        raise AssertionError(
            f"expected {EXPECTED_N_PARAGRAPHS} non-empty paragraphs, got {n_total}"
        )
    if len(articles) != EXPECTED_N_ARTICLES:
        raise AssertionError(f"expected {EXPECTED_N_ARTICLES} articles found, got {len(articles)}")
    return articles


def build_original_and_index(articles: list[Article]) -> tuple[list[str], list[dict]]:
    original: list[str] = []
    index: list[dict] = []
    i = 0
    for article in articles:
        for par_idx, paragraph in enumerate(article.paragraphs):
            original.append(paragraph)
            index.append(
                {
                    "i": i,
                    "title": article.title,
                    "section": article.section,
                    "par_idx": par_idx,
                    "n_tokens": len(tokens(paragraph)),
                }
            )
            i += 1
    return original, index


def write_json_bouquet_style(data: object, path: Path) -> None:
    """Match bouquet_original.json's serialization: ensure_ascii=False, indent=2."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _char_stats(strings: list[str]) -> dict[str, float]:
    lengths = [len(s) for s in strings]
    return {
        "count": len(lengths),
        "mean_chars": statistics.mean(lengths),
        "median_chars": statistics.median(lengths),
        "max_chars": max(lengths),
    }


def validate_schema(original_path: Path, bouquet_path: Path) -> dict[str, dict[str, float]]:
    """Assert both files are a flat JSON array of non-empty strings; return
    per-file char-length stats for the printed comparison."""
    wiki_original = json.loads(original_path.read_text(encoding="utf-8"))
    bouquet_original = json.loads(bouquet_path.read_text(encoding="utf-8"))

    named = (("wiki_original.json", wiki_original), ("bouquet_original.json", bouquet_original))
    for name, data in named:
        if not isinstance(data, list):
            raise AssertionError(f"{name}: expected a JSON array, got {type(data).__name__}")
        if not all(isinstance(x, str) and x for x in data):
            raise AssertionError(f"{name}: expected an array of non-empty strings")

    return {
        "wiki_original.json": _char_stats(wiki_original),
        "bouquet_original.json": _char_stats(bouquet_original),
    }


def _decile_picks(articles: list[Article]) -> list[dict]:
    """Rank-based deciles: sort ascending by article total tokens, split into
    10 equal-size bins of 10, and pick each bin's lower-median (index 4 of
    10) as the article closest to that decile's rank midpoint."""
    ranked = sorted(articles, key=lambda a: a.n_tokens)
    bin_size = len(ranked) // N_DECILES
    picks = []
    for d in range(N_DECILES):
        bin_articles = ranked[d * bin_size : (d + 1) * bin_size]
        pick = bin_articles[bin_size // 2 - 1]
        picks.append({"decile": d, "article": pick, "reason": f"decile {d}"})
    return picks


def _force_include(
    picks: list[dict], article: Article, reason: str, forced_slots: set[int]
) -> None:
    """Force `article` into `picks`, replacing the pick nearest to it by total
    tokens (excluding slots already forced) unless it is already present."""
    for pick in picks:
        if pick["article"].title == article.title:
            pick["reason"] = f"{pick['reason']} + {reason}"
            forced_slots.add(picks.index(pick))
            return

    candidates = [(i, p) for i, p in enumerate(picks) if i not in forced_slots]
    slot_i, _ = min(candidates, key=lambda ip: abs(ip[1]["article"].n_tokens - article.n_tokens))
    replaced_decile = picks[slot_i]["decile"]
    replaced_reason = picks[slot_i]["reason"]
    new_reason = f"{reason} (replaces decile {replaced_decile} pick, was {replaced_reason})"
    picks[slot_i] = {"decile": replaced_decile, "article": article, "reason": new_reason}
    forced_slots.add(slot_i)


def select_pilot(articles: list[Article], original: list[str], index: list[dict]) -> dict:
    picks = _decile_picks(articles)
    forced_slots: set[int] = set()

    max_tokens_paragraph = max(index, key=lambda rec: rec["n_tokens"])
    max_owner = next(a for a in articles if a.title == max_tokens_paragraph["title"])
    _force_include(picks, max_owner, "max-paragraph article", forced_slots)

    marker_owners = [a for a in articles if any(MARKER in p for p in a.paragraphs)]
    # Ишува carries both the corpus-max paragraph and the marker (2026-07-07
    # audit): pick a DIFFERENT marker owner so the two force-includes actually
    # diversify the pilot rather than double-counting one article.
    marker_article = next(a for a in marker_owners if a.title != max_owner.title)
    _force_include(picks, marker_article, "editorial-marker article", forced_slots)

    picks.sort(key=lambda p: p["decile"])

    pilot_titles = {p["article"].title for p in picks}
    paragraph_indices = [rec["i"] for rec in index if rec["title"] in pilot_titles]

    articles_out = [
        {
            "title": p["article"].title,
            "section": p["article"].section,
            "n_paragraphs": p["article"].n_paragraphs,
            "n_tokens": p["article"].n_tokens,
            "reason": p["reason"],
        }
        for p in picks
    ]

    smoke_indices = _smoke_indices(index, max_tokens_paragraph["i"], marker_article, original)

    return {
        "articles": articles_out,
        "paragraph_indices": paragraph_indices,
        "smoke_indices": smoke_indices,
    }


def _smoke_indices(
    index: list[dict], max_paragraph_i: int, marker_article: Article, original: list[str]
) -> dict[str, int]:
    """5-paragraph smoke subset over the whole corpus: shortest, closest to
    the median, closest to p90 (the "long" bucket, distinct from the literal
    max), the max-token paragraph, and the first marker paragraph."""
    all_tokens = sorted(rec["n_tokens"] for rec in index)
    median = statistics.median(all_tokens)
    p90 = all_tokens[int(0.9 * (len(all_tokens) - 1))]

    marker_i = next(
        rec["i"]
        for rec in index
        if rec["title"] == marker_article.title and MARKER in original[rec["i"]]
    )

    used: set[int] = {max_paragraph_i, marker_i}

    def closest_to(target: float) -> int:
        candidates = [rec for rec in index if rec["i"] not in used]
        best = min(candidates, key=lambda rec: abs(rec["n_tokens"] - target))
        used.add(best["i"])
        return best["i"]

    short_i = closest_to(min(all_tokens))
    medium_i = closest_to(median)
    long_i = closest_to(p90)

    return {
        "short": short_i,
        "medium": medium_i,
        "long": long_i,
        "max_paragraph": max_paragraph_i,
        "marker_paragraph": marker_i,
    }


def print_summary(
    articles: list[Article],
    schema_stats: dict[str, dict[str, float]],
    pilot: dict,
) -> None:
    n_total_tokens = sum(a.n_tokens for a in articles)
    n_total_paragraphs = sum(a.n_paragraphs for a in articles)
    print(f"articles: {len(articles)}, paragraphs: {n_total_paragraphs}, tokens: {n_total_tokens}")

    print("\nschema comparison (wiki_original.json vs bouquet_original.json):")
    for name, stats in schema_stats.items():
        print(
            f"  {name}: count={stats['count']} mean={stats['mean_chars']:.1f} "
            f"median={stats['median_chars']:.1f} max={stats['max_chars']:.0f}"
        )

    print("\npilot: 10 stratified articles")
    for a in pilot["articles"]:
        print(
            f"  decile-pick {a['title']!r} ({a['section']}): "
            f"{a['n_paragraphs']} paragraphs, {a['n_tokens']} tokens -- {a['reason']}"
        )
    print(f"\npilot paragraphs covered: {len(pilot['paragraph_indices'])}")
    print(f"smoke indices: {pilot['smoke_indices']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--titles", type=Path, default=DEFAULT_TITLES)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--bouquet", type=Path, default=DEFAULT_BOUQUET)
    args = parser.parse_args()

    articles = build_corpus(args.titles, args.cache)
    original, index = build_original_and_index(articles)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    original_path = args.out_dir / "wiki_original.json"
    index_path = args.out_dir / "wiki_index.json"
    pilot_path = args.out_dir / "pilot_articles.json"

    write_json_bouquet_style(original, original_path)
    write_json_bouquet_style(index, index_path)

    schema_stats = validate_schema(original_path, args.bouquet)

    pilot = select_pilot(articles, original, index)
    write_json_bouquet_style(pilot, pilot_path)

    print_summary(articles, schema_stats, pilot)


if __name__ == "__main__":
    main()
