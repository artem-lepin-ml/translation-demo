#!/usr/bin/env python3
"""Combine ``scripts/sitelink_contamination.py``'s per-run sitelink-clean
replay (R_doc/R_span/R_strict + P_mention/P_type, all with Wilson CI) for
both finished model-comparison runs (gemini-3.1-flash-lite, deepseek-v4-flash)
into one JSON for the paper's Table C.

Pure driver -- no matching/CI/replay logic of its own; it just calls
``sitelink_contamination.run()`` twice against the two runs' own already-warm
on-disk caches (``docs/experiments/2026-07-05-model-comparison/drafts/
sitelink_replay/.wikidata_cache.<model-slug>.jsonl``, built by a prior run of
that script) and writes the combined result. ``allow_network=False`` (the
default) means this makes zero live Wikidata calls on a warm cache -- see
``sitelink_contamination.py``'s module docstring for what that guarantees and
what it does NOT cover (P_label / P3\\exact, reported as a diagnostic count
only, never computed here).

Usage (from the worktree root, with PYTHONPATH=src):
  uv run python scripts/sitelink_clean_full_metrics.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitelink_contamination import run  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GT_PATH = REPO / "data/eval/wiki/gt_v2.jsonl"
REPLAY_DIR = REPO / "docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay"
OUT_PATH = REPO / "docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json"

# The two finished, citable model-comparison runs (config "111") -- same run
# dirs as drafts/sitelink_replay/{gemini,deepseek}.json and
# docs/reports/python-pro-ner-wikidata-table-c-extraction.md.
RUNS = {
    "gemini-3.1-flash-lite": (
        REPO / "reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9"
        "/111/2026-07-05T23-06-38Z"
    ),
    "deepseek-v4-flash": (
        REPO / "reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--provider-9"
        "/111/2026-07-05T23-35-52Z"
    ),
}


def main() -> int:
    results: dict = {}
    for name, pred_dir in RUNS.items():
        meta = json.loads((pred_dir / "meta.json").read_text(encoding="utf-8"))
        model_slug = f"{meta['model'].replace('/', '--')}--{meta['provider']}"
        cache_path = REPLAY_DIR / f".wikidata_cache.{model_slug}.jsonl"

        result = run(
            pred_dir, GT_PATH, meta,
            network_concurrency=1, cache_path=cache_path, allow_network=False,
        )
        results[name] = result
        print(
            f"=== {name}: wikidata_network_calls_made={result['wikidata_network_calls_made']} "
            f"R_doc_clean={result['R_doc_clean']['value']} "
            f"({result['R_doc_clean']['matched']}/{result['R_doc_clean']['total']}) ===",
            file=sys.stderr,
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
