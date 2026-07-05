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
  python scripts/wiki_eval.py run --gt data/eval/wiki/gt.jsonl --config 111 --model openai/gpt-5.5 --provider provider-3 --max-usd 12 --max-judge-calls 5000
  python scripts/wiki_eval.py ablate --gt data/eval/wiki/gt.jsonl --max-usd 40 --dry-run
  python scripts/wiki_eval.py report --gt data/eval/wiki/gt.jsonl --pred reports/terminology/wiki-eval/<model-slug>/111/<run_id>
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
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
# OPENROUTER_BASE_URL) running google/gemini-3.1-flash-lite pinned to provider-9.
# Model and route are overridable three ways, in priority order: CLI --model/
# --provider (ticket 002, model-comparison runs) > CLOSEROUTER_MODEL/
# CLOSEROUTER_PROVIDER env vars > the hardcoded defaults below. provider-9 was
# verified on a 2026-07-05 probe: 10/10, ~1.4s, honest prompt tokens (5),
# cost surfaced — the fastest/cheapest clean route in the fleet. Pin an explicit
# route because "auto" can land on a reseller-padded provider for some models
# (e.g. gpt-5.4-mini -> provider-6, +4400 hidden prompt tokens/call). CloseRouter's
# WAF rejects the OpenAI SDK's default User-Agent; palimpsest.llm.client sends a
# neutral one. WIKI_EVAL_PROVIDER switches the gateway: "openrouter" (openrouter.ai)
# or "openai-direct" (gpt-4o-mini on api.openai.com) as fallbacks -- --model/
# --provider only affect the closerouter branch (see _resolve_route).
WIKI_EVAL_PROVIDER = os.environ.get("WIKI_EVAL_PROVIDER", "closerouter")
CLOSEROUTER_MODEL = os.environ.get("CLOSEROUTER_MODEL", "google/gemini-3.1-flash-lite")
CLOSEROUTER_PROVIDER = os.environ.get("CLOSEROUTER_PROVIDER", "provider-9")

JUDGE_MAX_TOKENS = 512


def _resolve_route(model: str | None = None, provider: str | None = None) -> dict:
    """Resolve the extractor+judge route config for this call.

    Computed as a function (not module-level constants) so CLI ``--model``/
    ``--provider`` always win regardless of import order -- the previous
    design baked ``CLOSEROUTER_MODEL``/``CLOSEROUTER_PROVIDER`` into
    module-level constants at import time, before argparse had even run
    (ticket 002). ``model``/``provider`` override the env vars only on the
    default ``closerouter`` branch; the ``openrouter``/``openai-direct``
    fallbacks keep their own fixed model, unaffected by CLI overrides.
    """
    cr_model = model or CLOSEROUTER_MODEL
    cr_provider = provider or CLOSEROUTER_PROVIDER
    if WIKI_EVAL_PROVIDER == "closerouter":
        base = os.environ.get("OPENROUTER_BASE_URL", "https://api.closerouter.dev/v1")
        return {
            "extract_model": cr_model, "judge_model": cr_model,
            "extract_base_url": base, "judge_base_url": base,
            "extract_api_key_env": "OPENROUTER_API_KEY", "judge_api_key_env": "OPENROUTER_API_KEY",
            "extract_extra_body": {"provider": cr_provider}, "judge_extra_body": {"provider": cr_provider},
        }
    elif WIKI_EVAL_PROVIDER == "openrouter":
        return {
            "extract_model": "anthropic/claude-haiku-4.5", "judge_model": "anthropic/claude-haiku-4.5",
            "extract_base_url": "https://openrouter.ai/api/v1", "judge_base_url": "https://openrouter.ai/api/v1",
            "extract_api_key_env": "OPENROUTER_API_KEY", "judge_api_key_env": "OPENROUTER_API_KEY",
            "extract_extra_body": None, "judge_extra_body": None,
        }
    else:  # openai-direct fallback
        return {
            "extract_model": "gpt-4o-mini", "judge_model": "gpt-4o-mini",
            "extract_base_url": "https://api.openai.com/v1", "judge_base_url": "https://api.openai.com/v1",
            "extract_api_key_env": "OPENAI_API_KEY", "judge_api_key_env": "OPENAI_API_KEY",
            "extract_extra_body": None, "judge_extra_body": None,
        }


# E-D11/Sec.11: pre-call reservation cap + hard call-count ceiling (judge calls
# only -- see BudgetGuard; extraction calls are bounded by --max-usd alone,
# there are ~1 per paragraph and that's already bounded by the corpus size).
MAX_JUDGE_CALLS = 900
DEFAULT_MAX_USD = 40.0

# Conservative per-call price estimate (gpt-4o-mini list price, USD/token),
# mirrors eval_grounding.py -- used only for the pre-call reservation and
# --dry-run forecast, settled against real usage.cost when the provider
# reports it (E-D12). Shared fallback for both extraction and judge calls;
# not a per-model price table (that's ticket 003's provider-triage concern).
PRICE_IN = 0.15 / 1_000_000
PRICE_OUT = 0.60 / 1_000_000
EST_PROMPT_TOKENS = 1000
EST_COMPLETION_TOKENS = JUDGE_MAX_TOKENS
EST_COST_PER_JUDGE_CALL = EST_PROMPT_TOKENS * PRICE_IN + EST_COMPLETION_TOKENS * PRICE_OUT

# Extraction prompt = DEFAULT_NER_PROMPT template (~500 tokens) + one paragraph
# of RU source text; completion = a JSON list of extracted surfaces, typically
# well short of the extractor's 4096-token LLMConfig default. Deliberately
# generous vs. a typical paragraph so the estimate doesn't under-shoot (same
# worst-case-bound philosophy as EST_COST_PER_JUDGE_CALL above).
EST_EXTRACT_PROMPT_TOKENS = 1200
EST_EXTRACT_COMPLETION_TOKENS = 400
EST_COST_PER_EXTRACT_CALL = EST_EXTRACT_PROMPT_TOKENS * PRICE_IN + EST_EXTRACT_COMPLETION_TOKENS * PRICE_OUT

ALL_CONFIG_BITS = ["".join(p) for p in itertools.product("01", repeat=3)]


def model_slug(model: str, provider: str) -> str:
    """`<model>/<provider>` -> a filesystem-safe run-dir segment (ticket 002):
    every ``/`` in the model id becomes ``--``, then ``--<provider>`` is
    appended. Dots are preserved (dotted model names stay dotted in filenames,
    working-style.md "Naming & PRs") -- e.g. ``openai/gpt-5.5`` + ``provider-3``
    -> ``openai--gpt-5.5--provider-3``.
    """
    return f"{model.replace('/', '--')}--{provider}"


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
    contract to eval_grounding.py's guard: reserve() before every call,
    settle() after with the real cost once known.

    Ticket 002: extraction calls now share this same guard (previously only
    judge calls were reserved/settled -- a real accounting hole for the
    ~12k/100-article extraction volume). ``kind`` ("extract"/"judge") tags
    each reservation for the meta.json spend/call-count split; only "judge"
    calls count against ``max_judge_calls`` (extraction has no count
    ceiling of its own, just the shared dollar cap). Thread-safe: phase 1 of
    prediction (ticket 002) runs extract_fn over a paragraph's siblings
    concurrently via a ThreadPoolExecutor, so multiple threads can call
    can_reserve/reserve/settle at once -- every method takes ``_lock``.
    Known imprecision: can_reserve() and reserve() are separate lock
    acquisitions (matching eval_grounding.py's two-step contract), so under
    concurrency several threads can pass the check against the same
    pre-reservation ``spent`` before any of them reserves, overshooting by up
    to (concurrency-1) small per-call estimates -- bounded by
    DEFAULT_MAX_CONCURRENCY=4, consistent with this guard's existing
    worst-case-not-exact tolerance (settle() already lets actual cost exceed
    the estimate between calls)."""

    def __init__(self, max_usd: float, max_judge_calls: int = MAX_JUDGE_CALLS) -> None:
        self.max_usd = max_usd
        self.max_judge_calls = max_judge_calls
        self.spent = 0.0
        self.spent_by_kind: dict[str, float] = {"extract": 0.0, "judge": 0.0}
        self.calls_by_kind: dict[str, int] = {"extract": 0, "judge": 0}
        self.stopped_reason: str | None = None
        self._lock = threading.Lock()

    @property
    def n_calls(self) -> int:
        return self.calls_by_kind["extract"] + self.calls_by_kind["judge"]

    def can_reserve(self, est: float, *, kind: str = "judge") -> bool:
        with self._lock:
            if self.stopped_reason is not None:
                return False
            if kind == "judge" and self.calls_by_kind["judge"] + 1 > self.max_judge_calls:
                self.stopped_reason = f"max_judge_calls={self.max_judge_calls} reached"
                return False
            if self.spent + est > self.max_usd:
                self.stopped_reason = f"budget cap ${self.max_usd:.2f} hit (spent ${self.spent:.4f} + est ${est:.4f})"
                return False
            return True

    def reserve(self, est: float, *, kind: str = "judge") -> None:
        with self._lock:
            self.spent += est
            self.spent_by_kind[kind] += est
            self.calls_by_kind[kind] += 1

    def settle(self, est: float, actual: float | None, *, kind: str = "judge") -> None:
        if actual is None:
            return
        with self._lock:
            delta = actual - est
            self.spent += delta
            self.spent_by_kind[kind] += delta


# ── extractor + judge builders (E-D16 bridge) ────────────────────────────────


def _build_extract_fn(guard: BudgetGuard, *, model: str | None = None, provider: str | None = None):
    """Real NER extraction entry point: LLMClient + DEFAULT_NER_PROMPT ->
    llm_surfaces -> mentions_from_surfaces -> list[TermMention].

    Mirrors term_pipeline.py's `extract --real` path (same prompt, validated
    substrings only) but wrapped as the single-paragraph `extract_fn` predict.py
    expects. Lazy-imports LLMClient so --dry-run/--help stay importable without
    `openai` installed (LLMClient-only by design, no direct openai import
    outside palimpsest.llm.client). ``guard`` is required (not optional) since
    ticket 002: every extraction call now reserves/settles against it, same
    contract as the judge below -- this closure may be invoked concurrently
    from several ThreadPoolExecutor workers (phase 1 of prediction), which is
    exactly why BudgetGuard grew a lock.
    """
    from palimpsest.llm.client import LLMClient, LLMConfig

    _load_dotenv()
    route = _resolve_route(model, provider)
    api_key = os.environ.get(route["extract_api_key_env"])
    if not api_key:
        raise RuntimeError(f"{route['extract_api_key_env']} not set (checked .env and environment) -- required for extraction")

    client = LLMClient(LLMConfig(model=route["extract_model"], base_url=route["extract_base_url"], api_key=api_key,
                                 temperature=0, extra_body=route["extract_extra_body"]))

    def extractor(source: str) -> list[dict]:
        if not guard.can_reserve(EST_COST_PER_EXTRACT_CALL, kind="extract"):
            raise RuntimeError(guard.stopped_reason)
        guard.reserve(EST_COST_PER_EXTRACT_CALL, kind="extract")
        reply = client.complete_retrying(system="", user=DEFAULT_NER_PROMPT.replace("{{source}}", source))
        actual_cost = reply.usage.cost_usd
        if actual_cost is None and reply.usage.prompt_tokens:
            actual_cost = (reply.usage.prompt_tokens * PRICE_IN
                           + reply.usage.completion_tokens * PRICE_OUT)
        guard.settle(EST_COST_PER_EXTRACT_CALL, actual_cost, kind="extract")
        return parse_surfaces(reply.content)

    def extract_fn(paragraph: str):
        surfaces = llm_surfaces(paragraph, extractor=extractor)
        return mentions_from_surfaces(paragraph, surfaces)

    return extract_fn


def _parallel_extract_fn(extract_fn, paragraphs: list[str]):
    """Phase 1 of predicting one article (ticket 002): run ``extract_fn`` over
    every paragraph CONCURRENTLY, bounded by
    ``palimpsest.llm.client.DEFAULT_MAX_CONCURRENCY`` (4). Phase 2 (grounding +
    judge, inside ``predict.predict_tuples``) stays fully sequential --
    unchanged.

    Design choice (ticket 002 asked to pick the cleanest of "a new
    predict_tuples parameter" vs. "an order-safe wrapper"): an order-safe
    wrapper. ``predict_tuples`` already calls ``extract_fn(paragraph)`` exactly
    once per paragraph, strictly in ``paragraphs`` order -- so precomputing
    every paragraph's mentions up front (``ThreadPoolExecutor.map``, which
    preserves input order in its output regardless of completion order) and
    replaying them through a positional iterator reproduces byte-identical
    tuple/stitching semantics with zero changes to ``predict.py`` or its tests.
    Replay is by POSITION, not by paragraph text -- a content-keyed cache would
    misalign whenever paragraph text repeats (e.g. blank lines from
    ``tokenize.flatten``'s split).

    Lazy-imports ``DEFAULT_MAX_CONCURRENCY`` (pulls in ``palimpsest.llm.client``
    -> ``openai``) so this module stays importable for --dry-run/--help
    without `openai` installed; this helper is only ever called from the paid,
    non-dry-run path.
    """
    from palimpsest.llm.client import DEFAULT_MAX_CONCURRENCY

    with ThreadPoolExecutor(max_workers=DEFAULT_MAX_CONCURRENCY) as pool:
        mentions_per_paragraph = list(pool.map(extract_fn, paragraphs))
    ordered = iter(mentions_per_paragraph)
    return lambda _paragraph: next(ordered)


def _build_judge(guard: BudgetGuard, *, model: str | None = None, provider: str | None = None):
    """Judge on the same provider as the extractor (default CloseRouter
    claude-haiku-4.5, pinned via CLOSEROUTER_PROVIDER). Returns None when the
    provider key is unset so the caller can fall back to judge=None."""
    from palimpsest.llm.client import LLMClient, LLMConfig

    _load_dotenv()
    route = _resolve_route(model, provider)
    api_key = os.environ.get(route["judge_api_key_env"])
    if not api_key:
        return None

    client = LLMClient(LLMConfig(
        model=route["judge_model"], base_url=route["judge_base_url"], api_key=api_key,
        temperature=0, max_tokens=JUDGE_MAX_TOKENS, extra_body=route["judge_extra_body"],
    ))

    def judge(prompt: str) -> dict:
        if not guard.can_reserve(EST_COST_PER_JUDGE_CALL, kind="judge"):
            raise RuntimeError(guard.stopped_reason)
        guard.reserve(EST_COST_PER_JUDGE_CALL, kind="judge")
        result = client.complete_retrying(
            system="You are a Wikidata disambiguation judge. Return strict JSON only.",
            user=prompt,
        )
        actual_cost = result.usage.cost_usd
        if actual_cost is None and result.usage.prompt_tokens:
            actual_cost = (result.usage.prompt_tokens * PRICE_IN
                           + result.usage.completion_tokens * PRICE_OUT)
        guard.settle(EST_COST_PER_JUDGE_CALL, actual_cost, kind="judge")

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

    # each line: "<title>" or "<title>\t<stratum>"; untagged lines default to
    # "typical" (legacy pilot-file default -- the v2 titles file tags every line).
    titles: dict[str, str] = {}
    stratum_map: dict[str, str] = {}
    for line in lines:
        parts = line.split("\t")
        title = parts[0].strip()
        stratum = parts[1].strip() if len(parts) > 1 else "typical"
        stratum_map[title] = stratum

    wd = WikidataClient(cache_path=WIKIDATA_CACHE)
    # Single shared cache: build_gt's internal anchor-title->QID lookups reuse
    # the same resolved titles instead of each re-fetching identical batches
    # over the network (spec: call once).
    shared_titles_to_qids = wiki_gt.memoized_titles_to_qids()

    qid_map = shared_titles_to_qids(list(stratum_map.keys()))
    for title, entry in qid_map.items():
        titles[title] = (entry or {}).get("qid") or ""

    summary = wiki_gt.build_gt(
        titles,
        args.cache,
        args.out,
        stratum_of=lambda t: stratum_map.get(t, "typical"),
        p31_of=_p31_of_fn(wd),
        titles_to_qids_fn=shared_titles_to_qids,
    )
    summary_path = Path(str(args.out) + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    n = sum(1 for _ in Path(args.out).open(encoding="utf-8"))
    print(f"wrote {n} articles -> {args.out}")
    return 0


# ── run ───────────────────────────────────────────────────────────────────────


def _run_one_config(bits: str, gt_records: list[dict], cache_dir: str, *, dry_run: bool, guard: BudgetGuard | None,
                     model: str | None = None, provider: str | None = None) -> tuple[list[dict], dict]:
    config = _config_from_bits(bits)
    wd = WikidataClient(cache_path=WIKIDATA_CACHE)
    grounder = LabelFirstGrounding(wd, config)
    canonicalize = _canonicalize_fn(wd)

    judge = None if dry_run else _build_judge(guard, model=model, provider=provider)
    extract_fn = None if dry_run else _build_extract_fn(guard, model=model, provider=provider)

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
        # Phase 1 (parallel, capped at DEFAULT_MAX_CONCURRENCY): extract every
        # paragraph's mentions concurrently. Phase 2 (grounding + judge, inside
        # predict_tuples) is untouched and stays sequential.
        paragraph_extract_fn = _parallel_extract_fn(extract_fn, paragraphs)
        result = predict.predict_tuples(
            article_text, paragraphs, paragraph_extract_fn, ground_fn,
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
    guard = BudgetGuard(args.max_usd, max_judge_calls=args.max_judge_calls)

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

    started_at = datetime.now(timezone.utc)
    pred_records, counters = _run_one_config(
        args.config, gt_records, args.cache, dry_run=False, guard=guard,
        model=args.model, provider=args.provider,
    )
    finished_at = datetime.now(timezone.utc)

    model = args.model or CLOSEROUTER_MODEL
    provider = args.provider or CLOSEROUTER_PROVIDER
    slug = model_slug(model, provider)
    run_id = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = OUT_ROOT / slug / args.config / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pred.jsonl").open("w", encoding="utf-8") as fh:
        for r in pred_records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta = {
        "model": model,
        "provider": provider,
        "config": args.config,
        "run_id": run_id,
        "price_in_per_token": PRICE_IN,
        "price_out_per_token": PRICE_OUT,
        "spend": {
            "total": guard.spent,
            "extract": guard.spent_by_kind["extract"],
            "judge": guard.spent_by_kind["judge"],
        },
        "calls": {
            "extract": guard.calls_by_kind["extract"],
            "judge": guard.calls_by_kind["judge"],
        },
        "max_usd": args.max_usd,
        "max_judge_calls": args.max_judge_calls,
        "stopped_reason": guard.stopped_reason,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "wall_clock_s": (finished_at - started_at).total_seconds(),
        **counters,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    print(f"model={model}  provider={provider}  config={args.config}  run_id={run_id}  {counters}")
    print(f"spent=${guard.spent:.4f} (extract=${guard.spent_by_kind['extract']:.4f} judge=${guard.spent_by_kind['judge']:.4f})"
          f"  extract_calls={guard.calls_by_kind['extract']}  judge_calls={guard.calls_by_kind['judge']}")
    if guard.stopped_reason:
        print(f"STOPPED: {guard.stopped_reason}")
    print(f"wrote -> {out_dir / 'pred.jsonl'}")
    print(f"wrote -> {out_dir / 'meta.json'}")
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
        "config": pred_dir.parent.name,  # ticket 002: config stays parent-dir-of-run_id
        "n_articles": len(gt_records),
        "n_gt_tuples": n_gt_tuples,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ticket 002: merge the run's own meta.json (model, provider, spend split,
    # wall-clock, ...) into the report meta when present -- run_meta's fields
    # fill in first, then meta's freshly-computed run_id/config/generated_at
    # win on any overlapping key (derived directly from pred_dir, authoritative).
    run_meta_path = pred_dir / "meta.json"
    if run_meta_path.exists():
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        meta = {**run_meta, **meta}

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


def _build_parser() -> argparse.ArgumentParser:
    """Pure parser construction, split out from ``main()`` so tests can parse
    argv and inspect the resulting namespace without invoking ``args.func``
    (which would make a real paid LLM call for ``run``/``ablate``)."""
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
    p_run.add_argument("--model", default=None, help="model id override (else CLOSEROUTER_MODEL env, else google/gemini-3.1-flash-lite)")
    p_run.add_argument("--provider", default=None, help="CloseRouter provider route override (else CLOSEROUTER_PROVIDER env, else provider-9)")
    p_run.add_argument("--max-judge-calls", type=int, default=MAX_JUDGE_CALLS, help="hard ceiling on judge calls (spec Sec.11)")
    p_run.add_argument("--dry-run", action="store_true", help="print cost forecast only, write nothing")
    p_run.set_defaults(func=cmd_run)

    p_ablate = sub.add_parser("ablate", help="loop `run` over all 8 configs, sharing the judge cache")
    p_ablate.add_argument("--gt", default=str(DEFAULT_GT))
    p_ablate.add_argument("--cache", default=str(DEFAULT_PAGES_CACHE))
    p_ablate.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    p_ablate.add_argument("--model", default=None, help="model id override (else CLOSEROUTER_MODEL env, else google/gemini-3.1-flash-lite)")
    p_ablate.add_argument("--provider", default=None, help="CloseRouter provider route override (else CLOSEROUTER_PROVIDER env, else provider-9)")
    p_ablate.add_argument("--max-judge-calls", type=int, default=MAX_JUDGE_CALLS, help="hard ceiling on judge calls (spec Sec.11)")
    p_ablate.add_argument("--dry-run", action="store_true")
    p_ablate.set_defaults(func=cmd_ablate)

    p_report = sub.add_parser("report", help="offline recompute: metrics.json + report.html from persisted pred + gt")
    p_report.add_argument("--gt", default=str(DEFAULT_GT))
    p_report.add_argument("--pred", required=True, help="run dir containing pred.jsonl, e.g. reports/terminology/wiki-eval/<model-slug>/111/<run_id>")
    p_report.add_argument("--ablation", action="store_true", help="reserved for a future multi-config comparison report")
    p_report.set_defaults(func=cmd_report)

    return ap


def main() -> int:
    args = _build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
