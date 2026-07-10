#!/usr/bin/env python3
"""Sitelink-rung contamination replay (W5 follow-up): recompute "clean"
(sitelink-off) G6 wiki-eval recall for one model run, by REPLAYING the
candidate-generation ladder for every grounded prediction and dropping the
ones the ladder could only resolve via its last-resort rung.

Method: docs/experiments/2026-07-05-model-comparison/drafts/sitelink-contamination.md.
Ladder: src/palimpsest/terminology/grounding/candidates.py::generate_candidates
  1. wbsearchentities(lemma), wbsearchentities(surface)
  2. if 0 hits and config.use_cirrus: search_cirrus(lemma), search_cirrus(surface)
  3. if still 0 and config.use_sitelink: wikipedia_wikibase_item(lemma or surface)
     -- source "wikipedia_langlink" -- shares its title->QID mapping with the
     wiki-eval GT construction itself, hence "contamination" (spec Sec.4).

Data source: LIVE Wikidata queries, not a cached replay. The per-model
``reports/terminology/wikidata_cache.<model>.jsonl`` caches the original
analysis depended on were never committed and are gone (container swap), and
``pred.jsonl`` itself carries no step attribution (only ``resolved_by`` --
``exact_label``/``llm_disambiguation``/``judge_unavailable`` -- which grounding
STRATEGY resolved it, not which SEARCH rung supplied the candidate). So this
script reconstructs the ladder decision by calling the real
``generate_candidates`` once per unique (lemma, surface) pair among the run's
own grounded predictions, via the project's own ``WikidataClient`` (stdlib
urllib, on-disk JSONL cache, bounded concurrency) -- no new dependency, same
polite-crawl contract the pipeline itself uses. ``enrich_top=0`` skips
``wbgetentities`` entirely: this replay only needs ``source`` (which rung
fired), never the enriched candidate metadata, so it costs at most 3 requests
per unique form pair instead of 4.

The ladder is a pure function of (lemma, surface, lang, config) -- independent
of which article/occurrence a mention came from -- so this is a faithful,
deterministic reconstruction of the original run's decision, just recomputed
against Wikidata's current (rather than that day's cached) content. On a
*warm* on-disk ``--cache`` (populated by a prior run of this same script
against the same ``--pred`` dir) every lookup is a cache hit and the replay
makes zero network calls; ``run()`` asserts this via the client's own
``n_network_calls`` counter and raises rather than silently mixing cached and
live data, unless ``--allow-network`` is passed explicitly.

Full-metrics extension (2026-07-09, paper Table C): beyond the headline
``R_doc_full``/``R_doc_clean`` (M3), ``run()`` now also computes clean/full
``R_strict`` (M1), ``R_span`` (M2), and precision ``P_mention``/``P_type``
(P1/P2) for the SAME replayed clean/full prediction sets, via
``metrics.aggregate_corpus`` -- the exact micro-average code path
``scripts/wiki_eval.py cmd_report`` uses to build each run's own
``metrics.json``, so the *full*-set numbers this script computes are a
direct, exact-match sanity check against that file.

``P_label`` (P3\\exact) needs a live ``wbsearchentities(..., limit=1)`` call
per unmatched, non-``exact_label`` prediction surface (``label_exists``,
mirrored below from ``scripts/wiki_eval.py::_label_exists_fn``) -- a
different cache-key shape (``limit=1``) than the ``limit=7``
candidate-generation ladder this script replays, so the existing candidate
cache never covers it. By default (``compute_p_label=False``) ``run()``
reports only ``p_label_p3ex.estimated_unique_live_calls_required_clean`` (an
exact count, reusing the real ``metrics._precision_counts_p3_ex`` accounting
with a counting stub in place of a network-calling ``label_exists``) so a
caller can decide whether that many live calls are acceptable, without this
script silently making them. Pass ``compute_p_label=True`` (``--compute-p-label``
on the CLI) with a ``label_cache_path`` to actually make them: every unique
surface is looked up once via a bounded ``ThreadPoolExecutor``
(``label_network_concurrency``, default 3 -- Wikidata politeness, honoring
``WikidataClient``'s existing 429/``Retry-After`` backoff), cached to
``label_cache_path`` (a NEW on-disk cache, deliberately separate from the
``limit=7`` candidate-generation cache since the key shape differs and both
should stay independently replayable), then ``metrics.aggregate_corpus`` is
re-run against the now-fully-warm ``label_exists`` closure -- a single-threaded
pass at that point, since every lookup it makes is a cache hit.

Postmortem (2026-07-09, first live run): the deepseek prewarm died mid-batch
(55/~1991) on an uncaught ``RuntimeError`` -- Wikidata's own ``maxlag`` guard
tripped on a genuinely lagged replica (``wdqs1012``, 317s query-service lag),
``WikidataClient._fetch``'s internal 5-attempt/~12s retry wasn't long enough
to clear it, and the resulting exception, raised inside one
``ThreadPoolExecutor`` worker, propagated out of ``pool.map`` and killed the
whole process (gemini's prewarm had already finished and was unaffected).
``_resilient_label_exists`` now wraps every prewarm call with its own outer
retry (longer backoff than ``_fetch``'s internal one) and, only after
exhausting those, falls back to ``False`` (the conservative choice -- never
silently counts an unverifiable surface as label-justified) with the failure
recorded in ``p_label_p3ex.label_exists_failures`` rather than crashing the
batch. The give-up is sticky per surface so a persistently broken lookup
isn't retried twice (once during prewarm, once again during the final
single-threaded ``aggregate_corpus`` pass).

Usage (from the worktree root, with PYTHONPATH=src):
  uv run python scripts/sitelink_contamination.py \\
      --pred reports/terminology/wiki-eval/<model-slug>/<config>/<run_id> \\
      --gt data/eval/wiki/gt.jsonl \\
      --out docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay/<model>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.base import GroundingConfig, TermMention
from palimpsest.terminology.evaluation import metrics as M
from palimpsest.terminology.grounding.candidates import generate_candidates
from palimpsest.terminology.grounding.match import norm
from palimpsest.terminology.wikidata import WikidataClient

Tuple4 = tuple[int, str, str, int]

# candidates.py's tag for the last-resort RU-title -> Wikidata-item rung
# (generate_candidates: `hits, source = [{"id": qid}], "wikipedia_langlink"`).
SITELINK_SOURCE = "wikipedia_langlink"
# "none": the live replay found zero hits at all three rungs for a mention
# pred.jsonl says WAS grounded -- an inconsistency (Wikidata content drift
# since the run, or a title-normalization edge case), never silently folded
# into another bucket. Mirrors the "inconsistent"/"unknown" LOUD-accounting
# convention already used elsewhere in this project (e.g. scripts/wiki_eval.py
# FailureTracker).
NONE_SOURCE = "none"

DEFAULT_NETWORK_CONCURRENCY = 4  # polite default for a one-off live crawl (Wikidata etiquette)


def _config_from_bits(bits: str) -> GroundingConfig:
    """Mirrors scripts/wiki_eval.py::_config_from_bits (the config both target
    runs used, confirmed via meta.json's "config" field), plus enrich_top=0 --
    see module docstring for why enrichment is skipped."""
    use_lemma, use_fallbacks, _match_aliases = (c == "1" for c in bits)
    return GroundingConfig(use_lemma=use_lemma, use_fallbacks=use_fallbacks, enrich_top=0)


def _load_gt(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _load_pred_by_title(pred_path: Path) -> dict[str, list[dict]]:
    by_title: dict[str, list[dict]] = defaultdict(list)
    for line in pred_path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        by_title[r["title"]].append(r)
    return by_title


def _grounded(records: list[dict]) -> list[dict]:
    """qid != null only -- same filter scripts/wiki_eval.py::cmd_report applies
    before building pred_tuples."""
    return [r for r in records if r.get("qid") is not None]


def _model_slug(pred_dir: Path, meta: dict) -> str:
    model, provider = meta.get("model"), meta.get("provider")
    if model and provider:
        return f"{model.replace('/', '--')}--{provider}"
    # Fallback: run-dir layout is always <model-slug>/<config>/<run_id>/.
    return pred_dir.resolve().parents[1].name


def _replay_sources(
    grounded_records: list[dict], *, wd: WikidataClient, config: GroundingConfig,
    lang: str, workers: int,
) -> dict[tuple[str, str], str]:
    """(lemma, surface) -> ladder source, replayed live via the real
    ``generate_candidates``. Deduplicated by form pair -- the ladder decision
    is deterministic given (lemma, surface, lang, config), and this corpus
    repeats the same entities many times, so this cuts ~2-3x redundant work.
    """
    pairs = sorted({(r.get("lemma") or "", r["surface"]) for r in grounded_records})

    def _one(pair: tuple[str, str]) -> tuple[tuple[str, str], str]:
        lemma, surface = pair
        mention = TermMention(surface=surface, lemma=lemma or None, lang=lang)
        return pair, generate_candidates(wd, mention, config)["source"]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(_one, pairs))


# -- article-local slice maps, mirroring scripts/wiki_eval.py::cmd_report's
# same-named helpers exactly (GT/pred token indices reset per article -- spec
# E-D6 -- so every map below is keyed by an INDEX that is only meaningful
# within its own article; duplicated here rather than imported to avoid a
# script-to-script import for three one-liners).
def _resolved_by_of_for_article(pred_records: list[dict]) -> dict[int, str]:
    return {r["index"]: r["resolved_by"] for r in pred_records if r.get("resolved_by")}


def _stratum_of_for_article(gt_tuples: list[Tuple4], stratum: str) -> dict[int, str]:
    return {t[0]: stratum for t in gt_tuples}


def _type_of_for_article(gt_tuples: list[Tuple4]) -> dict[int, str]:
    """named vs term, classified by GT anchor surface capitalization (spec Sec.4 caveat)."""
    return {t[0]: ("named" if t[1][:1].isupper() else "term") for t in gt_tuples}


def _label_exists_fn(wd: WikidataClient):
    """P3 predicate (spec Sec.4): does ``surface`` exist as a Wikidata RU label
    anywhere reachable via wbsearchentities exact-prefix search? Mirrors
    ``scripts/wiki_eval.py::_label_exists_fn`` exactly (same in-memory
    cache-by-``norm(surface)`` closure on top of ``wd``'s own on-disk cache,
    keyed by the literal ``wbsearchentities(..., limit=1)`` URL) -- duplicated
    rather than imported to avoid pulling in the whole ``wiki_eval`` CLI
    module for one function.
    """
    cache: dict[str, bool] = {}
    lock = threading.Lock()

    def label_exists(surface: str) -> bool:
        key = norm(surface)
        with lock:
            if key in cache:
                return cache[key]
        hits = wd.search_entities(surface, lang="ru", limit=1)
        exists = any(norm(h.get("label", "")) == key for h in hits)
        with lock:
            cache[key] = exists
        return exists

    return label_exists


def _resilient_label_exists(
    label_exists_fn, *, max_attempts: int = 4, backoff: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0),
):
    """Wrap a ``label_exists`` closure so ONE surface's transient failure
    (maxlag exhaustion, network hiccup) can never kill a whole
    ``ThreadPoolExecutor`` batch -- ``pool.map`` re-raises the first worker
    exception it sees when iterated, which aborts every other still-in-flight
    lookup too (see module docstring's 2026-07-09 postmortem). Retries with a
    longer OUTER backoff than ``WikidataClient._fetch``'s own internal maxlag
    retry (5 attempts, <=~12s total) -- a genuinely lagged replica needs
    longer than that to clear. Give-up is sticky per ``norm(surface)`` (never
    retries a proven-broken lookup twice) and falls back to ``False`` -- the
    conservative choice, matching the project's "log the deviation, keep
    going" convention -- rather than raising. Returns ``(wrapped, failures)``;
    ``failures`` is a live list of ``(surface, error)`` pairs, appended to as
    the wrapped function runs, for the caller to report afterward.
    """
    gave_up: dict[str, bool] = {}
    lock = threading.Lock()
    failures: list[tuple[str, str]] = []

    def wrapped(surface: str) -> bool:
        key = norm(surface)
        with lock:
            if key in gave_up:
                return gave_up[key]
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return label_exists_fn(surface)
            except (RuntimeError, urllib.error.URLError) as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
        with lock:
            gave_up[key] = False
        failures.append((surface, repr(last_exc)))
        return False

    return wrapped, failures


def _needed_label_surfaces(articles: list[M.ArticleTuples]) -> dict[str, str]:
    """``norm(surface) -> one representative literal surface``, in the exact
    dedup shape a real ``aggregate_corpus(..., label_exists=...)`` pass over
    these articles will query (reuses the real
    ``metrics._precision_counts_p3_ex`` accounting, mode="m2", with a
    collecting stub in place of a network-calling predicate -- so this is an
    exact set, not an estimate, and costs zero live calls to compute).
    """
    needed: dict[str, str] = {}

    def _collect(surface: str) -> bool:
        needed.setdefault(norm(surface), surface)
        return False  # value is irrelevant -- only call sites are collected

    for article in articles:
        M._precision_counts_p3_ex(
            article["gt_tuples"], article["pred_tuples"], mode="m2",
            resolved_by_of=article["resolved_by_of"], label_exists=_collect,
        )
    return needed


def run(
    pred_dir: Path, gt_path: Path, meta: dict, *, network_concurrency: int, cache_path: Path,
    allow_network: bool = False,
    compute_p_label: bool = False,
    label_cache_path: Path | None = None,
    label_network_concurrency: int = 3,
) -> dict:
    config_bits = meta.get("config") or pred_dir.parent.name
    config = _config_from_bits(config_bits)

    gt_records = _load_gt(gt_path)
    pred_by_title = _load_pred_by_title(pred_dir / "pred.jsonl")

    all_grounded = [r for records in pred_by_title.values() for r in _grounded(records)]
    wd = WikidataClient(cache_path=cache_path, network_concurrency=network_concurrency)
    source_of = _replay_sources(
        all_grounded, wd=wd, config=config, lang="ru", workers=network_concurrency,
    )

    if wd.n_network_calls and not allow_network:
        raise RuntimeError(
            f"sitelink_contamination.py: {wd.n_network_calls} live Wikidata call(s) were "
            f"made against {cache_path} -- the cache was not fully warm for this --pred dir, "
            "so this would silently mix cached and live data. Re-run with --allow-network "
            "if that is intentional (e.g. warming the cache for the first time)."
        )

    def source(r: dict) -> str:
        return source_of[(r.get("lemma") or "", r["surface"])]

    full_articles: list[M.ArticleTuples] = []
    clean_articles: list[M.ArticleTuples] = []
    source_counts: dict[str, int] = defaultdict(int)

    for rec in gt_records:
        gt_tuples = [tuple(t) for t in rec["gt_tuples"]]
        raw_records = pred_by_title.get(rec["title"], [])
        grounded = _grounded(raw_records)
        for r in grounded:
            source_counts[source(r)] += 1

        full_pred = [(r["index"], r["surface"], r["qid"], r["span_len"]) for r in grounded]
        clean_pred = [
            (r["index"], r["surface"], r["qid"], r["span_len"])
            for r in grounded if source(r) != SITELINK_SOURCE
        ]
        resolved_by_of = _resolved_by_of_for_article(raw_records)
        stratum_of = _stratum_of_for_article(gt_tuples, rec.get("stratum", "typical"))
        type_of = _type_of_for_article(gt_tuples)

        full_articles.append({
            "gt_tuples": gt_tuples, "pred_tuples": full_pred,
            "resolved_by_of": resolved_by_of, "stratum_of": stratum_of, "type_of": type_of,
        })
        clean_articles.append({
            "gt_tuples": gt_tuples, "pred_tuples": clean_pred,
            "resolved_by_of": resolved_by_of, "stratum_of": stratum_of, "type_of": type_of,
        })

    # R_strict (m1) / R_span (m2) / R_doc (m3) + P_mention (p1) / P_type (p2),
    # all with Wilson CI, via the SAME micro-average aggregation
    # scripts/wiki_eval.py cmd_report uses for metrics.json. `full_articles`
    # never gets a real label_exists (P_label on the original/non-clean set
    # already exists in each run's own committed metrics.json -- only the
    # clean-set P_label is new work here).
    metrics_full = M.aggregate_corpus(full_articles)

    needed_label_surfaces = _needed_label_surfaces(clean_articles)

    if compute_p_label:
        if label_cache_path is None:
            raise ValueError("compute_p_label=True requires a label_cache_path")
        wd_label = WikidataClient(
            cache_path=label_cache_path, network_concurrency=label_network_concurrency,
        )
        label_exists_raw = _label_exists_fn(wd_label)
        label_exists, label_failures = _resilient_label_exists(label_exists_raw)
        # Pre-warm: dispatch every unique surface concurrently (bounded by
        # label_network_concurrency, WikidataClient's own semaphore enforces
        # the same cap on the actual HTTP calls) so the real aggregate_corpus
        # pass below -- which calls label_exists single-threaded, in GT/pred
        # iteration order -- hits an already-warm cache on every lookup. The
        # resilient wrapper (see module docstring postmortem) means a single
        # stuck surface can no longer take the whole batch down with it.
        with ThreadPoolExecutor(max_workers=label_network_concurrency) as pool:
            list(pool.map(label_exists, needed_label_surfaces.values()))
        # NOT `M.aggregate_corpus(clean_articles, label_exists=label_exists)`:
        # passing label_exists there also activates aggregate_corpus's
        # per-resolved_by-slice P3 (`_precision_counts(..., variant="p3",
        # label_exists=...)` inside its axis-slicing loop, unconditionally
        # once label_exists is not None) -- a SEPARATE, unrequested
        # computation over EVERY resolved_by value (including the huge
        # exact_label slice, which the p3_ex headline explicitly excludes),
        # which silently drove the first live run's call count to ~1.7x the
        # diagnosed estimate (gemini: 4014 actual vs 2419 estimated -- see
        # module docstring postmortem). Recall/P1/P2 come from the
        # label-free aggregate_corpus call above; p3_ex is accumulated here
        # directly via the exact same private helper aggregate_corpus itself
        # uses for the headline cell, so the result is identical -- just
        # without the wasted slice-P3 network cost.
        metrics_clean = M.aggregate_corpus(clean_articles)
        p3_matched = p3_total = 0
        for article in clean_articles:
            m, t = M._precision_counts_p3_ex(
                article["gt_tuples"], article["pred_tuples"], mode="m2",
                resolved_by_of=article["resolved_by_of"], label_exists=label_exists,
            )
            p3_matched += m
            p3_total += t
        p_label_p3ex = {
            "status": "computed",
            **M._cell(p3_matched, p3_total),
            "unique_surfaces_queried": len(needed_label_surfaces),
            "live_calls_made": wd_label.n_network_calls,
            "cache_hits": wd_label.n_cache_hits,
            "cache_path": str(label_cache_path),
            "label_exists_failures": len(label_failures),
            "label_exists_failure_examples": label_failures[:20],
        }
    else:
        metrics_clean = M.aggregate_corpus(clean_articles)
        p_label_p3ex = {
            "status": "not_computed",
            "reason": (
                "P_label (P3\\exact) needs a live wbsearchentities(..., limit=1) call per "
                "unmatched, non-exact_label prediction surface (label_exists) -- a different "
                "cache-key shape than the limit=7 candidate-generation ladder this script "
                "replays, so no committed cache covers it. Not computed to avoid making "
                "live/uncached Wikidata calls. Pass compute_p_label=True (--compute-p-label) "
                "with a label_cache_path to compute it for real."
            ),
            "estimated_unique_live_calls_required_clean": len(needed_label_surfaces),
        }

    r_full, r_clean = metrics_full["recall"]["m3"], metrics_clean["recall"]["m3"]

    n_grounded = sum(source_counts.values())
    n_sitelink = source_counts.get(SITELINK_SOURCE, 0)
    n_inconsistent = source_counts.get(NONE_SOURCE, 0)

    return {
        "pred_dir": str(pred_dir),
        "model": meta.get("model"),
        "provider": meta.get("provider"),
        "config": config_bits,
        "n_articles": len(gt_records),
        "n_gt_tuples": sum(len(rec["gt_tuples"]) for rec in gt_records),
        "n_grounded": n_grounded,
        "source_counts": dict(source_counts),
        "sitelink_sourced": n_sitelink,
        "sitelink_share_of_grounded": (n_sitelink / n_grounded) if n_grounded else None,
        "replay_inconsistent_count": n_inconsistent,
        # kept for backward compat with drafts/sitelink_replay/{gemini,deepseek}.json
        # consumers -- same matched/total/value as before, now additionally
        # carrying ci_lo/ci_hi/underpowered (metrics._cell's shape).
        "R_doc_full": r_full,
        "R_doc_clean": r_clean,
        "R_doc_delta": (
            r_clean["value"] - r_full["value"]
            if r_full["value"] is not None and r_clean["value"] is not None else None
        ),
        "recall_units_lost": r_full["matched"] - r_clean["matched"],
        "unique_forms_replayed": len(source_of),
        # -- full-metrics extension (paper Table C, 2026-07-09) --
        "recall_full": metrics_full["recall"],      # {"m1": R_strict, "m2": R_span, "m3": R_doc}
        "recall_clean": metrics_clean["recall"],
        "precision_full": dict(metrics_full["precision"]),   # p1=P_mention, p2=P_type
        "precision_clean": dict(metrics_clean["precision"]),   # p1/p2 only -- p3_ex is p_label_p3ex
        "p_label_p3ex": p_label_p3ex,
        "wikidata_network_calls_made": wd.n_network_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pred", required=True, help="wiki-eval run dir (contains pred.jsonl + meta.json)")
    parser.add_argument("--gt", required=True, help="GT jsonl with gt_tuples per article (e.g. data/eval/wiki/gt.jsonl)")
    parser.add_argument("--out", default=None, help="optional path to write the JSON result")
    parser.add_argument("--network-concurrency", type=int, default=DEFAULT_NETWORK_CONCURRENCY,
                         help="bound on concurrent live Wikidata HTTP calls (politeness)")
    parser.add_argument("--cache", default=None,
                         help="live-Wikidata JSONL cache path (default: next to --out, else CWD)")
    parser.add_argument("--allow-network", action="store_true",
                         help="permit live Wikidata calls on a cache miss (default: off -- run() "
                              "raises instead of silently mixing cached and live data)")
    parser.add_argument("--compute-p-label", action="store_true",
                         help="actually compute clean P_label (P3\\exact) via live "
                              "wbsearchentities(..., limit=1) label_exists calls, cached to "
                              "--label-cache (default: off -- reports a live-call-count "
                              "diagnostic instead, see module docstring)")
    parser.add_argument("--label-cache", default=None,
                         help="label_exists JSONL cache path (default: next to --out, else CWD; "
                              "deliberately separate from --cache -- different key shape)")
    parser.add_argument("--label-network-concurrency", type=int, default=3,
                         help="bound on concurrent live label_exists HTTP calls (politeness)")
    args = parser.parse_args()

    pred_dir = Path(args.pred)
    gt_path = Path(args.gt)
    out_path = Path(args.out) if args.out else None

    meta_path = pred_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    cache_dir = out_path.parent if out_path else Path.cwd()
    cache_path = Path(args.cache) if args.cache else cache_dir / f".wikidata_cache.{_model_slug(pred_dir, meta)}.jsonl"
    label_cache_path = (
        Path(args.label_cache) if args.label_cache
        else cache_dir / f".wikidata_cache.label_exists.{_model_slug(pred_dir, meta)}.jsonl"
    )

    result = run(
        pred_dir, gt_path, meta,
        network_concurrency=args.network_concurrency, cache_path=cache_path,
        allow_network=args.allow_network,
        compute_p_label=args.compute_p_label,
        label_cache_path=label_cache_path,
        label_network_concurrency=args.label_network_concurrency,
    )

    text = json.dumps(result, ensure_ascii=False, indent=1)
    print(text)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
