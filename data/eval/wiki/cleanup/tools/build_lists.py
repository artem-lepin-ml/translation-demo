#!/usr/bin/env python3
# Provenance: written during the 2026-07-10 wiki-eval v2 session (gold-cleanup campaign).
# What it does: builds per-article numbered lists of gold anchors as LLM-cleanup input.
# Paths inside may assume the original scratchpad CWD -- adjust before rerunning.
"""Per-article numbered list of ALL gold anchors (raw markup, no tier filter)
with their full sentences, for ALL 100 articles in data/eval/wiki/gt.jsonl.

Data-prep helper for the gold-annotation LLM cleanup task. Reuses the proven
sentence-reconstruction machinery from
scratchpad/ner_miss_review/enumerate_misses.py, which itself reuses
extract.py's `_sentence_spans`/`_is_sentence_boundary` verbatim -- not
reimplemented here.

Scratch-only: writes ONLY under OUT_DIR (this scratchpad), never under
docs/ or data/. No LLM calls, no network.

Run: cd /home/user/translation-demo && PYTHONPATH=src uv run --no-sync python3 <this file>
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from palimpsest.terminology.extract import _sentence_spans  # reuse, not reimplement

ROOT = Path("/home/user/translation-demo")
GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"

OUT_DIR = Path(
    "/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff"
    "/scratchpad/gold_cleanup"
)
ARTICLES_DIR = OUT_DIR / "articles"

WINDOW = 15  # +/- token fallback window when no sentence span can be found/used

_SLUG_RE = re.compile(r"[^0-9A-Za-zА-Яа-яЁё]+")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title).strip("-").lower()
    return slug or "untitled"


def build_sentence_index(tokens: list[str]) -> tuple[list[int], list[tuple[int, int]]]:
    """Space-join tokens into one string (article-global, as gt.jsonl carries
    no paragraph-boundary field) and return (char_offset_of_each_token_start,
    sentence_char_spans) -- same construction as enumerate_misses.py's
    build_sentence_index, minus the joined string itself (not needed here).
    """
    offsets = []
    pos = 0
    for tok in tokens:
        offsets.append(pos)
        pos += len(tok) + 1  # +1 for the joining space
    joined = " ".join(tokens)
    assert pos - 1 == len(joined) or len(tokens) == 0
    spans = _sentence_spans(joined)
    return offsets, spans


def token_range_for_char_span(
    offsets: list[int], n_tokens: int, char_lo: int, char_hi: int
) -> tuple[int, int]:
    """Map a char span [char_lo, char_hi) back to a token index range
    [tok_lo, tok_hi) using the same offsets list build_sentence_index made."""
    tok_lo = 0
    while tok_lo < n_tokens and offsets[tok_lo] < char_lo:
        tok_lo += 1
    tok_hi = tok_lo
    while tok_hi < n_tokens and offsets[tok_hi] < char_hi:
        tok_hi += 1
    return tok_lo, tok_hi


def window_fallback(tokens: list[str], idx: int, slen: int, n_tokens: int) -> str:
    """+/-WINDOW-token fallback sentence, marking the anchor if it falls
    (even partially) inside the window. Used whenever a clean, fully-marked
    sentence cannot be produced -- including out-of-bounds anchors, where
    idx/slen may themselves be invalid."""
    lo = max(0, min(idx, n_tokens) - WINDOW)
    hi = max(0, min(max(idx + max(slen, 0), idx), n_tokens) + WINDOW)
    hi = min(hi, n_tokens)
    seg = list(tokens[lo:hi])
    mark_lo = max(idx, lo)
    mark_hi = min(idx + slen, hi)
    if slen > 0 and mark_lo < mark_hi and lo <= mark_lo and mark_hi <= hi and seg:
        rel_lo = mark_lo - lo
        rel_hi = mark_hi - lo
        seg[rel_lo] = "⟪" + seg[rel_lo]
        seg[rel_hi - 1] = seg[rel_hi - 1] + "⟫"
    return " ".join(seg)


def build_anchor_record(
    tokens: list[str],
    offsets: list[int],
    sent_spans: list[tuple[int, int]],
    n_tokens: int,
    tuple_index: int,
    t: list,
    edge_cases: list[str],
    title: str,
) -> dict:
    idx, surf, qid, slen = t[0], t[1], t[2], t[3]
    n = tuple_index + 1

    out_of_bounds = idx < 0 or slen <= 0 or idx + slen > n_tokens
    if out_of_bounds:
        edge_cases.append(
            f"{title}: tuple_index={tuple_index} OUT_OF_BOUNDS idx={idx} slen={slen} "
            f"n_tokens={n_tokens} qid={qid} surf={surf!r}"
        )
        sentence = window_fallback(tokens, idx, slen, n_tokens)
        return {
            "n": n,
            "tuple_index": tuple_index,
            "token_index": idx,
            "span_len": slen,
            "anchor_text": surf,
            "qid": qid,
            "sentence": sentence,
        }

    char_lo = offsets[idx]
    char_hi = offsets[idx + slen - 1] + len(tokens[idx + slen - 1])
    overlapping = [(a, b) for a, b in sent_spans if char_lo < b and char_hi > a]

    if not overlapping:
        edge_cases.append(
            f"{title}: tuple_index={tuple_index} NO_SENTENCE_SPAN idx={idx} slen={slen} "
            f"char=[{char_lo},{char_hi}) qid={qid} surf={surf!r}"
        )
        sentence = window_fallback(tokens, idx, slen, n_tokens)
    else:
        sent_char_lo = min(a for a, _ in overlapping)
        sent_char_hi = max(b for _, b in overlapping)
        sent_tok_lo, sent_tok_hi = token_range_for_char_span(
            offsets, n_tokens, sent_char_lo, sent_char_hi
        )
        sent_tokens = list(tokens[sent_tok_lo:sent_tok_hi])
        rel_lo = idx - sent_tok_lo
        rel_hi = rel_lo + slen
        if 0 <= rel_lo < len(sent_tokens) and rel_lo < rel_hi <= len(sent_tokens):
            sent_tokens[rel_lo] = "⟪" + sent_tokens[rel_lo]
            sent_tokens[rel_hi - 1] = sent_tokens[rel_hi - 1] + "⟫"
            sentence = " ".join(sent_tokens)
        else:
            edge_cases.append(
                f"{title}: tuple_index={tuple_index} ANCHOR_OUTSIDE_SENTENCE idx={idx} "
                f"slen={slen} sent_tok=[{sent_tok_lo},{sent_tok_hi}) qid={qid} surf={surf!r}"
            )
            sentence = window_fallback(tokens, idx, slen, n_tokens)

    return {
        "n": n,
        "tuple_index": tuple_index,
        "token_index": idx,
        "span_len": slen,
        "anchor_text": surf,
        "qid": qid,
        "sentence": sentence,
    }


def main() -> None:
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(GT_PATH)
    assert len(records) == 100, f"expected 100 articles, got {len(records)}"

    edge_cases: list[str] = []
    empty_token_articles: list[str] = []
    duplicate_tuple_notes: list[str] = []

    manifest_entries: list[dict] = []
    anchor_counts: list[int] = []
    total_anchors = 0

    for i, rec in enumerate(records, start=1):
        title = rec["title"]
        article_qid = rec["qid"]
        tokens = rec["tokens"]
        gt_tuples = rec["gt_tuples"]
        n_tokens = len(tokens)

        if n_tokens == 0:
            empty_token_articles.append(title)
            edge_cases.append(f"{title}: EMPTY_TOKENS (n_tuples={len(gt_tuples)})")

        # exact-duplicate tuple detection (same idx/surf/qid/slen at >1 position)
        seen: dict[tuple, list[int]] = {}
        for ti, t in enumerate(gt_tuples):
            seen.setdefault(tuple(t), []).append(ti)
        for key, positions in seen.items():
            if len(positions) > 1:
                note = (
                    f"{title}: DUPLICATE_TUPLE {key!r} at tuple_index={positions} "
                    f"(kept both, not deduplicated)"
                )
                duplicate_tuple_notes.append(note)
                edge_cases.append(note)

        offsets, sent_spans = build_sentence_index(tokens) if n_tokens else ([], [])

        anchors = [
            build_anchor_record(
                tokens, offsets, sent_spans, n_tokens, ti, t, edge_cases, title
            )
            for ti, t in enumerate(gt_tuples)
        ]

        n_anchors = len(anchors)
        anchor_counts.append(n_anchors)
        total_anchors += n_anchors

        fname = f"{i:03d}-{slugify(title)}.json"
        out_path = ARTICLES_DIR / fname
        out_path.write_text(
            json.dumps(
                {
                    "title": title,
                    "qid": article_qid,
                    "n_anchors": n_anchors,
                    "anchors": anchors,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        manifest_entries.append({"file": fname, "title": title, "n_anchors": n_anchors})

    manifest = {
        "articles": manifest_entries,
        "total_articles": len(records),
        "total_anchors": total_anchors,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    counts_sorted = sorted(anchor_counts)
    n = len(counts_sorted)
    median = (
        counts_sorted[n // 2]
        if n % 2
        else (counts_sorted[n // 2 - 1] + counts_sorted[n // 2]) / 2
    )

    print(f"total_articles = {len(records)}")
    print(f"total_anchors = {total_anchors}")
    print(f"anchor_counts: min={counts_sorted[0]} median={median} max={counts_sorted[-1]}")
    print(f"empty_token_articles = {len(empty_token_articles)}: {empty_token_articles}")
    print(f"duplicate_tuple_notes = {len(duplicate_tuple_notes)}")
    for note in duplicate_tuple_notes:
        print("  DUP:", note)
    print(f"\nall edge_cases (n={len(edge_cases)}):")
    for e in edge_cases:
        print("  EDGE:", e)
    print(f"\nwrote {len(manifest_entries)} article files under {ARTICLES_DIR}")
    print(f"wrote {OUT_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
