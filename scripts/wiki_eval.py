#!/usr/bin/env python3
"""Wiki-eval CLI (W5): build-gt / run / ablate / report over 100 RU-Wikipedia
history articles, evaluating G6 label_first NER+grounding against human
hyperlink annotations.

Spec: docs/superpowers/specs/2026-07-03-wiki-eval-design.md.
Plan: docs/superpowers/plans/2026-07-03-wiki-eval-plan.md (W5).

Usage (from the worktree root, with PYTHONPATH=src):
  python scripts/wiki_eval.py build-gt --titles <file> --out data/eval/wiki/gt.jsonl --cache data/eval/wiki/pages
  python scripts/wiki_eval.py run --gt data/eval/wiki/gt.jsonl --config 111 --dry-run
  python scripts/wiki_eval.py run --gt data/eval/wiki/gt.jsonl --config 111 --max-usd 40
  python scripts/wiki_eval.py ablate --gt data/eval/wiki/gt.jsonl --max-usd 40 --dry-run
  python scripts/wiki_eval.py report --gt data/eval/wiki/gt.jsonl --pred reports/terminology/wiki-eval/111/<run_id>
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.base import GroundingConfig
from palimpsest.terminology.evaluation import metrics as M
from palimpsest.terminology.evaluation import predict, report, wiki_gt
from palimpsest.terminology.evaluation.tokenize import flatten
from palimpsest.terminology.extract import (
    DEFAULT_NER_PROMPT,
    llm_surfaces,
    mentions_from_surfaces,
    parse_surfaces,
)
from palimpsest.terminology.grounding import LabelFirstGrounding
from palimpsest.terminology.grounding.match import norm
from palimpsest.terminology.wikidata import WikidataClient

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_GT = ROOT / "data/eval/wiki/gt.jsonl"
DEFAULT_PAGES_CACHE = ROOT / "data/eval/wiki/pages"
WIKIDATA_CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
OUT_ROOT = ROOT / "reports/terminology/wiki-eval"

# Extraction + judge provider. Default = CloseRouter (OpenAI-compatible gateway at
# OPENROUTER_BASE_URL) running openai/gpt-5.4-mini pinned to provider-8. Model and
# route are env-overridable (CLOSEROUTER_MODEL / CLOSEROUTER_PROVIDER). provider-8
# is chosen over provider-6 and "auto": on a 2026-07-05 probe both worked 10/10 but
# provider-6 (where "auto" routes gpt-5.4-mini) padded ~4400 hidden prompt tokens
# per call vs 21 on provider-8 — a ~200x input-cost trap. CloseRouter's WAF rejects
# the OpenAI SDK's default User-Agent; palimpsest.llm.client sends a neutral one.
# WIKI_EVAL_PROVIDER switches the gateway: "openrouter" (openrouter.ai) or
# "openai-direct" (gpt-4o-mini on api.openai.com) as fallbacks. To measure the
# 2026-07-02 NER tournament winner instead, set CLOSEROUTER_MODEL=anthropic/claude-haiku-4.5.
WIKI_EVAL_PROVIDER = os.environ.get("WIKI_EVAL_PROVIDER", "closerouter")
CLOSEROUTER_MODEL = os.environ.get("CLOSEROUTER_MODEL", "openai/gpt-5.4-mini")
CLOSEROUTER_PROVIDER = os.environ.get("CLOSEROUTER_PROVIDER", "provider-8")

JUDGE_MAX_TOKENS = 512

if WIKI_EVAL_PROVIDER == "closerouter":
    _CR_BASE = os.environ.get("OPENROUTER_BASE_URL", "https://api.closerouter.dev/v1")
    _CR_EXTRA = {"provider": CLOSEROUTER_PROVIDER}
    EXTRACT_MODEL = JUDGE_MODEL = CLOSEROUTER_MODEL
    EXTRACT_BASE_URL = JUDGE_BASE_URL = _CR_BASE
    EXTRACT_API_KEY_ENV = JUDGE_API_KEY_ENV = "OPENROUTER_API_KEY"
    EXTRACT_EXTRA_BODY = JUDGE_EXTRA_BODY = _CR_EXTRA
elif WIKI_EVAL_PROVIDER == "openrouter":
    EXTRACT_MODEL = JUDGE_MODEL = "anthropic/claude-haiku-4.5"
    EXTRACT_BASE_URL = JUDGE_BASE_URL = "https://openrouter.ai/api/v1"
    EXTRACT_API_KEY_ENV = JUDGE_API_KEY_ENV = "OPENROUTER_API_KEY"
    EXTRACT_EXTRA_BODY = JUDGE_EXTRA_BODY = None
else:  # openai-direct fallback
    EXTRACT_MODEL = JUDGE_MODEL = "gpt-4o-mini"
    EXTRACT_BASE_URL = JUDGE_BASE_URL = "https://api.openai.com/v1"
    EXTRACT_API_KEY_ENV = JUDGE_API_KEY_ENV = "OPENAI_API_KEY"
    EXTRACT_EXTRA_BODY = JUDGE_EXTRA_BODY = None

# E-D11/Sec.11: pre-call reservation cap + hard call-count ceiling.
MAX_JUDGE_CALLS = 900
DEFAULT_MAX_USD = 40.0

# Conservative per-call price estimate (gpt-4o-mini list price, USD/token),
# mirrors eval_grounding.py -- used only for the pre-call reservation and
# --dry-run forecast, settled against real usage.cost when the provider
# reports it (E-D12).
PRICE_IN = 0.15 / 1_000_000
PRICE_OUT = 0.60 / 1_000_000
EST_PROMPT_TOKENS = 1000
EST_COMPLETION_TOKENS = JUDGE_MAX_TOKENS
EST_COST_PER_JUDGE_CALL = EST_PROMPT_TOKENS * PRICE_IN + EST_COMPLETION_TOKENS * PRICE_OUT

ALL_CONFIG_BITS = ["".join(p) for p in itertools.product("01", repeat=3)]


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


def _config_from_bits(bits: str) -> GroundingConfig:
    use_lemma, use_fallbacks, match_aliases = (c == "1" for c in bits)
    return GroundingConfig(use_lemma=use_lemma, use_fallbacks=use_fallbacks, match_aliases=match_aliases)


class BudgetGuard:
    """Provider-agnostic in-process pre-call spend cap (E-D11). Identical
    contract to eval_grounding.py's guard: reserve() before every judge call,
    settle() after with the real cost once known."""

    def __init__(self, max_usd: float) -> None:
        self.max_usd = max_usd
        self.spent = 0.0
        self.n_calls = 0
        self.stopped_reason: str | None = None

    def can_reserve(self, est: float) -> bool:
        if self.stopped_reason is not None:
            return False
        if self.n_calls + 1 > MAX_JUDGE_CALLS:
            self.stopped_reason = f"MAX_JUDGE_CALLS={MAX_JUDGE_CALLS} reached"
            return False
        if self.spent + est > self.max_usd:
            self.stopped_reason = f"budget cap ${self.max_usd:.2f} hit (spent ${self.spent:.4f} + est ${est:.4f})"
            return False
        return True

    def reserve(self, est: float) -> None:
        self.spent += est
        self.n_calls += 1

    def settle(self, est: float, actual: float | None) -> None:
        if actual is None:
            return
        self.spent += actual - est


# ── extractor + judge builders (E-D16 bridge) ────────────────────────────────


def _build_extract_fn(guard: BudgetGuard | None = None):
    """Real NER extraction entry point: LLMClient + DEFAULT_NER_PROMPT ->
    llm_surfaces -> mentions_from_surfaces -> list[TermMention].

    Mirrors term_pipeline.py's `extract --real` path (same prompt, validated
    substrings only) but wrapped as the single-paragraph `extract_fn` predict.py
    expects. Lazy-imports LLMClient so --dry-run/--help stay importable without
    `openai` installed (LLMClient-only by design, no direct openai import
    outside palimpsest.llm.client).
    """
    from palimpsest.llm.client import LLMClient, LLMConfig

    _load_dotenv()
    api_key = os.environ.get(EXTRACT_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{EXTRACT_API_KEY_ENV} not set (checked .env and environment) -- required for extraction")

    client = LLMClient(LLMConfig(model=EXTRACT_MODEL, base_url=EXTRACT_BASE_URL, api_key=api_key,
                                 temperature=0, extra_body=EXTRACT_EXTRA_BODY))

    def extractor(source: str) -> list[dict]:
        reply = client.complete_retrying(system="", user=DEFAULT_NER_PROMPT.replace("{{source}}", source))
        return parse_surfaces(reply.content)

    def extract_fn(paragraph: str):
        surfaces = llm_surfaces(paragraph, extractor=extractor)
        return mentions_from_surfaces(paragraph, surfaces)

    return extract_fn


def _build_judge(guard: BudgetGuard):
    """Judge on the same provider as the extractor (default CloseRouter
    claude-haiku-4.5, pinned via CLOSEROUTER_PROVIDER). Returns None when the
    provider key is unset so the caller can fall back to judge=None."""
    from palimpsest.llm.client import LLMClient, LLMConfig

    _load_dotenv()
    api_key = os.environ.get(JUDGE_API_KEY_ENV)
    if not api_key:
        return None

    client = LLMClient(LLMConfig(
        model=JUDGE_MODEL, base_url=JUDGE_BASE_URL, api_key=api_key,
        temperature=0, max_tokens=JUDGE_MAX_TOKENS, extra_body=JUDGE_EXTRA_BODY,
    ))

    def judge(prompt: str) -> dict:
        if not guard.can_reserve(EST_COST_PER_JUDGE_CALL):
            raise RuntimeError(guard.stopped_reason)
        guard.reserve(EST_COST_PER_JUDGE_CALL)
        result = client.complete_retrying(
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
        return json.loads(text)

    return judge


def _canonicalize_fn(wd: WikidataClient):
    """QID -> canonical QID via the same redirect path GT used (E-D18):
    wbgetentities on a redirect returns the target under `entity["id"]`."""
    cache: dict[str, str] = {}

    def canonicalize(qid: str) -> str:
        if qid in cache:
            return cache[qid]
        entities = wd.get_entities([qid], props="")
        entity = entities.get(qid) or {}
        canonical = entity.get("id", qid)
        cache[qid] = canonical
        return canonical

    return canonicalize


def _p31_of_fn(wd: WikidataClient):
    """QID -> set of target P31 (instance-of) QIDs, for the chronology filter."""
    cache: dict[str, set[str]] = {}

    def p31_of(qid: str) -> set[str]:
        if qid in cache:
            return cache[qid]
        entities = wd.get_entities([qid], props="claims")
        entity = entities.get(qid) or {}
        claims = entity.get("claims", {}).get("P31", [])
        values: set[str] = set()
        for claim in claims:
            snak = claim.get("mainsnak", {})
            value = snak.get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                values.add(value["id"])
        cache[qid] = values
        return values

    return p31_of


def _label_exists_fn(wd: WikidataClient):
    """P3 predicate (spec Sec.4): does `surface` exist as a Wikidata RU label
    anywhere reachable via wbsearchentities exact-prefix search?"""
    cache: dict[str, bool] = {}

    def label_exists(surface: str) -> bool:
        key = norm(surface)
        if key in cache:
            return cache[key]
        hits = wd.search_entities(surface, lang="ru", limit=1)
        exists = any(norm(h.get("label", "")) == key for h in hits)
        cache[key] = exists
        return exists

    return label_exists


# ── gt.jsonl I/O ──────────────────────────────────────────────────────────────


def _load_gt(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


# ── build-gt ──────────────────────────────────────────────────────────────────


def cmd_build_gt(args) -> int:
    titles_path = Path(args.titles)
    lines = [l.strip() for l in titles_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # each line: "<title>" or "<title>\t<stratum>"; a line explicitly marked
    # "hard" in the input file is a forced hardness seed (spec E-D3).
    titles: dict[str, str] = {}
    stratum_map: dict[str, str] = {}
    seeds: list[str] = []
    for line in lines:
        parts = line.split("\t")
        title = parts[0].strip()
        stratum = parts[1].strip() if len(parts) > 1 else "typical"
        stratum_map[title] = stratum
        if stratum == "hard":
            seeds.append(title)

    wd = WikidataClient(cache_path=WIKIDATA_CACHE)
    # Single shared cache: the hardness pre-pass and build_gt's internal
    # anchor-title->QID lookups reuse the same resolved titles instead of
    # each re-fetching identical batches over the network (spec: call once).
    shared_titles_to_qids = wiki_gt.memoized_titles_to_qids()

    qid_map = shared_titles_to_qids(list(stratum_map.keys()))
    for title, entry in qid_map.items():
        titles[title] = (entry or {}).get("qid") or ""

    pages_gt = {}
    for title in titles:
        try:
            html = wiki_gt.fetch_html(title, args.cache)
        except wiki_gt.WikiFetchError:
            continue
        anchor_titles = sorted(wiki_gt._collect_anchor_titles(html))
        title_to_qid = shared_titles_to_qids(anchor_titles) if anchor_titles else {}
        pages_gt[title] = wiki_gt.extract_gt(html, title_to_qid, p31_of=_p31_of_fn(wd))
    hardness_scores = wiki_gt.hardness(pages_gt)

    # Hard-seed disclosure (E-D3): how many of the hard-stratum pages are
    # forced seeds vs. score-ranked, and each seed's hardness percentile.
    # select_articles reasons over the FULL pool so the disclosure reflects
    # every candidate's rank, not just the pre-labeled subset.
    selection = wiki_gt.select_articles(hardness_scores, n_hard=len(seeds) or 50, seeds=seeds)

    summary = wiki_gt.build_gt(
        titles,
        args.cache,
        args.out,
        stratum_of=lambda t: stratum_map.get(t, "typical"),
        hardness_of=lambda t: hardness_scores.get(t, 0.0),
        p31_of=_p31_of_fn(wd),
        titles_to_qids_fn=shared_titles_to_qids,
    )
    summary["n_hard_seeds"] = selection.n_hard_seeds
    summary["seed_percentiles"] = selection.seed_percentiles
    summary_path = Path(str(args.out) + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    n = sum(1 for _ in Path(args.out).open(encoding="utf-8"))
    print(f"wrote {n} articles -> {args.out}")
    print(f"n_hard_seeds={selection.n_hard_seeds}  seed_percentiles={selection.seed_percentiles}")
    return 0


# ── run ───────────────────────────────────────────────────────────────────────


def _run_one_config(bits: str, gt_records: list[dict], cache_dir: str, *, dry_run: bool, guard: BudgetGuard | None) -> tuple[list[dict], dict]:
    config = _config_from_bits(bits)
    wd = WikidataClient(cache_path=WIKIDATA_CACHE)
    grounder = LabelFirstGrounding(wd, config)
    canonicalize = _canonicalize_fn(wd)

    judge = None if dry_run else _build_judge(guard)
    extract_fn = None if dry_run else _build_extract_fn(guard)

    def ground_fn(mention, *, judge=judge, scope_id=None, judge_cache=None):
        return grounder.ground(mention, judge=judge, scope_id=scope_id, judge_cache=judge_cache)

    pred_records: list[dict] = []
    n_paragraphs_total = 0
    n_mentions_est = 0

    for rec in gt_records:
        title = rec["title"]
        # tokens[] is a flat token list, not paragraphs -- re-derive paragraphs
        # from the cached HTML so predict_tuples gets the same chunking wiki_gt used.
        html_path = Path(cache_dir) / f"{wiki_gt._safe_filename(title)}.html"
        if not html_path.exists():
            continue
        html = html_path.read_text(encoding="utf-8")
        article_text = flatten(html)
        paragraphs = article_text.split("\n")
        n_paragraphs_total += len(paragraphs)

        if dry_run:
            n_mentions_est += sum(len(p.split()) for p in paragraphs) // 20  # rough forecast only
            continue

        judge_cache: dict = {}
        result = predict.predict_tuples(
            article_text, paragraphs, extract_fn, ground_fn,
            judge=judge, judge_cache=judge_cache, scope_id=title, canonicalize=canonicalize,
        )
        for r in result["records"]:
            pred_records.append({"title": title, **r})

        if guard is not None and guard.stopped_reason is not None:
            break

    counters = {
        "n_articles": len(gt_records),
        "n_paragraphs": n_paragraphs_total,
        "n_pred_mentions": n_mentions_est if dry_run else len(pred_records),
    }
    return pred_records, counters


def cmd_run(args) -> int:
    gt_records = _load_gt(Path(args.gt))
    guard = BudgetGuard(args.max_usd)

    if args.dry_run:
        _, counters = _run_one_config(args.config, gt_records, args.cache, dry_run=True, guard=None)
        # Forecast: 1 judge call per ~3 mentions (rough escalation-rate prior,
        # matches eval_grounding.py's dry-run intent -- an upper-bound sanity
        # check, not a precise simulation, per spec Sec.5 cap-reconciliation).
        est_escalations = counters["n_pred_mentions"] // 3
        est_cost = est_escalations * EST_COST_PER_JUDGE_CALL
        print(f"config={args.config}  articles={counters['n_articles']}  paragraphs={counters['n_paragraphs']}")
        print(f"est_mentions={counters['n_pred_mentions']}  est_judge_calls={est_escalations}  est_cost_usd={est_cost:.4f}")
        if est_cost > args.max_usd:
            print(f"\nABORT: forecast ${est_cost:.4f} exceeds --max-usd ${args.max_usd:.2f}.")
            return 1
        print(f"\nForecast ${est_cost:.4f} is within --max-usd ${args.max_usd:.2f}. Dry run only -- nothing written.")
        return 0

    pred_records, counters = _run_one_config(args.config, gt_records, args.cache, dry_run=False, guard=guard)

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = OUT_ROOT / args.config / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pred.jsonl").open("w", encoding="utf-8") as fh:
        for r in pred_records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"config={args.config}  run_id={run_id}  {counters}")
    print(f"spent=${guard.spent:.4f}  judge_calls={guard.n_calls}")
    if guard.stopped_reason:
        print(f"STOPPED: {guard.stopped_reason}")
    print(f"wrote -> {out_dir / 'pred.jsonl'}")
    return 0


def cmd_ablate(args) -> int:
    for bits in ALL_CONFIG_BITS:
        sub_args = argparse.Namespace(**{**vars(args), "config": bits})
        rc = cmd_run(sub_args)
        if rc != 0:
            return rc
    return 0


# ── report ────────────────────────────────────────────────────────────────────
#
# GT/pred token indices are ARTICLE-LOCAL (reset to 0 per article -- spec
# E-D6). Aggregation must therefore group by article title and match/slice
# each article independently (metrics.aggregate_corpus); flattening all
# articles' tuples into one list before matching would cross-match identical
# (index, qid) pairs from unrelated articles.


def _resolved_by_of_for_article(pred_records: list[dict]) -> dict[int, str]:
    return {r["index"]: r["resolved_by"] for r in pred_records if r.get("resolved_by")}


def _stratum_of_for_article(gt_tuples: list[tuple], stratum: str) -> dict[int, str]:
    return {t[0]: stratum for t in gt_tuples}


def _type_of_for_article(gt_tuples: list[tuple]) -> dict[int, str]:
    """named vs term, classified by GT anchor surface capitalization (spec Sec.4 caveat)."""
    return {t[0]: ("named" if t[1][:1].isupper() else "term") for t in gt_tuples}


def cmd_report(args) -> int:
    gt_records = _load_gt(Path(args.gt))

    pred_dir = Path(args.pred)
    pred_path = pred_dir / "pred.jsonl"
    all_pred_records = [json.loads(l) for l in pred_path.open(encoding="utf-8") if l.strip()] if pred_path.exists() else []

    pred_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in all_pred_records:
        pred_by_title[r["title"]].append(r)

    articles: list[M.ArticleTuples] = []
    for rec in gt_records:
        gt_tuples = [tuple(t) for t in rec["gt_tuples"]]
        title_pred_records = pred_by_title.get(rec["title"], [])
        pred_tuples = [
            (r["index"], r["surface"], r["qid"], r["span_len"])
            for r in title_pred_records if r.get("qid") is not None
        ]
        articles.append(
            {
                "gt_tuples": gt_tuples,
                "pred_tuples": pred_tuples,
                "resolved_by_of": _resolved_by_of_for_article(title_pred_records),
                "stratum_of": _stratum_of_for_article(gt_tuples, rec["stratum"]),
                "type_of": _type_of_for_article(gt_tuples),
            }
        )

    result = M.aggregate_corpus(articles)

    n_gt_tuples = sum(len(a["gt_tuples"]) for a in articles)
    meta = {
        "run_id": pred_dir.name,
        "config": pred_dir.parent.name,
        "n_articles": len(gt_records),
        "n_gt_tuples": n_gt_tuples,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    metrics_out = pred_dir / "metrics.json"
    metrics_out.write_text(json.dumps({**result, "meta": meta}, ensure_ascii=False, indent=1), encoding="utf-8")

    html_body = report.render_html(result, meta)
    html_doc = f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Wiki-eval report — {meta['config']}</title></head><body>{html_body}</body></html>"
    report_out = pred_dir / "report.html"
    report_out.write_text(html_doc, encoding="utf-8")

    print(f"wrote {metrics_out}")
    print(f"wrote {report_out}")
    print(f"recall m2 = {result['recall']['m2']['value']}")
    return 0


# ── argparse ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build-gt", help="fetch + extract GT tuples from a title list (free)")
    p_build.add_argument("--titles", required=True, help="file: one title per line, optional \\tstratum suffix")
    p_build.add_argument("--out", default=str(DEFAULT_GT))
    p_build.add_argument("--cache", default=str(DEFAULT_PAGES_CACHE))
    p_build.set_defaults(func=cmd_build_gt)

    p_run = sub.add_parser("run", help="ground one config over gt.jsonl (paid: extractor + judge)")
    p_run.add_argument("--gt", default=str(DEFAULT_GT))
    p_run.add_argument("--cache", default=str(DEFAULT_PAGES_CACHE))
    p_run.add_argument("--config", default="111", help="3-bit config id, e.g. 111 = use_lemma+use_fallbacks+match_aliases")
    p_run.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    p_run.add_argument("--dry-run", action="store_true", help="print cost forecast only, write nothing")
    p_run.set_defaults(func=cmd_run)

    p_ablate = sub.add_parser("ablate", help="loop `run` over all 8 configs, sharing the judge cache")
    p_ablate.add_argument("--gt", default=str(DEFAULT_GT))
    p_ablate.add_argument("--cache", default=str(DEFAULT_PAGES_CACHE))
    p_ablate.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    p_ablate.add_argument("--dry-run", action="store_true")
    p_ablate.set_defaults(func=cmd_ablate)

    p_report = sub.add_parser("report", help="offline recompute: metrics.json + report.html from persisted pred + gt")
    p_report.add_argument("--gt", default=str(DEFAULT_GT))
    p_report.add_argument("--pred", required=True, help="run dir containing pred.jsonl, e.g. reports/terminology/wiki-eval/111/<run_id>")
    p_report.add_argument("--ablation", action="store_true", help="reserved for a future multi-config comparison report")
    p_report.set_defaults(func=cmd_report)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
