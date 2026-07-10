#!/usr/bin/env python3
# Provenance: written during the 2026-07-10 wiki-eval v2 session (NER miss-review campaign).
# What it does: enumerates span-level NER misses on the gemini pilot for human/LLM review.
# Paths inside may assume the original scratchpad CWD -- adjust before rerunning.
"""Enumerate ALL span-level NER misses on the gemini pilot (follow-up to
Section D of replay_analysis.py) -- gold anchors (tier-filtered) with NO
token-overlap from any pred mention, one JSON record each with a
reconstructed sentence, unit-recovery flag, and in-sentence extraction
context. PURELY OFFLINE, no Wikidata replay needed (no candidate-set data
used here) -- lighter than the parent analysis.

Run: PYTHONPATH=src uv run --no-sync python3 <this file>
"""
from __future__ import annotations

import json
import urllib.parse
from collections import defaultdict
from pathlib import Path

from palimpsest.terminology.evaluation import metrics as M
from palimpsest.terminology.extract import _is_sentence_boundary, _sentence_spans  # reuse, not reimplement

ROOT = Path("/home/user/translation-demo")
RUN_DIR = ROOT / "reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z"
PRED_PATH = RUN_DIR / "pred.jsonl"
GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"
TIER_PATH = ROOT / "data/eval/wiki/tier_assignment.json"

OUT_DIR = Path("/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/ner_miss_review")

EXPECTED_NAMED_MISS = 28
EXPECTED_TERM_MISS = 36


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def overlaps(a_index: int, a_len: int, b_index: int, b_len: int) -> bool:
    return a_index < b_index + b_len and b_index < a_index + a_len


def contains(outer_index: int, outer_len: int, inner_index: int, inner_len: int) -> bool:
    return outer_index <= inner_index and inner_index + inner_len <= outer_index + outer_len


def wiki_url(title: str) -> str:
    return "https://ru.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="")


def qid_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}"


def build_sentence_index(tokens: list[str]) -> tuple[str, list[int], list[tuple[int, int]]]:
    """Reconstruct the article as one space-joined string (paragraph breaks
    collapse to a single space -- gt.jsonl carries no paragraph-boundary
    field alongside its flat, article-global token list, so this is an
    approximation of the real per-paragraph ``sentence_context`` call;
    documented as a limitation, not hidden). Returns (joined_text,
    char_offset_of_each_token_start, sentence_char_spans).
    """
    joined_parts = []
    offsets = []
    pos = 0
    for tok in tokens:
        offsets.append(pos)
        joined_parts.append(tok)
        pos += len(tok) + 1  # +1 for the joining space
    joined = " ".join(tokens)
    assert pos - 1 == len(joined) or len(tokens) == 0
    spans = _sentence_spans(joined)
    return joined, offsets, spans


def token_range_for_char_span(offsets: list[int], n_tokens: int, char_lo: int, char_hi: int) -> tuple[int, int]:
    """Map a char span [char_lo, char_hi) back to a token index range
    [tok_lo, tok_hi) using the same offsets list build_sentence_index made."""
    tok_lo = 0
    while tok_lo < n_tokens and offsets[tok_lo] < char_lo:
        tok_lo += 1
    tok_hi = tok_lo
    while tok_hi < n_tokens and offsets[tok_hi] < char_hi:
        tok_hi += 1
    return tok_lo, tok_hi


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pred_records = load_jsonl(PRED_PATH)
    gt_all = load_jsonl(GT_PATH)
    pred_titles = {r["title"] for r in pred_records}
    gt_pilot = [r for r in gt_all if r["title"] in pred_titles]
    assert len(gt_pilot) == 10
    tier_assignment: dict[str, int] = json.loads(TIER_PATH.read_text(encoding="utf-8"))

    pred_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in pred_records:
        pred_by_title[r["title"]].append(r)

    # gold_class + TP unit set (same construction as the parent analysis' Step 2,
    # verified there to reproduce aggregate_corpus_v3's own counts exactly)
    gold_class: dict[tuple[str, str], str] = {}
    tp_units: set[tuple[str, str]] = set()
    for rec in gt_pilot:
        title = rec["title"]
        gold_surfaces: dict[str, list[str]] = defaultdict(list)
        for t in rec["gt_tuples"]:
            qid = t[2]
            if tier_assignment.get(qid, 0) != 0:
                continue
            gold_surfaces[qid].append(t[1])
        pred_qids_grounded = {r["qid"] for r in pred_by_title.get(title, []) if r.get("qid")}
        for qid, surfaces in gold_surfaces.items():
            cls, _amb = M._classify(surfaces)
            gold_class[(title, qid)] = cls
            if qid in pred_qids_grounded:
                tp_units.add((title, qid))

    anomalies: list[str] = []

    misses: list[dict] = []
    d_recall_check = {"named": {"hit": 0, "total": 0}, "term": {"hit": 0, "total": 0}}

    for rec in gt_pilot:
        title = rec["title"]
        tokens = rec["tokens"]
        article_mentions = pred_by_title.get(title, [])
        joined, offsets, sent_spans = build_sentence_index(tokens)

        for t in rec["gt_tuples"]:
            idx, surf, qid, slen = t[0], t[1], t[2], t[3]
            if tier_assignment.get(qid, 0) != 0:
                continue
            cls = gold_class[(title, qid)]
            hit = any(overlaps(m["index"], m["span_len"], idx, slen) for m in article_mentions)
            d_recall_check[cls]["total"] += 1
            if hit:
                d_recall_check[cls]["hit"] += 1
                continue

            # --- missed anchor: build the record ---
            if idx < 0 or idx + slen > len(tokens):
                anomalies.append(f"{title}: anchor token range [{idx},{idx+slen}) out of bounds "
                                  f"(n_tokens={len(tokens)}) qid={qid} surf={surf!r}")
                continue
            char_lo = offsets[idx]
            char_hi = offsets[idx + slen - 1] + len(tokens[idx + slen - 1])

            overlapping_sent = [(a, b) for (a, b) in sent_spans if char_lo < b and char_hi > a]
            if not overlapping_sent:
                anomalies.append(f"{title}: no sentence span found for anchor qid={qid} surf={surf!r} "
                                  f"idx={idx} char=[{char_lo},{char_hi})")
                sentence_text = " ".join(tokens[idx:idx + slen])
                sent_tok_lo, sent_tok_hi = idx, idx + slen
            else:
                sent_char_lo = min(a for a, _ in overlapping_sent)
                sent_char_hi = max(b for _, b in overlapping_sent)
                sent_tok_lo, sent_tok_hi = token_range_for_char_span(offsets, len(tokens), sent_char_lo, sent_char_hi)
                sent_tokens = list(tokens[sent_tok_lo:sent_tok_hi])
                # mark the anchor's own tokens (relative position within the slice)
                rel_lo = idx - sent_tok_lo
                rel_hi = rel_lo + slen
                if 0 <= rel_lo < len(sent_tokens) and rel_hi <= len(sent_tokens):
                    sent_tokens[rel_lo] = "⟪" + sent_tokens[rel_lo]
                    sent_tokens[rel_hi - 1] = sent_tokens[rel_hi - 1] + "⟫"
                else:
                    anomalies.append(f"{title}: anchor idx range not inside its own detected sentence token range "
                                      f"qid={qid} surf={surf!r} idx={idx} slen={slen} sent=[{sent_tok_lo},{sent_tok_hi})")
                sentence_text = " ".join(sent_tokens)

            extracted_in_sentence = sorted({
                m["surface"] for m in article_mentions
                if contains(sent_tok_lo, sent_tok_hi - sent_tok_lo, m["index"], m["span_len"])
            })

            misses.append({
                "article_title": title,
                "article_url": wiki_url(title),
                "anchor_text": surf,
                "gold_qid": qid,
                "qid_url": qid_url(qid),
                "class": cls,
                "token_index": idx,
                "span_len": slen,
                "sentence": sentence_text,
                "sentence_source": "gt.jsonl tokens (space-joined; extract.py _sentence_spans reused verbatim)",
                "unit_recovered_elsewhere": (title, qid) in tp_units,
                "extracted_in_sentence": extracted_in_sentence,
            })

    # ── reconciliation ──────────────────────────────────────────────────────
    n_named_miss = sum(1 for m in misses if m["class"] == "named")
    n_term_miss = sum(1 for m in misses if m["class"] == "term")

    d_named_delta = d_recall_check["named"]["total"] - d_recall_check["named"]["hit"]
    d_term_delta = d_recall_check["term"]["total"] - d_recall_check["term"]["hit"]

    print(f"named: total={d_recall_check['named']['total']} hit={d_recall_check['named']['hit']} "
          f"miss(computed here)={d_named_delta}  enumerated={n_named_miss}  "
          f"expected={EXPECTED_NAMED_MISS}  match_D={d_named_delta==428-400}  match_enum={n_named_miss==EXPECTED_NAMED_MISS}")
    print(f"term:  total={d_recall_check['term']['total']} hit={d_recall_check['term']['hit']} "
          f"miss(computed here)={d_term_delta}  enumerated={n_term_miss}  "
          f"expected={EXPECTED_TERM_MISS}  match_D={d_term_delta==95-59}  match_enum={n_term_miss==EXPECTED_TERM_MISS}")

    assert d_recall_check["named"]["total"] == 428, d_recall_check["named"]["total"]
    assert d_recall_check["named"]["hit"] == 400, d_recall_check["named"]["hit"]
    assert d_recall_check["term"]["total"] == 95, d_recall_check["term"]["total"]
    assert d_recall_check["term"]["hit"] == 59, d_recall_check["term"]["hit"]

    n_recovered = sum(1 for m in misses if m["unit_recovered_elsewhere"])

    misses.sort(key=lambda m: (m["article_title"], m["token_index"]))

    (OUT_DIR / "misses.json").write_text(json.dumps(misses, ensure_ascii=False, indent=1), encoding="utf-8")

    def trim(sentence: str, max_words: int = 15) -> str:
        # find marker position to center the trim window on the anchor
        words = sentence.split(" ")
        marker_positions = [i for i, w in enumerate(words) if "⟪" in w or "⟫" in w]
        if not marker_positions:
            core = words[:max_words]
            return " ".join(core) + (" …" if len(words) > max_words else "")
        lo_w, hi_w = marker_positions[0], marker_positions[-1]
        half = max_words // 2
        start = max(0, lo_w - half)
        end = min(len(words), hi_w + half + 1)
        prefix = "… " if start > 0 else ""
        suffix = " …" if end < len(words) else ""
        return prefix + " ".join(words[start:end]) + suffix

    lines = [
        "| article | class | anchor | recovered? | sentence (trimmed) |",
        "|---|---|---|---|---|",
    ]
    for m in misses:
        lines.append(
            f"| {m['article_title']} | {m['class']} | {m['anchor_text']} | "
            f"{'yes' if m['unit_recovered_elsewhere'] else 'NO'} | {trim(m['sentence'])} |"
        )
    (OUT_DIR / "misses_preview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nn_misses total = {len(misses)} (named={n_named_miss}, term={n_term_miss})")
    print(f"n_recovered_elsewhere = {n_recovered} / {len(misses)}")
    print(f"anomalies: {len(anomalies)}")
    for a in anomalies:
        print("  ANOMALY:", a)
    print(f"\nwrote {OUT_DIR / 'misses.json'}")
    print(f"wrote {OUT_DIR / 'misses_preview.md'}")


if __name__ == "__main__":
    main()
