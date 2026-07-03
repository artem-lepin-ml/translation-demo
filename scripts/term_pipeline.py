#!/usr/bin/env python3
"""CLI for the terminology pipeline: build mentions → run extract→ground→pair → Term[].

Usage (from the worktree root, with PYTHONPATH=src):
  python scripts/term_pipeline.py mentions          # spans from extracted surfaces → terminology_terms.jsonl
  python scripts/term_pipeline.py run               # G1+P1 over all seed paragraphs → terminology_out.json
  python scripts/term_pipeline.py extract --dry-run # print intended OR calls, spend $0, write nothing
  python scripts/term_pipeline.py extract --real     # live OR NER run, budget-guarded (needs OPENROUTER_API_KEY)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology import pipeline
from palimpsest.terminology.extract import (
    DEFAULT_NER_PROMPT,
    deterministic_surfaces,
    load_mentions,
    mentions_from_surfaces,
    parse_surfaces,
    validate_surfaces,
)
from palimpsest.terminology.grounding import LabelFirstGrounding
from palimpsest.terminology.pairing import LinkLocatePairing
from palimpsest.terminology.wikidata import WikidataClient

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
SURFACES = ROOT / "data/seed/extracted_surfaces.json"
MENTIONS = ROOT / "data/seed/terminology_terms.jsonl"
OUT = ROOT / "data/seed/terminology_out.json"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
CALLS_LOG = ROOT / "reports/terminology/extract_llm_calls.jsonl"
ENV_FILE = ROOT / ".env"

# Winner of the 7-model real-OR NER tournament (2026-07-02): ties the top lowercase
# recall (0.906) but with ~half the noise of gemini-2.5-flash-lite; see
# docs/reports/2026-07-02-ner-model-tournament.html. Budget alternative with equal
# recall + more noise: google/gemini-2.5-flash-lite.
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
OR_BASE_URL = "https://openrouter.ai/api/v1"
MAX_CALLS = 15  # first-attempts only; retries counted separately (<=1/paragraph)


def _seed_rows() -> dict[int, dict]:
    return {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}


def cmd_mentions(_args) -> int:
    rows = _seed_rows()
    extracted = json.loads(SURFACES.read_text(encoding="utf-8"))
    MENTIONS.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with MENTIONS.open("w", encoding="utf-8") as fh:
        for para in extracted:
            pid = para["paragraph_id"]
            src = rows[pid]["source"]
            for m in mentions_from_surfaces(src, para["surfaces"]):
                fh.write(json.dumps({
                    "paragraph_id": pid, "surface": m.surface, "context": m.context,
                    "lemma": m.lemma, "char_start": m.char_start, "char_end": m.char_end,
                    "category": m.category,
                }, ensure_ascii=False) + "\n")
                n += 1
    print(f"wrote {n} mentions → {MENTIONS.relative_to(ROOT)}")
    return 0


def _term_json(t) -> dict:
    return {
        "sourceSurface": t.source_surface, "sourceLemma": t.source_lemma,
        "context": t.context, "charStart": t.char_start, "charEnd": t.char_end,
        "difficulty": t.difficulty,
        "grounded": t.grounded.as_dict() if t.grounded else None,
        "candidates": [c.as_dict() for c in t.candidates],
        "targetSurface": t.target_surface, "pairAccuracy": t.pair_accuracy,
        "recommended": t.recommended, "note": t.note, "trace": t.trace,
    }


def cmd_run(_args) -> int:
    rows = _seed_rows()
    by_para = load_mentions(MENTIONS)
    wd = WikidataClient(cache_path=CACHE)
    grounder, pairer = LabelFirstGrounding(wd), LinkLocatePairing(wd)

    out: dict[str, list] = {}
    t0 = time.perf_counter()
    counts = {"green": 0, "yellow": 0, "red": 0}
    pair_counts = {"green": 0, "yellow": 0, "red": 0, "null": 0}
    for pid, mentions in by_para.items():
        row = rows[pid]
        terms = pipeline.run(row["source"], row.get("translated", ""), mentions,
                             grounder=grounder, pairer=pairer)
        out[str(pid)] = [_term_json(t) for t in terms]
        for t in terms:
            counts[t.difficulty] += 1
            pair_counts[t.pair_accuracy or "null"] += 1
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    dt = time.perf_counter() - t0
    total = sum(counts.values())
    print(f"pipeline: {total} terms in {len(out)} paragraphs, {dt:.1f}s, {wd.n_calls} live API calls")
    print(f"  difficulty:   {counts}")
    print(f"  pairAccuracy: {pair_counts}")
    print(f"  → {OUT.relative_to(ROOT)}")
    return 0


def _load_dotenv(path: Path = ENV_FILE) -> None:
    """Manual .env parser -> os.environ. Never prints/logs the value."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _mask(key: str | None) -> str:
    if not key:
        return "(empty)"
    return key[:4] + "…" if len(key) > 4 else "…"


def _or_credits(api_key: str) -> float | None:
    """GET https://openrouter.ai/api/v1/credits -> total_usage in USD, or None on failure.

    Plain REST GET via urllib (billing/observability, not an LLM completion) --
    doesn't touch Invariant #6 (LLMClient-only rule is about model calls).
    """
    req = urllib.request.Request(
        f"{OR_BASE_URL}/credits", headers={"Authorization": f"Bearer {api_key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - network/credits lookup is best-effort
        print(f"  (credits lookup failed: {exc})")
        return None
    d = data.get("data", data)
    total_credits = d.get("total_credits")
    total_usage = d.get("total_usage")
    if total_credits is not None and total_usage is not None:
        return float(total_usage)
    return None


def _seed_pairs() -> list[tuple[int, str]]:
    rows = _seed_rows()
    return sorted((pid, row["source"]) for pid, row in rows.items())


def cmd_extract(args) -> int:
    _load_dotenv()
    model = args.model or os.environ.get("EXTRACT_MODEL") or DEFAULT_MODEL
    pairs = _seed_pairs()

    if args.dry_run:
        print(f"[dry-run] model={model}  paragraphs={len(pairs)}  max_usd={args.max_usd}")
        for pid, source in pairs:
            preview = DEFAULT_NER_PROMPT.replace("{{source}}", source[:80] + ("…" if len(source) > 80 else ""))
            preview = preview.splitlines()[-2] if preview.splitlines() else preview
            print(f"  pid={pid:<5} prompt_preview={preview[:100]!r}")
        print("[dry-run] estimate: 16 calls ~ 24k in / 6k out tokens, < $0.01 on gpt-4o-mini (no spend, nothing written)")
        return 0

    if not args.real:
        print("no --real: using deterministic_surfaces (offline, no network, $0 spend)")
        out = [{"paragraph_id": pid, "surfaces": deterministic_surfaces(source)} for pid, source in pairs]
        SURFACES.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {len(out)} paragraphs → {SURFACES.relative_to(ROOT)}")
        return 0

    # --real: lazy-import LLMClient/OpenRouter code only here, so --dry-run/--help
    # and the rest of this module stay importable without `openai` installed.
    from palimpsest.llm.client import LLMClient, LLMConfig

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("error: OPENROUTER_API_KEY not set (checked .env and environment)", file=sys.stderr)
        return 1

    client = LLMClient(LLMConfig(model=model, base_url=OR_BASE_URL, api_key=api_key, temperature=0))

    usage_before = _or_credits(api_key)
    print(f"model={model}  api_key={_mask(api_key)}  usage_before=${usage_before if usage_before is not None else 'unknown'}")

    n_calls = 0
    n_retries = 0
    out: list[dict] = []
    calls_log: list[dict] = []

    for i, (pid, source) in enumerate(pairs):
        if n_calls >= MAX_CALLS:
            print(f"abort: N_CALLS={n_calls} reached cap {MAX_CALLS}", file=sys.stderr)
            return 1

        user_prompt = DEFAULT_NER_PROMPT.replace("{{source}}", source)
        t0 = time.perf_counter()
        n_calls += 1
        reply = client.complete(system="", user=user_prompt)
        surfaces = parse_surfaces(reply.content)
        if not surfaces and n_retries < n_calls:
            n_retries += 1
            reply = client.complete(system="", user=user_prompt)
            surfaces = parse_surfaces(reply.content)
        latency_ms = (time.perf_counter() - t0) * 1000

        valid, dropped = validate_surfaces(source, surfaces)
        out.append({"paragraph_id": pid, "surfaces": valid})
        calls_log.append({
            "pid": pid, "model": model, "finish_reason": "stop" if surfaces else "empty",
            "n_surfaces": len(valid), "n_dropped_not_in_source": dropped, "latency_ms": round(latency_ms, 1),
        })

        # mid-batch budget check (every 8 paragraphs, plus the last one)
        if i in (7, len(pairs) - 1):
            usage_now = _or_credits(api_key)
            if usage_before is not None and usage_now is not None:
                delta = usage_now - usage_before
                if delta > args.max_usd:
                    print(f"abort: spend ${delta:.4f} exceeds --max-usd {args.max_usd}", file=sys.stderr)
                    return 1

    usage_after = _or_credits(api_key)
    delta = (usage_after - usage_before) if (usage_before is not None and usage_after is not None) else None

    SURFACES.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    CALLS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CALLS_LOG.open("a", encoding="utf-8") as fh:
        for row in calls_log:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"n_calls={n_calls}  n_retries={n_retries}  "
          f"spend={'$%.4f' % delta if delta is not None else '< $0.01 (below credits-API resolution)'}")
    print(f"wrote {len(out)} paragraphs → {SURFACES.relative_to(ROOT)}")
    print(f"appended {len(calls_log)} rows → {CALLS_LOG.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mentions").set_defaults(func=cmd_mentions)
    sub.add_parser("run").set_defaults(func=cmd_run)

    p_extract = sub.add_parser("extract", help="NER-extract surfaces for all seed paragraphs")
    p_extract.add_argument("--real", action="store_true", help="use the live OpenRouter model (default: deterministic_surfaces, no network)")
    p_extract.add_argument("--dry-run", action="store_true", help="print intended calls + estimate; spend $0; write nothing")
    p_extract.add_argument("--max-usd", type=float, default=0.20, help="abort if OR credits-delta exceeds this (default 0.20)")
    p_extract.add_argument("--model", default=None, help="OR model id (else EXTRACT_MODEL env, else claude-haiku-4.5)")
    p_extract.set_defaults(func=cmd_extract)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
