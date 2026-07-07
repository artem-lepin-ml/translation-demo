#!/usr/bin/env python3
"""Rebuild the demo Term[] with G6 label_first grounding + P1/P3 pairing.

Grounding: G6 (label_first) via ``pipeline.run`` — deterministic exact-label
match first, LLM judge escalation only on genuine ambiguity (per-decision
trace written to ``term.trace``, see spec 2026-07-03-grounding-label-first-design.md
§3). The judge is the live CloseRouter gateway (``google/gemini-3.1-flash-lite``
@ ``provider-9``, temperature=0 — same provider selection as
``scripts/eval_grounding.py``/``scripts/wiki_eval.py``) when
``OPENROUTER_API_KEY`` is available; otherwise ``judge=None`` and every
escalation degrades honestly to yellow/judge_unavailable (no silent top-1
fallback).

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
# .env is not committed and not per-worktree; try the worktree root, the main
# translation-demo checkout, then the legacy sibling — first existing file wins.
ENV_CANDIDATES = (
    ROOT / ".env",
    Path("/Users/a1111/Projects/Work/translation-demo/.env"),
    Path("/Users/a1111/Projects/Work/gse-translation/.env"),
)

JUDGE_MAX_TOKENS = 512
JUDGE_SYSTEM = "You are a Wikidata disambiguation judge. Return strict JSON only."
MAX_JUDGE_CALLS = 400  # hard safety cap on live calls for one rebuild


def _load_dotenv(paths: tuple[Path, ...] = ENV_CANDIDATES) -> None:
    """Manual .env parser -> os.environ. Never prints/logs the value.

    Loads the first existing candidate file (worktrees carry no .env of their
    own); already-set env vars are never overwritten.
    """
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value
        return


def _build_judge():
    """Live grounding judge for LLM disambiguation escalation.

    Same provider selection as the eval harness (scripts/eval_grounding.py /
    scripts/wiki_eval.py): the CloseRouter gateway running
    ``google/gemini-3.1-flash-lite`` @ ``provider-9`` on the repo's live
    ``OPENROUTER_API_KEY`` — model/provider/base-url are env-overridable
    (``CLOSEROUTER_MODEL`` / ``CLOSEROUTER_PROVIDER`` / ``OPENROUTER_BASE_URL``).
    Returns ``(judge_callable, path_used, stats)`` — ``judge_callable`` is
    ``None`` on any setup failure so the caller degrades to
    ``judge_unavailable`` honestly (no silent top-1 fallback). ``stats`` is a
    live-updated dict of call count + token/cost totals for the run report.
    """
    _load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None, "no OPENROUTER_API_KEY — judge=None (fallback)", None

    model = os.environ.get("CLOSEROUTER_MODEL", "google/gemini-3.1-flash-lite")
    provider = os.environ.get("CLOSEROUTER_PROVIDER", "provider-9")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://api.closerouter.dev/v1")

    # Lazy import: keep this module importable without `openai` installed
    # when the judge path isn't exercised (mirrors term_pipeline.py's pattern).
    from palimpsest.llm.client import LLMClient, LLMConfig

    client = LLMClient(
        LLMConfig(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=0,
            max_tokens=JUDGE_MAX_TOKENS,
            extra_body={"provider": provider},
        )
    )

    stats = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "cost_usd": 0.0,
    }

    def judge(prompt: str) -> dict:
        if stats["calls"] >= MAX_JUDGE_CALLS:
            raise RuntimeError(f"MAX_JUDGE_CALLS={MAX_JUDGE_CALLS} reached")
        res = client.complete_retrying(system=JUDGE_SYSTEM, user=prompt)
        stats["calls"] += 1
        u = res.usage
        stats["prompt_tokens"] += u.prompt_tokens
        stats["completion_tokens"] += u.completion_tokens
        stats["reasoning_tokens"] += u.reasoning_tokens
        cost = u.cost_usd if u.cost_usd is not None else 0.0
        stats["cost_usd"] += cost

        text = res.content.strip()
        if text.startswith("```"):  # gemini occasionally fences its JSON
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        parsed["_usage"] = {
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "reasoning_tokens": u.reasoning_tokens,
        }
        parsed["_cost_usd"] = cost
        return parsed

    return judge, f"live CloseRouter judge ({model} @ {provider})", stats


def main() -> int:
    rows = {json.loads(line)["id"]: json.loads(line) for line in SEED.open(encoding="utf-8")}
    by_para = load_mentions(MENTIONS)
    p3 = json.loads(PAIR_P3.read_text(encoding="utf-8")) if PAIR_P3.exists() else {}
    wd = WikidataClient(cache_path=CACHE)
    grounder, pairer = LabelFirstGrounding(wd), LinkLocatePairing(wd)

    judge, judge_path, judge_stats = _build_judge()
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
            row["source"],
            target,
            mentions,
            grounder=grounder,
            pairer=pairer,
            judge=judge,
            scope_id=pid,
            judge_cache=judge_cache,
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
    rel_out = OUT.relative_to(ROOT)
    print(f"rebuilt {total} terms (G6 label_first grounding + P1/P3 pairing) -> {rel_out}")
    print(f"  difficulty:   {counts}")
    print(f"  resolved_by:  {resolved_by_counts}")
    print(f"  pairAccuracy: {pair_counts}  (P3 overlaid on {p3_overlaid} occurrences)")
    print(f"  live wikidata api calls this run: {wd.n_calls}")
    if judge_stats is not None:
        print(
            f"  live judge calls: {judge_stats['calls']}  "
            f"(prompt {judge_stats['prompt_tokens']} + completion "
            f"{judge_stats['completion_tokens']} + reasoning "
            f"{judge_stats['reasoning_tokens']} tokens, "
            f"${judge_stats['cost_usd']:.4f})"
        )
    return 0


def _term(t, ts, pa, rec) -> dict:
    return {
        "sourceSurface": t.source_surface,
        "sourceLemma": t.source_lemma,
        "context": t.context,
        "charStart": t.char_start,
        "charEnd": t.char_end,
        "difficulty": t.difficulty,
        "grounded": t.grounded.as_dict() if t.grounded else None,
        "candidates": [c.as_dict() for c in t.candidates],
        "targetSurface": ts,
        "pairAccuracy": pa,
        "recommended": rec,
        "note": t.note,
        "trace": t.trace,
    }


if __name__ == "__main__":
    raise SystemExit(main())
