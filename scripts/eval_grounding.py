#!/usr/bin/env python3
"""G6 label_first ablation harness: 8 GroundingConfig toggle combinations against
the golden-99, one shared warm Wikidata cache, Wilson-CI'd QID accuracy.

Spec: docs/superpowers/specs/2026-07-03-grounding-label-first-design.md §8.
Output: reports/terminology/g6/<bits>/<run_id ISO-UTC>/{traces.jsonl,metrics.json}.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology import eval_harness as H
from palimpsest.terminology.base import GroundingConfig, TermMention
from palimpsest.terminology.grounding import LabelFirstGrounding
from palimpsest.terminology.grounding.match import norm
from palimpsest.terminology.wikidata import WikidataClient

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path("/Users/a1111/Projects/Work/gse-translation/.env")
SEED = ROOT / "data/seed/seed_paragraphs.jsonl"
GOLD = ROOT / "data/seed/terminology_gold.jsonl"
GOLD_SOURCES = ROOT / "data/seed/gold_sources"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
OUT_ROOT = ROOT / "reports/terminology/g6"

JUDGE_MODEL = "gpt-4o-mini"
JUDGE_MAX_TOKENS = 512
# Conservative per-call price estimate (gpt-4o-mini list price, USD/token) used
# only for the pre-call budget reservation and --dry-run forecast — settled
# against real usage.cost when the provider reports it, never trusted alone.
PRICE_IN = 0.15 / 1_000_000
PRICE_OUT = 0.60 / 1_000_000
# True pre-call worst-case bound, not an average: prompt tokens sized for the
# fixed template + enrich_top=5 candidate lines (qid + label + a full-sentence
# Wikidata description) + a long context sentence, all in RU (heavier tokenization
# than EN); completion tokens use the actual API cap (JUDGE_MAX_TOKENS), since
# the model can legitimately fill it. This must never under-estimate a real call,
# or the BudgetGuard reservation can let --max-usd be exceeded before it stops.
EST_PROMPT_TOKENS = 1000
EST_COMPLETION_TOKENS = JUDGE_MAX_TOKENS
EST_COST_PER_JUDGE_CALL = EST_PROMPT_TOKENS * PRICE_IN + EST_COMPLETION_TOKENS * PRICE_OUT

REFERENCE_G3_ACCURACY = 0.78
FLAG_TERM_DROP = 2  # spec §8 Q5: drop of >2 terms on config 111 vs reference is flagged

# label_first.py's decision-table enum (module docstring) — seeded here so
# resolved_by_distribution always reports every key, zero-count included,
# mirroring how difficulty_distribution is seeded from H.VERDICTS.
RESOLVED_BY_VALUES = ("exact_label", "llm_disambiguation", "judge_rejected",
                      "judge_unavailable", "wikidata_unavailable", "no_candidates")


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


def _seed_rows() -> dict[int, dict]:
    return {json.loads(l)["id"]: json.loads(l) for l in SEED.open(encoding="utf-8")}


def _gold() -> list[dict]:
    return [json.loads(l) for l in GOLD.open(encoding="utf-8")]


def _context_lookup() -> dict[str, str]:
    """Map normalised surface/lemma -> context, built from the gold_sources files.

    Only ``grounding_gold.jsonl`` carries a ``context`` field (``pairing_gold.jsonl``
    and ``terminology_gold_v1.jsonl`` don't); keyed by both surface and lemma so a
    golden row missing its own context can still recover one that a sibling source
    hand-authored for the same term. First writer wins per key (source order is
    fixed, not adversarial).
    """
    lookup: dict[str, str] = {}
    for name in ("grounding_gold.jsonl", "pairing_gold.jsonl", "terminology_gold_v1.jsonl"):
        path = GOLD_SOURCES / name
        if not path.exists():
            continue
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            ctx = row.get("context")
            if not ctx:
                continue
            for key in (row.get("surface") or row.get("source_surface"), row.get("lemma")):
                if key and norm(key) not in lookup:
                    lookup[norm(key)] = ctx
    return lookup


def _configs(bits_subset: list[str] | None) -> dict[str, GroundingConfig]:
    all_bits = ["".join(p) for p in itertools.product("01", repeat=3)]
    bits_list = bits_subset if bits_subset else all_bits
    out = {}
    for bits in bits_list:
        use_lemma, use_fallbacks, match_aliases = (c == "1" for c in bits)
        out[bits] = GroundingConfig(use_lemma=use_lemma, use_fallbacks=use_fallbacks, match_aliases=match_aliases)
    return out


class BudgetGuard:
    """Provider-agnostic in-process pre-call spend cap (E-D12: no OpenRouter
    credits-endpoint polling — that endpoint is dead for this project's key).

    ``reserve()`` is called BEFORE every judge call with a conservative
    per-call estimate; if the running total would exceed ``max_usd`` the run
    stops cleanly instead of firing the call.
    """

    def __init__(self, max_usd: float) -> None:
        self.max_usd = max_usd
        self.spent = 0.0
        self.stopped_reason: str | None = None

    def can_reserve(self, est: float) -> bool:
        if self.stopped_reason is not None:
            return False
        if self.spent + est > self.max_usd:
            self.stopped_reason = f"budget cap ${self.max_usd:.2f} hit (spent ${self.spent:.4f} + est ${est:.4f})"
            return False
        return True

    def reserve(self, est: float) -> None:
        self.spent += est

    def settle(self, est: float, actual: float | None) -> None:
        if actual is None:
            return
        self.spent += actual - est


def _build_judge(guard: BudgetGuard):
    """Lazy-import LLMClient (no direct `openai` import outside
    palimpsest.llm.client by design), pointed at OpenAI direct per the task brief
    (the repo-default OpenRouter base/key are dead)."""
    from palimpsest.llm.client import LLMClient, LLMConfig

    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    client = LLMClient(LLMConfig(
        model=JUDGE_MODEL,
        base_url="https://api.openai.com/v1",
        api_key=api_key,
        temperature=0,
        max_tokens=JUDGE_MAX_TOKENS,
    ))

    def judge(prompt: str) -> dict:
        if not guard.can_reserve(EST_COST_PER_JUDGE_CALL):
            raise RuntimeError(guard.stopped_reason)
        guard.reserve(EST_COST_PER_JUDGE_CALL)
        result = client.complete(
            system="You are a Wikidata disambiguation judge. Return strict JSON only.",
            user=prompt,
        )
        actual_cost = result.usage.cost_usd
        if actual_cost is None and result.usage.prompt_tokens:
            actual_cost = (result.usage.prompt_tokens * PRICE_IN
                           + result.usage.completion_tokens * PRICE_OUT)
        guard.settle(EST_COST_PER_JUDGE_CALL, actual_cost)

        text = result.content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        parsed["_usage"] = {"prompt_tokens": result.usage.prompt_tokens,
                             "completion_tokens": result.usage.completion_tokens,
                             "reasoning_tokens": result.usage.reasoning_tokens}
        parsed["_cost_usd"] = actual_cost if actual_cost is not None else EST_COST_PER_JUDGE_CALL
        return parsed

    return judge


def _mention(g: dict, rows: dict, context_lookup: dict[str, str]) -> tuple[TermMention, str]:
    """Build a TermMention from a golden row plus the ``context_source`` tag.

    Precedence (spec §8, honest-provenance fix):
      1. the golden row's own ``context``                          -> "golden"
      2. gold_sources lookup keyed by normalised surface/lemma      -> "golden_source"
      3. reconstructed from the seed paragraph, if the surface is
         found there                                                -> "reconstructed"
      4. none of the above                                          -> "unavailable" (context="")
    """
    context = g.get("context")
    char_start, char_end = g.get("char_start"), g.get("char_end")
    if context:
        return (TermMention(surface=g["surface"], lemma=g.get("lemma"), context=context,
                            char_start=char_start if char_start is not None else -1,
                            char_end=char_end if char_end is not None else -1,
                            category=g.get("category")), "golden")

    source_ctx = context_lookup.get(norm(g["surface"])) or context_lookup.get(norm(g.get("lemma") or ""))
    if source_ctx:
        return (TermMention(surface=g["surface"], lemma=g.get("lemma"), context=source_ctx,
                            char_start=char_start if char_start is not None else -1,
                            char_end=char_end if char_end is not None else -1,
                            category=g.get("category")), "golden_source")

    src = rows.get(g["paragraph_id"], {}).get("source", "")
    i = src.find(g["surface"])
    if i >= 0:
        context = src[max(0, i - 40): i + len(g["surface"]) + 40]
        char_start, char_end = i, i + len(g["surface"])
        return (TermMention(surface=g["surface"], lemma=g.get("lemma"), context=context,
                            char_start=char_start, char_end=char_end,
                            category=g.get("category")), "reconstructed")

    return (TermMention(surface=g["surface"], lemma=g.get("lemma"), context="",
                        char_start=-1, char_end=-1,
                        category=g.get("category")), "unavailable")


def _run_config(bits: str, config: GroundingConfig, gold: list[dict], rows: dict,
                 wd: WikidataClient, judge, guard: BudgetGuard,
                 context_lookup: dict[str, str]) -> tuple[list[dict], dict]:
    strategy = LabelFirstGrounding(wd, config)
    judge_cache: dict = {}
    traces: list[dict] = []
    score_rows: list[dict] = []
    n_context_golden = 0
    n_context_from_source = 0
    n_context_reconstructed = 0
    n_context_unavailable = 0
    n_excluded_wikidata_unavailable = 0
    n_judge_calls = 0
    judge_cost_usd = 0.0

    for g in gold:
        mention, context_source = _mention(g, rows, context_lookup)
        if context_source == "golden":
            n_context_golden += 1
        elif context_source == "golden_source":
            n_context_from_source += 1
        elif context_source == "reconstructed":
            n_context_reconstructed += 1
        else:
            n_context_unavailable += 1

        if guard.stopped_reason is not None:
            break

        result = strategy.ground(mention, judge=judge, scope_id=g["paragraph_id"], judge_cache=judge_cache)
        trace = result.trace
        traces.append({"surface": g["surface"], "gold_qid": g.get("gold_qid"),
                       "gold_difficulty": g.get("gold_difficulty"), "context_source": context_source, **trace})

        j = trace.get("judge") or {}
        response = j.get("response") or {}
        if response.get("_cost_usd") is not None:
            n_judge_calls += 1
            judge_cost_usd += response["_cost_usd"]

        if trace.get("resolved_by") == "wikidata_unavailable":
            n_excluded_wikidata_unavailable += 1
            continue

        score_rows.append({
            "surface": g["surface"], "category": g.get("category"),
            "gold_qid": g.get("gold_qid"), "gold_difficulty": g.get("gold_difficulty"),
            "pred_qid": result.grounded.qid if result.grounded else None,
            "pred_difficulty": result.difficulty,
            "latency_ms": result.latency_ms, "n_api_calls": result.n_api_calls,
            "resolved_by": trace.get("resolved_by"),
        })

    counters_out = {
        "n_context_golden": n_context_golden,
        "n_context_from_source": n_context_from_source,
        "n_context_reconstructed": n_context_reconstructed,
        "n_context_unavailable": n_context_unavailable,
        "n_excluded_wikidata_unavailable": n_excluded_wikidata_unavailable,
        "n_judge_calls": n_judge_calls,
        "judge_cost_usd": judge_cost_usd,
        "n_processed": len(traces),
        "n_total": len(gold),
    }
    return traces, {"score_rows": score_rows, "counters": counters_out}


def _metrics_v1(bits: str, config: GroundingConfig, gold: list[dict], scored: dict) -> dict:
    score_rows = scored["score_rows"]
    counters = scored["counters"]

    groundable = [r for r in score_rows if r["gold_difficulty"] in ("green", "yellow")]
    qid_hits = sum(1 for r in groundable if r.get("pred_qid") and r["pred_qid"] == r.get("gold_qid"))
    lo, hi = H.wilson_ci(qid_hits, len(groundable))

    reds = [r for r in score_rows if r["gold_difficulty"] == "red"]
    red_hit = sum(1 for r in reds if r["pred_difficulty"] == "red")

    difficulty_dist = {v: sum(1 for r in score_rows if r["pred_difficulty"] == v) for v in H.VERDICTS}
    resolved_by_dist: dict[str, int] = {v: 0 for v in RESOLVED_BY_VALUES}
    for r in score_rows:
        rb = r.get("resolved_by") or "unknown"
        resolved_by_dist[rb] = resolved_by_dist.get(rb, 0) + 1

    n_escalated = sum(v for k, v in resolved_by_dist.items()
                       if k in ("llm_disambiguation", "judge_rejected", "judge_unavailable"))
    escalation_rate = round(n_escalated / len(score_rows), 4) if score_rows else 0.0

    lat = H.latency_stats([r.get("latency_ms", 0.0) for r in score_rows])
    n_api_calls = sum(r.get("n_api_calls", 0) for r in score_rows)

    return {
        "v": 1,
        "config": {"use_lemma": config.use_lemma, "use_fallbacks": config.use_fallbacks,
                   "match_aliases": config.match_aliases},
        "golden": {"version": "terminology_gold.jsonl", "n_total": len(gold),
                   "n_groundable": len(groundable),
                   "n_context_golden": counters["n_context_golden"],
                   "n_context_from_source": counters["n_context_from_source"],
                   "n_context_reconstructed": counters["n_context_reconstructed"],
                   "n_context_unavailable": counters["n_context_unavailable"],
                   "n_excluded_wikidata_unavailable": counters["n_excluded_wikidata_unavailable"]},
        "qid_accuracy_groundable": {"correct": qid_hits, "total": len(groundable),
                                    "value": round(qid_hits / len(groundable), 4) if groundable else None,
                                    "ci95": [lo, hi]},
        "red_split": {"golden_red_hit": red_hit, "golden_red_total": len(reds)},
        "difficulty_distribution": difficulty_dist,
        "resolved_by_distribution": resolved_by_dist,
        "escalation_rate": escalation_rate,
        "n_api_calls": n_api_calls,
        "n_judge_calls": counters["n_judge_calls"],
        "judge_cost_usd": round(counters["judge_cost_usd"], 6),
        "latency_ms_p50": lat["p50"],
        "latency_ms_p95": lat["p95"],
    }


def _dry_run_estimate(configs: dict[str, GroundingConfig], gold: list[dict], rows: dict,
                       context_lookup: dict[str, str]) -> float:
    """Estimate escalations per config with a judge=None pass (no network, $0
    spend, nothing written) and print the forecast. Returns the total
    estimated cost so the caller can decide whether to abort."""
    total_est = 0.0
    print(f"{'config':<8}{'n_gold':>8}{'est_escalations':>18}{'est_cost_usd':>15}")
    for bits, config in configs.items():
        wd = WikidataClient(cache_path=CACHE)
        strategy = LabelFirstGrounding(wd, config)
        n_escalated = 0
        judge_cache: dict = {}
        for g in gold:
            mention, _context_source = _mention(g, rows, context_lookup)
            try:
                result = strategy.ground(mention, judge=None, scope_id=g["paragraph_id"], judge_cache=judge_cache)
            except RuntimeError:
                continue
            if result.trace.get("resolved_by") == "judge_unavailable":
                # judge=None turns every escalation into judge_unavailable, so this
                # count IS the escalation count for this config.
                n_escalated += 1
        cost = n_escalated * EST_COST_PER_JUDGE_CALL
        total_est += cost
        print(f"{bits:<8}{len(gold):>8}{n_escalated:>18}{cost:>15.4f}")
    print(f"\nTotal estimated cost across {len(configs)} configs: ${total_est:.4f}")
    return total_est


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print cost estimate only, write nothing")
    ap.add_argument("--max-usd", type=float, default=5.0, help="hard cumulative spend cap for the run")
    ap.add_argument("--configs", type=str, default=None, help="comma-separated bit-string subset, e.g. 111,000")
    args = ap.parse_args()

    bits_subset = args.configs.split(",") if args.configs else None
    configs = _configs(bits_subset)
    gold = _gold()
    rows = _seed_rows()
    context_lookup = _context_lookup()

    if args.dry_run:
        est_total = _dry_run_estimate(configs, gold, rows, context_lookup)
        if est_total > args.max_usd:
            print(f"\nABORT: forecast ${est_total:.4f} exceeds --max-usd ${args.max_usd:.2f}. "
                  "Raise the cap or narrow --configs before running for real.")
            return 1
        print(f"\nForecast ${est_total:.4f} is within --max-usd ${args.max_usd:.2f}. Dry run only — nothing written.")
        return 0

    guard = BudgetGuard(args.max_usd)
    judge = _build_judge(guard)
    if judge is None:
        print("WARNING: OPENAI_API_KEY not found — falling back to judge=None. "
              "Every escalation will be classified as judge_unavailable; "
              "deterministic exact_label/no_candidates paths are still valid.")

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    print(f"{'config':<8}{'n':>6}{'qid_acc':>10}{'ci95':>16}{'escalation':>12}{'judge_calls':>13}{'cost_usd':>10}")
    for bits, config in configs.items():
        wd = WikidataClient(cache_path=CACHE)
        traces, scored = _run_config(bits, config, gold, rows, wd, judge, guard, context_lookup)

        out_dir = OUT_ROOT / bits / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "traces.jsonl").open("w", encoding="utf-8") as fh:
            for t in traces:
                fh.write(json.dumps(t, ensure_ascii=False) + "\n")

        metrics = _metrics_v1(bits, config, gold, scored)
        (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")

        qa = metrics["qid_accuracy_groundable"]
        val = f"{qa['value']:.3f}" if qa["value"] is not None else "n/a"
        print(f"{bits:<8}{qa['total']:>6}{val:>10}{str(qa['ci95']):>16}"
              f"{metrics['escalation_rate']:>12.3f}{metrics['n_judge_calls']:>13}{metrics['judge_cost_usd']:>10.4f}")

        if bits == "111" and qa["value"] is not None:
            drop_terms = round((REFERENCE_G3_ACCURACY - qa["value"]) * qa["total"])
            if drop_terms > FLAG_TERM_DROP:
                print(f"  FLAG: config 111 qid_accuracy {qa['value']:.3f} is {drop_terms} terms below "
                      f"reference {REFERENCE_G3_ACCURACY} (threshold: >{FLAG_TERM_DROP} terms) — "
                      "investigate traces.jsonl before closing the block.")
            else:
                print(f"  OK: config 111 qid_accuracy {qa['value']:.3f} vs reference {REFERENCE_G3_ACCURACY} "
                      f"(delta {drop_terms} terms, within tolerance).")

        if guard.stopped_reason is not None:
            print(f"\nSTOPPED: {guard.stopped_reason}")
            print(f"Completed configs before stop are written under {OUT_ROOT}/<bits>/{run_id}/.")
            break

    print(f"\nTotal judge_cost_usd spent this run: ${guard.spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
