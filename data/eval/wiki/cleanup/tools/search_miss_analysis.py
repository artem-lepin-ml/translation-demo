#!/usr/bin/env python3
# Provenance: written 2026-07-10 for the wiki-eval v2 R_search follow-up (candidate-list
# retrieval-miss analysis over the NER+grounding pipeline's extraction-only in-flight runs,
# commit 64eb023's predict.py/label_first.py "candidates" per-mention field).
# What it does: classifies each effective-gold entity's pipeline outcome (not_extracted /
# no_candidates / retrieval_miss / candidates_hit) against a run's pred.jsonl/
# pred.partial.jsonl candidate lists, for offline search-miss review.
# PURELY OFFLINE: reads only committed gt.jsonl/tier_assignment.json/anchor_exclusions.json
# plus the given run dir's pred file (read-only). No LLM calls, no network. Never writes
# under reports/ -- --out is caller-supplied and must live outside it.
#
# Run: cd /home/user/translation-demo && PYTHONPATH=src uv run --no-sync python3 \
#     data/eval/wiki/cleanup/tools/search_miss_analysis.py \
#     --run-dir reports/terminology/wiki-eval/<model-slug>/<config>/<run_id> \
#     --articles 10 --out <json path>
"""Gold-entity pipeline-outcome classifier: not_extracted / no_candidates /
retrieval_miss / candidates_hit.

Unit of analysis = gold entity, i.e. a distinct ``(article, QID)`` pair -- the same
grouping ``metrics.aggregate_corpus`` (protocol v3) uses for its own gold units.
Effective gold = ``data/eval/wiki/gt.jsonl`` minus tier-filtered QIDs
(``tier_assignment.json``, kept iff ``drop_level == 0`` -- ``aggregate_corpus``'s own
gold-side filter, reused verbatim here, not reimplemented) minus the live
scoring-time anchor exclusions in ``anchor_exclusions.json`` (identity
``(token_index, anchor_text, qid, span_len)`` scoped by title -- the same filter
``compute_dataset_stats.py``/``span_ner_before_after.py`` apply; note this is NOT
baked into ``wiki_eval.py``'s own ``cmd_report``, which never reads
``anchor_exclusions.json`` -- it is a scoring-time-only overlay every offline
analysis script in this directory applies for itself).

``aggregate_corpus`` itself (protocol v3, read at HEAD) is a pure QID-set aggregator
-- it has NO span-overlap machinery of its own (retired together with ``matching.py``
in the v3 rework, see ``metrics.py``'s module docstring). The mention-level span
``overlaps()`` test below is therefore the same local port every sibling script in
this directory already carries verbatim (``replay_analysis.py``, ``enumerate_misses.py``,
``span_ner_before_after.py`` all define the identical formula) -- ported here per that
established convention, not invented fresh, and not imported from ``metrics.py``
because ``metrics.py`` does not define it. ``metrics._classify`` (named/term) is
deliberately NOT used here: this taxonomy classifies a pipeline OUTCOME per entity,
orthogonal to the named/term split ``aggregate_corpus`` reports.

Sentence reconstruction for each miss's first (lowest ``token_index``) gold mention
ports ``build_lists.py``'s ``build_sentence_index``/``token_range_for_char_span``/
anchor-marking algorithm verbatim (space-joined tokens, ``extract.py``'s
``_sentence_spans`` reused, ``⟪…⟫`` markers, +/-``WINDOW``-token fallback
on out-of-bounds/no-sentence-span edge cases).

Deterministic: entities are grouped in ``gt.jsonl`` file order / gt_tuples order, then
the ``misses`` list is sorted by (selected-article order, qid) for a stable, reviewable
diff between reruns on the same run dir.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from palimpsest.terminology.extract import _sentence_spans  # reuse, not reimplement

ROOT = Path("/home/user/translation-demo")
GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"
TIER_PATH = ROOT / "data/eval/wiki/tier_assignment.json"
EXCL_PATH = ROOT / "data/eval/wiki/anchor_exclusions.json"

Identity = tuple[int, str, str, int]
GoldMention = tuple[int, str, int]  # (token_index, anchor_text, span_len)
OUTCOMES = ("not_extracted", "no_candidates", "retrieval_miss", "candidates_hit")

WINDOW = 15  # sentence-reconstruction fallback window, same as build_lists.py


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def overlaps(a_index: int, a_len: int, b_index: int, b_len: int) -> bool:
    """Token-range overlap test -- same formula as replay_analysis.py/
    enumerate_misses.py/span_ner_before_after.py (metrics.py's protocol-v3
    aggregate_corpus has no span-overlap of its own to reuse, see module docstring)."""
    return a_index < b_index + b_len and b_index < a_index + a_len


# ── sentence reconstruction (verbatim port of build_lists.py) ──────────────────────

def build_sentence_index(tokens: list[str]) -> tuple[list[int], list[tuple[int, int]]]:
    offsets: list[int] = []
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
    tok_lo = 0
    while tok_lo < n_tokens and offsets[tok_lo] < char_lo:
        tok_lo += 1
    tok_hi = tok_lo
    while tok_hi < n_tokens and offsets[tok_hi] < char_hi:
        tok_hi += 1
    return tok_lo, tok_hi


def window_fallback(tokens: list[str], idx: int, slen: int, n_tokens: int) -> str:
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


def reconstruct_sentence(
    tokens: list[str],
    offsets: list[int],
    sent_spans: list[tuple[int, int]],
    idx: int,
    slen: int,
    *,
    title: str,
    qid: str,
    surf: str,
    anomalies: list[str],
) -> str:
    """Sentence containing gold mention [idx, idx+slen), anchor-marked with
    ⟪…⟫ -- verbatim port of build_lists.py's build_anchor_record sentence branch."""
    n_tokens = len(tokens)
    out_of_bounds = idx < 0 or slen <= 0 or idx + slen > n_tokens
    if out_of_bounds:
        anomalies.append(
            f"{title}: OUT_OF_BOUNDS idx={idx} slen={slen} n_tokens={n_tokens} "
            f"qid={qid} surf={surf!r}"
        )
        return window_fallback(tokens, idx, slen, n_tokens)

    char_lo = offsets[idx]
    char_hi = offsets[idx + slen - 1] + len(tokens[idx + slen - 1])
    overlapping = [(a, b) for a, b in sent_spans if char_lo < b and char_hi > a]

    if not overlapping:
        anomalies.append(
            f"{title}: NO_SENTENCE_SPAN idx={idx} slen={slen} char=[{char_lo},{char_hi}) "
            f"qid={qid} surf={surf!r}"
        )
        return window_fallback(tokens, idx, slen, n_tokens)

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
        return " ".join(sent_tokens)

    anomalies.append(
        f"{title}: ANCHOR_OUTSIDE_SENTENCE idx={idx} slen={slen} "
        f"sent_tok=[{sent_tok_lo},{sent_tok_hi}) qid={qid} surf={surf!r}"
    )
    return window_fallback(tokens, idx, slen, n_tokens)


# ── effective gold ──────────────────────────────────────────────────────────────────

def effective_gold_entities(
    gt_records: list[dict],
    tier_assignment: dict[str, int],
    excl_by_title: dict[str, set[Identity]],
) -> dict[tuple[str, str], list[GoldMention]]:
    """(title, qid) -> ordered list of (token_index, anchor_text, span_len), tier +
    exclusion filtered -- the same gold-unit grouping aggregate_corpus performs on its
    gold side, plus the anchor_exclusions.json live filter aggregate_corpus itself
    never applies (see module docstring)."""
    entities: dict[tuple[str, str], list[GoldMention]] = defaultdict(list)
    for rec in gt_records:
        title = rec["title"]
        excl_ids = excl_by_title.get(title, set())
        for t in rec["gt_tuples"]:
            idx, surf, qid, slen = t[0], t[1], t[2], t[3]
            if tier_assignment.get(qid, 0) != 0:
                continue
            identity: Identity = (idx, surf, qid, slen)
            if identity in excl_ids:
                continue
            entities[(title, qid)].append((idx, surf, slen))
    return entities


def classify_outcome(
    gold_mentions: list[GoldMention], qid: str, article_pred: list[dict]
) -> tuple[str, list[dict]]:
    """Classify one gold entity's outcome from pred mentions overlapping ANY of its
    gold mentions (pooled across all of the entity's occurrences in the article)."""
    overlapping: dict[tuple[int, int], dict] = {}
    for gidx, _gsurf, gslen in gold_mentions:
        for m in article_pred:
            if overlaps(m["index"], m["span_len"], gidx, gslen):
                overlapping[(m["index"], m["span_len"])] = m

    if not overlapping:
        return "not_extracted", []

    mentions = sorted(overlapping.values(), key=lambda m: (m["index"], m["span_len"]))
    any_candidates = any((m.get("candidates") or []) for m in mentions)
    if not any_candidates:
        return "no_candidates", mentions

    qid_in_candidates = any(
        c.get("qid") == qid for m in mentions for c in (m.get("candidates") or [])
    )
    if qid_in_candidates:
        return "candidates_hit", mentions
    return "retrieval_miss", mentions


def load_pred_records(run_dir: Path) -> tuple[list[dict], Path]:
    for name in ("pred.jsonl", "pred.partial.jsonl"):
        p = run_dir / name
        if p.exists():
            return load_jsonl(p), p
    raise SystemExit(f"HARD ERROR: neither pred.jsonl nor pred.partial.jsonl found under {run_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--articles", type=int, default=10, help="first N articles by gt.jsonl order")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    pred_records, pred_path = load_pred_records(run_dir)

    gt_all = load_jsonl(GT_PATH)
    if args.articles > len(gt_all):
        raise SystemExit(
            f"HARD ERROR: --articles {args.articles} exceeds gt.jsonl's {len(gt_all)} articles"
        )
    selected = gt_all[: args.articles]
    selected_titles = [r["title"] for r in selected]
    tokens_by_title = {r["title"]: r["tokens"] for r in selected}

    tier_assignment: dict[str, int] = json.loads(TIER_PATH.read_text(encoding="utf-8"))
    excl_data = json.loads(EXCL_PATH.read_text(encoding="utf-8"))
    excl_by_title: dict[str, set[Identity]] = defaultdict(set)
    for e in excl_data["exclusions"]:
        excl_by_title[e["title"]].add((e["token_index"], e["anchor_text"], e["qid"], e["span_len"]))

    pred_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in pred_records:
        pred_by_title[r["title"]].append(r)

    entities = effective_gold_entities(selected, tier_assignment, excl_by_title)

    # sanity gate: no excluded identity can have survived the filter above
    for (title, _qid), mentions in entities.items():
        excl_ids = excl_by_title.get(title, set())
        for idx, surf, slen in mentions:
            assert (idx, surf, _qid, slen) not in excl_ids, (
                f"LEAK: excluded identity present in effective gold: {title}/{_qid}/{idx}"
            )

    anomalies: list[str] = []
    outcome_counts = {o: 0 for o in OUTCOMES}
    misses: list[dict] = []
    sentence_index_cache: dict[str, tuple[list[int], list[tuple[int, int]]]] = {}

    for (title, qid), mentions in entities.items():
        article_pred = pred_by_title.get(title, [])
        outcome, overlapping_mentions = classify_outcome(mentions, qid, article_pred)
        outcome_counts[outcome] += 1

        if outcome == "candidates_hit":
            continue

        tokens = tokens_by_title[title]
        if title not in sentence_index_cache:
            sentence_index_cache[title] = build_sentence_index(tokens)
        offsets, sent_spans = sentence_index_cache[title]

        first_idx, first_surf, first_slen = min(mentions, key=lambda m: m[0])
        sentence = reconstruct_sentence(
            tokens, offsets, sent_spans, first_idx, first_slen,
            title=title, qid=qid, surf=first_surf, anomalies=anomalies,
        )

        misses.append({
            "title": title,
            "qid": qid,
            "gold_mentions": [
                {"anchor_text": surf, "token_index": idx}
                for idx, surf, _slen in sorted(mentions, key=lambda m: m[0])
            ],
            "outcome": outcome,
            "overlapping_pred_mentions": [
                {
                    "surface": m.get("surface"),
                    "lemma": m.get("lemma"),
                    "category": m.get("category"),
                    "candidates": m.get("candidates") or [],
                }
                for m in overlapping_mentions
            ],
            "sentence": sentence,
        })

    n_gold_entities = len(entities)
    assert sum(outcome_counts.values()) == n_gold_entities, (outcome_counts, n_gold_entities)

    misses.sort(key=lambda m: (selected_titles.index(m["title"]), m["qid"]))

    out = {
        "generated_by": "data/eval/wiki/cleanup/tools/search_miss_analysis.py",
        "run_dir": str(run_dir),
        "pred_path": str(pred_path),
        "articles": selected_titles,
        "totals": {
            "n_gold_entities": n_gold_entities,
            "outcomes": {
                o: {
                    "count": outcome_counts[o],
                    "rate": (outcome_counts[o] / n_gold_entities) if n_gold_entities else None,
                }
                for o in OUTCOMES
            },
        },
        "misses": misses,
        "anomalies": anomalies,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(out["totals"], ensure_ascii=False, indent=1))
    print(f"n_misses = {len(misses)}")
    print(f"anomalies: {len(anomalies)}")
    for a in anomalies:
        print("  ANOMALY:", a)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
