#!/usr/bin/env python3
"""Rebuild the demo Term[] with G6 label_first grounding + P1/P3 pairing.

Grounding: G6 (label_first) via ``pipeline.run`` — deterministic exact-label
match first, LLM judge escalation only on genuine ambiguity (per-decision
trace written to ``term.trace``, see spec 2026-07-03-grounding-label-first-design.md
§3). The judge is a live OpenAI client (gpt-4o-mini, temperature=0) when
``OPENAI_API_KEY`` is available; otherwise ``judge=None`` and every escalation
degrades honestly to yellow/judge_unavailable (no silent top-1 fallback).

Pairing: P1 (link_locate, deterministic) as the baseline, with the curated P3
(llm_judge) verdicts overlaid on the hard cases from
reports/terminology/judgments_pairing.json ({surface: {verdict, target_surface,
recommended}}). This shows the yellow/red pairing calls P3 wins on (Tadmor→Palmyra,
nomadic→nome) without a full per-occurrence LLM pairing pass; production would run
full P3 with a P1→P3 escalation (see docs/stages/terminology.md).

Output: data/seed/terminology_out.json  (loaded into demo.db by load_terms.py).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology import pipeline
from palimpsest.terminology.extract import load_mentions
from palimpsest.terminology.grounding import LabelFirstGrounding
from palimpsest.terminology.pairing.link_locate import LinkLocatePairing
from palimpsest.terminology.wikidata import WikidataClient

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
MENTIONS = ROOT / "data/seed/terminology_terms.jsonl"
PAIR_P3 = ROOT / "reports/terminology/judgments_pairing.json"
OUT = ROOT / "data/seed/terminology_out.json"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
# .env lives in the main repo checkout, not per-worktree (this worktree has none).
ENV_FILE = Path("/Users/a1111/Projects/Work/gse-translation/.env")

GROUNDING_MODEL = "gpt-4o-mini"
OPENAI_BASE_URL = "https://api.openai.com/v1"


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


def _build_judge():
    """Live OpenAI-direct judge (gpt-4o-mini) for grounding escalation.

    Repo's default closerouter/OPENROUTER_API_KEY is dead for this purpose
    (see task briefing) — this hits OpenAI directly with OPENAI_API_KEY.
    Returns (judge_callable, path_used) — judge_callable is None on any
    setup failure so the caller can degrade to judge_unavailable honestly.
    """
    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "no OPENAI_API_KEY — judge=None (fallback)"

    # Lazy import: keep this module importable without `openai` installed
    # when the judge path isn't exercised (mirrors term_pipeline.py's pattern).
    from palimpsest.llm.client import LLMClient, LLMConfig

    client = LLMClient(LLMConfig(
        model=GROUNDING_MODEL, base_url=OPENAI_BASE_URL, api_key=api_key,
        temperature=0, max_tokens=512,
    ))

    def judge(prompt: str) -> dict:
        res = client.complete(system="", user=prompt)
        return json.loads(res.content)

    return judge, f"live OpenAI judge ({GROUNDING_MODEL})"


def main() -> int:
    rows = {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}
    by_para = load_mentions(MENTIONS)
    p3 = json.loads(PAIR_P3.read_text(encoding="utf-8")) if PAIR_P3.exists() else {}
    wd = WikidataClient(cache_path=CACHE)
    grounder, pairer = LabelFirstGrounding(wd), LinkLocatePairing(wd)

    judge, judge_path = _build_judge()
    print(f"grounding judge: {judge_path}")
    judge_cache: dict = {}  # one sense per discourse, shared across the whole demo doc

    out, counts = {}, {"green": 0, "yellow": 0, "red": 0}
    resolved_by_counts: dict[str, int] = {}
    pair_counts = {"green": 0, "yellow": 0, "red": 0, "null": 0}
    p3_overlaid = 0
    for pid, mentions in by_para.items():
        row = rows[pid]
        target = row.get("translated", "")
        terms = pipeline.run(
            row["source"], target, mentions,
            grounder=grounder, pairer=pairer,
            judge=judge, scope_id=pid, judge_cache=judge_cache,
        )
        term_dicts = []
        for t in terms:
            resolved_by = t.trace.get("resolved_by", "unknown")
            counts[t.difficulty] += 1
            resolved_by_counts[resolved_by] = resolved_by_counts.get(resolved_by, 0) + 1

            ts, pa, rec = t.target_surface, t.pair_accuracy, t.recommended
            j = p3.get(t.source_surface)
            if j and j.get("verdict"):
                ts, pa, rec = j.get("target_surface", ts), j["verdict"], j.get("recommended")
                p3_overlaid += 1
            pair_counts[pa or "null"] += 1

            term_dicts.append(_term(t, ts, pa, rec))
        out[str(pid)] = term_dicts

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(counts.values())
    print(f"rebuilt {total} terms (G6 label_first grounding + P1/P3 pairing) → {OUT.relative_to(ROOT)}")
    print(f"  difficulty:   {counts}")
    print(f"  resolved_by:  {resolved_by_counts}")
    print(f"  pairAccuracy: {pair_counts}  (P3 overlaid on {p3_overlaid} occurrences)")
    print(f"  live wikidata api calls this run: {wd.n_calls}")
    return 0


def _term(t, ts, pa, rec) -> dict:
    return {
        "sourceSurface": t.source_surface, "sourceLemma": t.source_lemma, "context": t.context,
        "charStart": t.char_start, "charEnd": t.char_end, "difficulty": t.difficulty,
        "grounded": t.grounded.as_dict() if t.grounded else None,
        "candidates": [c.as_dict() for c in t.candidates],
        "targetSurface": ts, "pairAccuracy": pa, "recommended": rec, "note": t.note,
        "trace": t.trace,
    }


if __name__ == "__main__":
    raise SystemExit(main())
