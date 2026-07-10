#!/usr/bin/env python3
"""Wiki-eval CLI (W5, transport rework v2): build-gt / run / ablate / report
over 100 RU-Wikipedia history articles, evaluating G6 label_first
NER+grounding against human hyperlink annotations.

Spec: docs/superpowers/specs/2026-07-03-wiki-eval-design.md (build-gt/GT).
Route/params/observability/protocol-v3 rework:
docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md.

Usage (from the worktree root, with PYTHONPATH=src):
  python scripts/wiki_eval.py build-gt --titles <file> --out data/eval/wiki/gt.jsonl --cache data/eval/wiki/pages
  python scripts/wiki_eval.py run --gt data/eval/wiki/gt.jsonl --config 111 --dry-run
  python scripts/wiki_eval.py run --gt data/eval/wiki/gt.jsonl --config 111 --max-usd 40
  python scripts/wiki_eval.py run --gt data/eval/wiki/gt.jsonl --config 111 --model deepseek/deepseek-v4-flash --provider Novita --max-usd 12 --max-judge-calls 5000
  python scripts/wiki_eval.py ablate --gt data/eval/wiki/gt.jsonl --max-usd 40 --dry-run
  python scripts/wiki_eval.py report --gt data/eval/wiki/gt.jsonl --pred reports/terminology/wiki-eval/<model-slug>/111/<run_id>
"""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import os
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.base import FatalGroundingJudgeError, GroundingConfig
from palimpsest.terminology.evaluation import metrics as M
from palimpsest.terminology.evaluation import predict, report, wiki_gt
from palimpsest.terminology.evaluation.tokenize import flatten
from palimpsest.terminology.extract import (
    NER_SYSTEM_PROMPT,
    ExtractionParseError,
    llm_surfaces,
    mentions_from_surfaces,
    ner_user,
    parse_surfaces,
)
from palimpsest.terminology.grounding import LabelFirstGrounding
from palimpsest.terminology.grounding.label_first import DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT
from palimpsest.terminology.wikidata import DEFAULT_NETWORK_CONCURRENCY, WikidataClient

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_GT = ROOT / "data/eval/wiki/gt.jsonl"
DEFAULT_PAGES_CACHE = ROOT / "data/eval/wiki/pages"
WIKIDATA_CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"
OUT_ROOT = ROOT / "reports/terminology/wiki-eval"
TIER_PATH = ROOT / "data/eval/wiki/tier_assignment.json"

# Standard OpenRouter (spec 2026-07-10 Р2) -- the CloseRouter gateway/env-var
# machinery (WIKI_EVAL_PROVIDER, CLOSEROUTER_MODEL, CLOSEROUTER_PROVIDER) is
# retired along with it; every run goes through this one base URL.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-3.1-flash-lite"
DEFAULT_MAX_TOKENS = 20000  # both roles, spec Р3

# Vendor-recommended sampling + pinned provider + reasoning shape per cloud
# model (spec Р3/Р13/Р14; pins probed live 2026-07-10, see spec §4.6).
# Changing a pin requires a spec edit, not a code-side decision.
MODEL_PARAMS: dict[str, dict] = {
    "deepseek/deepseek-v4-flash": {
        "temperature": 1.0, "top_p": 1.0, "top_k": None,
        "provider_pin": "Novita", "reasoning": {"enabled": True},
    },
    "google/gemini-3.1-flash-lite": {
        "temperature": 1.0, "top_p": None, "top_k": None,
        "provider_pin": "Google AI Studio",
        # {"enabled": true} silently yields reasoning_tokens=0 on gemini --
        # only the effort form ignites reasoning (probed 2026-07-10, spec Р13)
        "reasoning": {"effort": "medium"},
    },
    "google/gemma-4-31b-it": {
        "temperature": 1.0, "top_p": 0.95, "top_k": 64,
        "provider_pin": "WandB", "reasoning": {"enabled": True},
    },
    # 2026-07-10 owner-authorized addition (spec Р1/Р14 amendment,
    # docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md):
    # gemma-3-27b-it/qwen3.6-27b are the local sr004 pair in the paper's
    # Table C plan (sr004-local-eval-runbook.md), routed through OpenRouter
    # here instead for a separate NER-extraction-only cost run, not a Table C
    # substitute. Pins probed live via GET /v1/models/{id}/endpoints
    # (cheapest provider with the best uptime), not from a HF-card vendor
    # recommendation like the three entries above.
    "google/gemma-3-27b-it": {
        # Same Gemma-family vendor sampling as gemma-4-31b-it above (no
        # separate HF-card probe done for this smaller sibling). Not a
        # reasoning/thinking model at all -- no "reasoning" key needed or sent.
        "temperature": 1.0, "top_p": 0.95, "top_k": 64,
        "provider_pin": "DeepInfra",  # $0.08/$0.16 per Mtok, uptime 99.8%+ (cheapest + most reliable of 5 probed)
    },
    "qwen/qwen3.6-27b": {
        "temperature": 1.0, "top_p": None, "top_k": None,
        "provider_pin": "Io Net",  # $0.285/$2.40 per Mtok, uptime 99.97% (cheapest + most reliable of 6 probed)
        # Hybrid-thinking model, reasons by default (docs/runbooks/
        # sr004-local-eval-runbook.md: "hybrid thinking model that reasons by
        # default unless a request sets it off"). The local vLLM runbook uses
        # chat_template_kwargs.enable_thinking=false, not available through
        # OpenRouter's normalized API; reasoning:{"enabled": false} is the
        # only lever this transport offers, and it IS honored here (probed
        # live 2026-07-10: reasoning_tokens=0 on a real extraction-shaped
        # call via Io Net, unlike gemini's enabled/effort split above).
        "reasoning": {"enabled": False},
    },
}


def _resolve_route(model: str | None = None, provider: str | None = None,
                    extra_body: dict | None = None, base_url: str | None = None,
                    temperature: float | None = None, top_p: float | None = None,
                    top_k: int | None = None, max_tokens: int | None = None) -> dict:
    """Resolve ONE route config used for BOTH the extractor and the judge
    (spec 2026-07-10 §4.1/Р2/Р3/Р13/Р14) -- unlike the retired CloseRouter
    three-branch design, extraction and judge always share the same model/
    provider/sampling on the standard OpenRouter endpoint.

    Resolution order per field: an explicit CLI-ish keyword argument (not
    ``None``) always wins; otherwise ``MODEL_PARAMS[model]`` supplies the
    vendor-recommended default when ``model`` is a known cloud model;
    otherwise the field is omitted (``None``) -- except ``max_tokens``,
    which falls back to ``DEFAULT_MAX_TOKENS`` (not a `MODEL_PARAMS` field,
    spec Р3: 20000 for every model) and ``base_url``, which falls back to
    ``DEFAULT_BASE_URL``. ``model=None`` resolves to ``DEFAULT_MODEL`` so
    callers/tests that don't pass one still get a fully-specified route.

    ``provider``: the literal ``"auto"`` disables pinning (and therefore the
    served-by gate) entirely, same semantics as the retired CloseRouter
    ``"auto"`` handling.

    ``extra_body`` is merged PER-KEY over the computed defaults (provider
    pin, reasoning shape, top_k, OpenRouter's ``usage.include``), never
    replaces them wholesale (finding 4 regression: an unrelated
    ``--extra-body`` key must not silently drop the provider pin). The pin
    used for the per-call served-by gate (returned as ``"provider_pin"``) is
    read back from the EFFECTIVE (post-merge) ``extra_body["provider"]
    ["order"][0]`` when present, so an explicit ``--extra-body`` provider
    override changes the gate consistently instead of gating against a pin
    that's no longer actually requested; no ``"provider"`` key in the
    effective body means no gate.
    """
    model = model or DEFAULT_MODEL
    params = MODEL_PARAMS.get(model, {})
    resolved_base_url = base_url or DEFAULT_BASE_URL

    resolved_temperature = temperature if temperature is not None else params.get("temperature")
    resolved_top_p = top_p if top_p is not None else params.get("top_p")
    resolved_top_k = top_k if top_k is not None else params.get("top_k")
    resolved_max_tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS

    if provider is not None:
        provider_pin = None if provider == "auto" else provider
    else:
        provider_pin = params.get("provider_pin")
    reasoning = params.get("reasoning")

    default_extra_body: dict = {}
    if provider_pin:
        default_extra_body["provider"] = {"order": [provider_pin], "allow_fallbacks": False}
    if reasoning:
        default_extra_body["reasoning"] = reasoning
    if resolved_top_k is not None:
        default_extra_body["top_k"] = resolved_top_k
    if "openrouter.ai" in resolved_base_url:
        default_extra_body["usage"] = {"include": True}  # OR only returns usage.cost when asked

    effective_extra_body = {**default_extra_body, **(extra_body or {})}

    gate_pin = None
    provider_field = effective_extra_body.get("provider")
    if provider_field:
        order = provider_field.get("order") or []
        gate_pin = order[0] if order else None

    # expect_reasoning (2026-07-10, qwen3.6-27b amendment): a "reasoning" key
    # being present does NOT by itself mean reasoning should ignite -- a
    # request can deliberately ask for it OFF (reasoning={"enabled": False},
    # qwen3.6-27b's MODEL_PARAMS entry, the only lever OpenRouter's
    # normalized API offers to suppress a hybrid-thinking model's default-on
    # reasoning). The Р13 gate ("reasoning didn't ignite") must only fire
    # when reasoning was actually asked for, not when it was asked to be
    # off and correctly stayed off -- reasoning_tokens=0 in that case is the
    # CORRECT, expected outcome, not a gate violation.
    reasoning_field = effective_extra_body.get("reasoning")
    expect_reasoning = bool(reasoning_field) and reasoning_field.get("enabled") is not False

    return {
        "model": model,
        "base_url": resolved_base_url,
        "api_key_env": "OPENROUTER_API_KEY",
        "temperature": resolved_temperature,
        "top_p": resolved_top_p,
        "max_tokens": resolved_max_tokens,
        "extra_body": effective_extra_body,
        "provider_pin": gate_pin,
        "expect_reasoning": expect_reasoning,
    }


# E-D11/Sec.11: pre-call reservation cap + hard call-count ceiling (judge calls
# only -- see BudgetGuard; extraction calls are bounded by --max-usd alone,
# there are ~1 per paragraph and that's already bounded by the corpus size).
MAX_JUDGE_CALLS = 900
DEFAULT_MAX_USD = 40.0

# Article-level parallelism (ticket 002b): `run`/`ablate` process this many
# articles concurrently by default: each article keeps its own judge_cache and
# runs its own two-phase (extract/ground) flow, but ALL of them share the same
# semaphore-bounded extract_fn/judge -- see `_process_articles_parallel`.
DEFAULT_ARTICLE_WORKERS = 3

# Process-wide cap on concurrent in-flight LLM calls (extract+judge combined),
# i.e. the size of the llm_semaphore built in `_run_one_config` (ticket 002b
# introduced the semaphore hardcoded to palimpsest.llm.client.DEFAULT_MAX_CONCURRENCY;
# ticket 004 makes it a CLI override via --llm-workers). Duplicated here rather
# than imported -- same reason DEFAULT_MAX_CONCURRENCY itself is lazy-imported
# elsewhere in this file: --dry-run/--help must stay importable without
# `openai` installed. Owner-approved 16 for the 2026-07-05 model-comparison
# matrix runs (docs/experiments/2026-07-05-model-comparison/APPROVED.md item 5).
DEFAULT_LLM_WORKERS = 4

# Last-resort retry budget for extraction/judge calls (owner directive, qwen-run
# resilience patch, 2026-07-05): the client.py default (3 attempts, 1/3/9s) is
# tuned for isolated blips, not the minutes-long hard-503 windows CloseRouter's
# circuit breaker produces once a flappy route (e.g. provider-8) trips it under
# a 429 storm. A `run`/`ablate` invocation makes ~35k calls total, so a single
# call exhausting only 3 short retries must not be allowed to kill the whole
# run -- 6 attempts with backoff stretching to 60s gives a flapping route real
# time to recover before this layer gives up and the last-resort tolerance
# below (FailureTracker) kicks in.
RESILIENT_ATTEMPTS = 6
RESILIENT_BACKOFF: tuple[float, ...] = (1.0, 3.0, 9.0, 20.0, 40.0, 60.0)

# Conservative per-call price estimate (gpt-4o-mini list price, USD/token),
# mirrors eval_grounding.py -- used only for the pre-call reservation and
# --dry-run forecast, settled against real usage.cost when the provider
# reports it (E-D12). Shared fallback for both extraction and judge calls;
# not a per-model price table (that's ticket 003's provider-triage concern).
PRICE_IN = 0.15 / 1_000_000
PRICE_OUT = 0.60 / 1_000_000
EST_PROMPT_TOKENS = 1000
# Decoupled from the judge's hard output cap (now DEFAULT_MAX_TOKENS=20000,
# spec Р3) -- this is a typical reasoning+answer completion length for the
# reservation estimate, not the cap itself (2026-07-10 rework).
EST_JUDGE_COMPLETION_TOKENS = 600
EST_COST_PER_JUDGE_CALL = EST_PROMPT_TOKENS * PRICE_IN + EST_JUDGE_COMPLETION_TOKENS * PRICE_OUT

# Extraction prompt = NER_SYSTEM_PROMPT (~500 tokens, fixed system) + one
# paragraph of RU source text as the user message; completion = a JSON list
# of extracted surfaces, typically well short of DEFAULT_MAX_TOKENS.
# Deliberately generous vs. a typical paragraph so the estimate doesn't
# under-shoot (same worst-case-bound philosophy as EST_COST_PER_JUDGE_CALL
# above).
EST_EXTRACT_PROMPT_TOKENS = 1200
EST_EXTRACT_COMPLETION_TOKENS = 400
EST_COST_PER_EXTRACT_CALL = EST_EXTRACT_PROMPT_TOKENS * PRICE_IN + EST_EXTRACT_COMPLETION_TOKENS * PRICE_OUT

ALL_CONFIG_BITS = ["".join(p) for p in itertools.product("01", repeat=3)]


def model_slug(model: str, provider: str) -> str:
    """`<model>/<provider>` -> a filesystem-safe run-dir segment (ticket 002):
    every ``/`` in the model id becomes ``--``, then ``--<provider>`` is
    appended. Dots are preserved (dotted model names stay dotted in filenames,
    working-style.md "Naming & PRs") -- e.g. ``openai/gpt-5.5`` + ``provider-3``
    -> ``openai--gpt-5.5--provider-3``. OpenRouter provider pins are display
    names that may contain spaces (e.g. ``"Google AI Studio"``, spec Р14) --
    those become ``-`` so the slug stays a single filesystem path segment:
    ``"Google AI Studio"`` -> ``"Google-AI-Studio"``.
    """
    return f"{model.replace('/', '--')}--{provider.replace(' ', '-')}"


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


def _config_from_bits(bits: str, *, use_sitelink: bool | None = None) -> GroundingConfig:
    """Build a GroundingConfig from the 3-bit ablation id.

    ``use_sitelink`` overrides the bit-derived value when given (not ``None``)
    -- the wiki-eval protocol (docs/stages/wiki-eval.md Subtleties, "G6
    sitelink rung creates evaluation circularity") requires eval-scoring runs
    to use ``use_cirrus=True, use_sitelink=False`` rather than the historical
    ``use_fallbacks`` bit-configs that couple both rungs to the same bit --
    the 3-bit id has no room for a 4th independent toggle, so this keyword
    lets ``run``'s ``--no-sitelink`` flag force the rung off without changing
    the bit-string format ablate/tests already depend on.
    """
    use_lemma, use_fallbacks, match_aliases = (c == "1" for c in bits)
    config = GroundingConfig(use_lemma=use_lemma, use_fallbacks=use_fallbacks, match_aliases=match_aliases)
    if use_sitelink is not None and use_sitelink != config.use_sitelink:
        config = dataclasses.replace(config, use_sitelink=use_sitelink)
    return config


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


class _CountingSemaphore:
    """``threading.Semaphore`` wrapper that records the peak number of
    simultaneous holders (ticket 002b acceptance: the semaphore bound must be
    *observable*, not just asserted in tests). ``max_in_use`` lands in
    meta.json as ``llm_max_in_flight_observed`` so every run self-evidences
    that in-flight LLM calls never exceeded the cap. Context-manager only --
    that's the only way ``_build_extract_fn``/``_build_judge`` use it."""

    def __init__(self, value: int) -> None:
        self._sem = threading.Semaphore(value)
        self._lock = threading.Lock()
        self._in_use = 0
        self.max_in_use = 0

    def __enter__(self) -> _CountingSemaphore:
        self._sem.acquire()
        with self._lock:
            self._in_use += 1
            self.max_in_use = max(self.max_in_use, self._in_use)
        return self

    def __exit__(self, *exc: object) -> None:
        with self._lock:
            self._in_use -= 1
        self._sem.release()


class FailureTracker:
    """Thread-safe LOUD accounting for last-resort-tolerated call failures
    (qwen-run resilience patch, 2026-07-05). Two things are tolerated rather
    than left to kill the whole run, and both must be counted, never silent:

    - an extraction call that's still TRANSIENT-failing after
      ``RESILIENT_ATTEMPTS`` retries -> that one paragraph is treated as
      zero mentions (see ``_parallel_extract_fn``'s ``safe_extract``);
    - a judge call that's still TRANSIENT-failing (or still returns
      unparseable JSON after one re-ask) -> the affected mention falls back
      to ``LabelFirstGrounding.ground()``'s pre-existing
      ``resolved_by=judge_unavailable`` path (see ``_build_judge``).

    Deterministic errors are NOT recorded here -- they propagate and kill the
    run (extraction) or fall into the same judge_unavailable path ground()
    already had before this patch (judge), unchanged either way. Shared
    across every concurrent article/paragraph worker thread (same
    lock-per-mutation pattern as ``BudgetGuard``).

    ``record_parse_failure`` (spec 2026-07-10 §4.2.5, finding 1): a THIRD,
    separate thing tracked here -- an LLM NER reply that ``parse_surfaces``
    could not parse at all (``ExtractionParseError``, distinct from an
    honest empty ``[]`` reply). Unlike the transient-exhausted tolerance
    above, this is a deterministic parsing failure: it is still tolerated as
    zero mentions for that one paragraph (pilot gate: <1% of paragraphs),
    but counted under its own counter so it's never confused with network
    flakiness in meta.json.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.n_failed_paragraphs = 0
        self.failed_paragraphs: list[dict] = []
        self.n_failed_judge_calls = 0
        self.n_extraction_parse_failures = 0
        self.parse_failed_paragraphs: list[dict] = []

    def record_failed_paragraph(self, title: str | None, paragraph_index: int) -> None:
        with self._lock:
            self.n_failed_paragraphs += 1
            self.failed_paragraphs.append({"title": title, "paragraph_index": paragraph_index})

    def record_failed_judge_call(self) -> None:
        with self._lock:
            self.n_failed_judge_calls += 1

    def record_parse_failure(self, title: str | None, paragraph_index: int) -> None:
        with self._lock:
            self.n_extraction_parse_failures += 1
            self.parse_failed_paragraphs.append({"title": title, "paragraph_index": paragraph_index})


# ── extractor + judge builders (E-D16 bridge) ────────────────────────────────


def _complete_with_slot(client, system: str, user: str,
                         semaphore: _CountingSemaphore | threading.Semaphore, *,
                         attempts: int, backoff: tuple[float, ...]):
    """Retry loop with the SAME contract as ``LLMClient.complete_retrying``
    (bounded retries on transient errors only via
    ``palimpsest.llm.client.is_transient_error``; a deterministic error
    raises immediately; ``asyncio.CancelledError`` is a ``BaseException`` and
    is never caught here, so it always propagates uncaught) -- except the
    ``llm_semaphore`` slot is held ONLY across each individual
    ``client.complete()`` attempt, never across the ``time.sleep`` backoff
    between attempts.

    This is the semaphore-starvation fix (diagnosed live via py-spy, 2026-07-06):
    the previous code held the slot for the ENTIRE ``complete_retrying(...)``
    call, backoff sleeps included, so under a sustained upstream 429 storm all
    N slots ended up held by threads that were merely sleeping -- throughput
    collapsed to ~zero with every slot occupied by a sleeper and ~20 threads
    queued on ``acquire``. Releasing the slot during backoff lets other
    threads make real network progress while this one waits to retry.

    Shared by both ``_build_extract_fn``'s ``extractor()`` and
    ``_build_judge``'s ``_call()`` so the loop is written exactly once.
    """
    from palimpsest.llm.client import is_transient_error

    for i in range(attempts):
        try:
            with semaphore:
                return client.complete(system, user)
        except Exception as exc:  # noqa: BLE001 -- re-raised unless transient
            if not is_transient_error(exc) or i == attempts - 1:
                raise
            time.sleep(backoff[min(i, len(backoff) - 1)])
    raise RuntimeError("unreachable")  # pragma: no cover


# ── per-call gates + observability (spec 2026-07-10 Р8/Р13/Р14/Р15) ─────────


class LengthOverflowError(FatalGroundingJudgeError):
    """A call's reply was truncated by the token cap: ``finish_reason ==
    "length"``, or empty content with ``reasoning_tokens > 0`` (the model
    spent its whole budget reasoning and never emitted an answer). Per spec
    Р15 this is NEVER tolerated or silently retried -- it halts the run with
    full diagnostics (model, role, usage) in the message so the operator can
    raise the cap and ``--resume``; the checkpoint stays intact."""


class CallGateError(FatalGroundingJudgeError):
    """A per-call vendor-params gate failed: reasoning didn't ignite despite
    being requested (spec Р13), or the served provider doesn't match the
    pin (spec Р14)."""


class BudgetExhaustedError(FatalGroundingJudgeError):
    """``BudgetGuard.can_reserve()`` returned False mid-call: the $ cap or
    the judge-call ceiling was hit. Halts the run loudly (finding 2/10) --
    the previous bare ``RuntimeError`` here was swallowed by
    ``LabelFirstGrounding.ground()``'s judge catch-all into
    ``resolved_by=judge_unavailable``, silently corrupting slices instead of
    stopping the run."""


class CallLogger:
    """Per-call JSONL append (spec Р8): one line per completed LLM call
    (extract/judge/judge_reask) to ``<out_dir>/calls.jsonl`` -- lock+append+
    flush, same pattern as ``Checkpointer``. Called AFTER a reply is
    received but BEFORE ``_gate_reply`` runs, so a call that then trips a
    gate is still recorded in the artifact (the offending call must be
    auditable, not silently dropped)."""

    def __init__(self, out_dir: Path) -> None:
        self.path = Path(out_dir) / "calls.jsonl"
        self._lock = threading.Lock()

    def log(self, reply, *, kind: str, model: str, latency_ms: float) -> None:
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "model": model,
            "provider": reply.provider,
            "finish_reason": reply.finish_reason,
            "prompt_tokens": reply.usage.prompt_tokens,
            "completion_tokens": reply.usage.completion_tokens,
            "reasoning_tokens": reply.usage.reasoning_tokens,
            "cost_usd": reply.usage.cost_usd,
            "latency_ms": round(latency_ms, 1),
            "content_len": len(reply.content),
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                fh.flush()


def _gate_reply(reply, *, kind: str, model: str, pin: str | None,
                 expect_reasoning: bool, context: str) -> None:
    """Per-call gate (spec Р15/Р13/Р14 §4.1.4), run after EVERY completed LLM
    call (extractor + judge + judge reask), after that call has already been
    logged to ``calls.jsonl`` by ``CallLogger``. Raises a
    ``FatalGroundingJudgeError`` subclass on violation -- these halt the run
    rather than collapsing to a tolerated degradation: on the judge side
    ``LabelFirstGrounding.ground()`` re-raises them past its catch-all; on
    the extraction side ``_parallel_extract_fn.safe_extract`` re-raises them
    (not tolerated as transient).

    Order matters: length-overflow is checked first (it can co-occur with
    ``reasoning_tokens == 0`` when reasoning itself got truncated, and the
    overflow is the more actionable diagnosis), then the reasoning-ignition
    gate, then the served-provider pin gate.
    """
    usage = reply.usage
    if reply.finish_reason == "length" or (not reply.content.strip() and usage.reasoning_tokens > 0):
        raise LengthOverflowError(
            f"{kind} call to {model!r} hit the output-length limit ({context}): "
            f"finish_reason={reply.finish_reason!r} prompt_tokens={usage.prompt_tokens} "
            f"completion_tokens={usage.completion_tokens} reasoning_tokens={usage.reasoning_tokens}"
        )
    if expect_reasoning and usage.reasoning_tokens == 0:
        raise CallGateError(
            f"{kind} call to {model!r} did not ignite reasoning ({context}): "
            f"reasoning_tokens=0 despite expect_reasoning=True"
        )
    if pin is not None and reply.provider is not None:
        if reply.provider.strip().casefold() != pin.strip().casefold():
            raise CallGateError(
                f"{kind} call to {model!r} was served by {reply.provider!r}, "
                f"pinned to {pin!r} ({context})"
            )


def _build_extract_fn(guard: BudgetGuard, llm_semaphore: _CountingSemaphore | threading.Semaphore, *,
                       model: str | None = None, provider: str | None = None,
                       extra_body: dict | None = None, base_url: str | None = None,
                       temperature: float | None = None, top_p: float | None = None,
                       top_k: int | None = None, max_tokens: int | None = None,
                       call_logger: "CallLogger | None" = None):
    """Real NER extraction entry point: LLMClient + NER_SYSTEM_PROMPT/ner_user
    -> llm_surfaces -> mentions_from_surfaces -> list[TermMention].

    Mirrors term_pipeline.py's `extract --real` path (same prompt, validated
    substrings only) but wrapped as the single-paragraph `extract_fn` predict.py
    expects. Lazy-imports LLMClient so --dry-run/--help stay importable without
    `openai` installed (LLMClient-only by design, no direct openai import
    outside palimpsest.llm.client). ``guard`` is required (not optional) since
    ticket 002: every extraction call now reserves/settles against it, same
    contract as the judge below -- this closure may be invoked concurrently
    from several ThreadPoolExecutor workers (phase 1 of prediction), which is
    exactly why BudgetGuard grew a lock.

    ``llm_semaphore`` (ticket 002b, article-level parallelism): the SAME
    semaphore instance is shared with ``_build_judge`` by the caller
    (``_run_one_config``), sized ``--llm-workers`` (default DEFAULT_LLM_WORKERS,
    ticket 004) -- it wraps only the actual network call, never the guard
    bookkeeping, and is the ONE thing that bounds total in-flight LLM requests
    (extract + judge, across every article worker) to that size;
    ThreadPoolExecutor worker counts (per-article extraction pool,
    article-level pool) may be larger, they just block on this semaphore
    before actually calling the provider.

    ``model``/``provider``/``extra_body``/``base_url``/``temperature``/
    ``top_p``/``top_k``/``max_tokens`` are forwarded straight into
    ``_resolve_route`` (spec 2026-07-10 §4.1) -- CLI overrides win, else the
    per-model vendor defaults in ``MODEL_PARAMS`` apply. ``timeout=120.0``
    (not the client default 30s): reasoning at a 20000-token output cap can
    run well past 30s.

    Retries at ``RESILIENT_ATTEMPTS``/``RESILIENT_BACKOFF`` (6 attempts, up
    to 60s backoff -- qwen-run resilience patch): if the call is still
    TRANSIENT-failing after that, it raises here unchanged and out through
    ``extract_fn``; the last-resort per-paragraph tolerance (zero mentions +
    loud ``FailureTracker`` accounting) lives one level up, in
    ``_parallel_extract_fn``, which is where the paragraph index and article
    title needed for the accounting are actually available. A deterministic
    error (bad request, bad config) is never tolerated anywhere -- it
    propagates all the way out and kills the run. Retries (and their backoff
    sleeps) are driven by the shared ``_complete_with_slot`` helper, which
    holds ``llm_semaphore`` only during each network attempt -- never during
    the sleep between attempts (semaphore-starvation fix, 2026-07-06; see its
    docstring).

    ``call_logger`` (spec Р8, optional): when given, every completed reply
    is appended to ``calls.jsonl`` BEFORE ``_gate_reply`` runs -- a call that
    then trips a gate (``LengthOverflowError``/``CallGateError``, both
    ``FatalGroundingJudgeError`` subclasses) still propagates and halts the
    run (spec Р15), it is not tolerated here or by ``safe_extract``.
    """
    from palimpsest.llm.client import LLMClient, LLMConfig

    _load_dotenv()
    route = _resolve_route(model, provider, extra_body, base_url, temperature, top_p, top_k, max_tokens)
    api_key = os.environ.get(route["api_key_env"])
    if not api_key:
        raise RuntimeError(f"{route['api_key_env']} not set (checked .env and environment) -- required for extraction")

    client = LLMClient(LLMConfig(
        model=route["model"], base_url=route["base_url"], api_key=api_key,
        temperature=route["temperature"], top_p=route["top_p"], max_tokens=route["max_tokens"],
        extra_body=route["extra_body"], timeout=120.0,
    ))

    def extractor(source: str) -> list[dict]:
        if not guard.can_reserve(EST_COST_PER_EXTRACT_CALL, kind="extract"):
            raise BudgetExhaustedError(guard.stopped_reason)
        guard.reserve(EST_COST_PER_EXTRACT_CALL, kind="extract")
        t0 = time.perf_counter()
        reply = _complete_with_slot(
            client, system=NER_SYSTEM_PROMPT, user=ner_user(source),
            semaphore=llm_semaphore, attempts=RESILIENT_ATTEMPTS, backoff=RESILIENT_BACKOFF,
        )
        if call_logger is not None:
            call_logger.log(reply, kind="extract", model=route["model"],
                             latency_ms=(time.perf_counter() - t0) * 1000)
        _gate_reply(reply, kind="extract", model=route["model"], pin=route["provider_pin"],
                    expect_reasoning=route["expect_reasoning"], context="extraction call")
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


def _parallel_extract_fn(extract_fn, paragraphs: list[str], *, title: str | None = None,
                          tracker: FailureTracker | None = None):
    """Phase 1 of predicting one article (ticket 002): run ``extract_fn`` over
    every paragraph CONCURRENTLY via a ThreadPoolExecutor sized
    ``palimpsest.llm.client.DEFAULT_MAX_CONCURRENCY`` (4). Phase 2 (grounding +
    judge, inside ``predict.predict_tuples``) stays fully sequential --
    unchanged.

    Ticket 002b (article-level parallelism): this pool size is no longer the
    sole concurrency bound once several articles run at once -- N articles
    each spin up their own such pool, so up to N*4 threads may attempt an
    extraction call simultaneously. The real cap is the ``llm_semaphore``
    every ``extract_fn`` call blocks on inside ``_build_extract_fn``'s
    ``extractor()`` closure (shared process-wide with the judge), so actual
    network concurrency never exceeds that semaphore's size regardless of how
    many threads are waiting. This pool's max_workers is left at 4 rather than
    raised, since raising it wouldn't buy anything on its own (every thread
    still serializes on the one shared semaphore) and it keeps this function's
    contract unchanged from ticket 002 for its existing paragraph-order tests
    -- ticket 004's ``--llm-workers`` raises the semaphore itself (not this
    pool) when more paragraph/article threads need to fit through it at once.

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

    Last-resort tolerance (qwen-run resilience patch, 2026-07-05): if
    ``extract_fn(paragraph)`` still raises after ``_build_extract_fn``'s
    ``RESILIENT_ATTEMPTS`` retries because the underlying error is TRANSIENT
    (429/5xx/timeout -- ``palimpsest.llm.client.is_transient_error``), that
    ONE paragraph is tolerated as yielding zero mentions rather than killing
    the whole run: one lost paragraph out of ~300+/article is an acceptable
    gap, a dead 35k-call run is not. The failure is never silent -- it's
    recorded via ``tracker`` as ``(title, paragraph_index)`` and counted, for
    meta.json's ``n_failed_paragraphs``/``failed_paragraphs``. A
    deterministic error (bad request, bad model config) is NOT tolerated --
    it means the run is misconfigured and would fail identically on every
    remaining paragraph, so it propagates and kills the run exactly as
    before this patch. ``title``/``tracker`` default to ``None`` so existing
    callers (including this function's own pre-existing tests) keep working
    unchanged -- the tolerance logic simply runs without an owner-visible
    counter in that case.

    Two more outcomes layered in by the 2026-07-10 rework, checked BEFORE
    the transient/deterministic split above:

    - A ``FatalGroundingJudgeError`` (``LengthOverflowError``/
      ``CallGateError``/``BudgetExhaustedError``, spec Р15) is a halt
      marker, never tolerated -- it is enriched with this paragraph's
      article/index context via ``exc.add_note`` (so the offending call is
      identifiable without re-deriving it from ``calls.jsonl``) and
      re-raised to kill the run.
    - An ``ExtractionParseError`` (spec §4.2.5, finding 1: ``parse_surfaces``
      now raises instead of silently returning ``[]`` on malformed LLM
      output) IS tolerated, same as a transient failure -- but recorded
      under its own counter (``tracker.record_parse_failure``), never
      conflated with network flakiness, and printed loudly to stderr since
      the pilot gate requires this to stay under 1% of paragraphs.
    """
    from palimpsest.llm.client import DEFAULT_MAX_CONCURRENCY, is_transient_error

    def safe_extract(item: tuple[int, str]) -> list:
        idx, paragraph = item
        try:
            return extract_fn(paragraph)
        except FatalGroundingJudgeError as exc:
            exc.add_note(f"article={title!r} paragraph={idx}")
            raise
        except ExtractionParseError:
            if tracker is not None:
                tracker.record_parse_failure(title, idx)
            print(f"wiki_eval: extraction parse failure -- article={title!r} paragraph={idx}",
                  file=sys.stderr)
            return []
        except Exception as exc:  # noqa: BLE001 -- re-raised unless transient
            if not is_transient_error(exc):
                raise
            if tracker is not None:
                tracker.record_failed_paragraph(title, idx)
            return []

    with ThreadPoolExecutor(max_workers=DEFAULT_MAX_CONCURRENCY) as pool:
        mentions_per_paragraph = list(pool.map(safe_extract, enumerate(paragraphs)))
    ordered = iter(mentions_per_paragraph)
    return lambda _paragraph: next(ordered)


# Role + strict-JSON output contract, single source of truth in
# grounding/label_first.py (spec 2026-07-10 Р7: the Role and output contract
# belong in system, not user; this module used to carry its own one-line
# stub here instead of importing the real thing).
JUDGE_SYSTEM_PROMPT = DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT
# One re-ask on unparseable JSON (qwen-run resilience patch) uses this instead
# of JUDGE_SYSTEM_PROMPT -- a corrective nudge, NOT a byte-identical retry.
# The original rationale here assumed temperature=0 (a byte-identical retry
# would reproduce the same malformed reply); under the 2026-07-10 vendor
# sampling rework (spec Р3) every model runs at temperature>=1.0 with
# reasoning on, so a plain retry could already vary -- but a MALFORMED reply
# specifically (wrong shape, markdown fence, commentary) tends to be a
# systematic prompt-following miss that sampling alone doesn't fix, which is
# why the reask still explicitly restates the output contract rather than
# just re-asking the same question again.
JUDGE_REASK_SYSTEM_PROMPT = (
    JUDGE_SYSTEM_PROMPT + " Your previous reply was not valid JSON -- return ONLY the JSON "
    "object, with no markdown code fence and no commentary before or after it."
)


def _build_judge(guard: BudgetGuard, llm_semaphore: _CountingSemaphore | threading.Semaphore, *,
                  model: str | None = None, provider: str | None = None,
                  extra_body: dict | None = None, base_url: str | None = None,
                  temperature: float | None = None, top_p: float | None = None,
                  top_k: int | None = None, max_tokens: int | None = None,
                  tracker: FailureTracker | None = None,
                  call_logger: "CallLogger | None" = None):
    """Judge on the same route as the extractor (spec 2026-07-10 §4.1: one
    ``_resolve_route`` call, shared model/provider/sampling for both roles).
    Returns None when the API key is unset so the caller can fall back to
    judge=None.

    ``llm_semaphore`` (ticket 002b): same shared instance as
    ``_build_extract_fn`` -- see its docstring. Judge calls happen inside
    grounding (phase 2), which with article-level parallelism now runs
    concurrently across article workers, so this closure needs the same
    global cap. ``timeout=120.0`` (not the client default 30s), same
    rationale as the extractor's.

    Last-resort tolerance (qwen-run resilience patch, 2026-07-05): retries at
    ``RESILIENT_ATTEMPTS``/``RESILIENT_BACKOFF`` (6 attempts, up to 60s
    backoff) instead of ``complete_retrying``'s 3-attempt default, to ride
    out multi-minute upstream circuit-breaker windows -- via the shared
    ``_complete_with_slot`` helper, which holds ``llm_semaphore`` only during
    each network attempt, never during the sleep between attempts
    (semaphore-starvation fix, 2026-07-06; see its docstring). If a call is
    still TRANSIENT-failing after that, or the reply is still not valid JSON
    after ONE corrective re-ask, this closure lets the exception propagate
    exactly as before this patch -- ``LabelFirstGrounding.ground()`` already
    treats ANY judge exception as terminal ``resolved_by=judge_unavailable``
    (grounding/label_first.py's module docstring: "judge raising ... collapse
    to yellow/judge_unavailable -- terminal, no retry"; see also
    ``test_label_first_judge_raises_resolves_judge_unavailable_called_once_not_retried``
    in tests/test_terminology.py) -- EXCEPT a ``FatalGroundingJudgeError``
    (``LengthOverflowError``/``CallGateError``/``BudgetExhaustedError``, spec
    Р15), which ``ground()`` re-raises past that same catch-all instead of
    collapsing it, so it kills the run as intended. So the tolerance itself
    needs no change at the grounding call boundary -- this wrapper's only
    job is to make the two "gave up" (transient-exhausted / re-ask also
    unparseable) cases LOUD before re-raising: ``tracker.record_failed_judge_call()``
    so meta.json's ``n_failed_judge_calls`` shows how many mentions fell back
    to judge_unavailable via this path, instead of that fact being invisible
    inside ground()'s pre-existing catch-all. A judge call that raises a
    DETERMINISTIC error (e.g. a real bad-request/config bug) is not counted
    here -- ground()'s catch-all still swallows it into judge_unavailable
    unchanged from before this patch; that's an existing, separate contract,
    not something this task changes. ``tracker`` defaults to ``None`` so
    existing callers/tests keep working unchanged (no counter observed).

    ``call_logger`` (spec Р8, optional): every completed reply (original ask
    AND the corrective reask, tagged ``kind="judge"``/``"judge_reask"``) is
    appended to ``calls.jsonl`` before ``_gate_reply`` runs -- same ordering
    contract as the extractor's.
    """
    from palimpsest.llm.client import LLMClient, LLMConfig, is_transient_error

    _load_dotenv()
    route = _resolve_route(model, provider, extra_body, base_url, temperature, top_p, top_k, max_tokens)
    api_key = os.environ.get(route["api_key_env"])
    if not api_key:
        return None

    client = LLMClient(LLMConfig(
        model=route["model"], base_url=route["base_url"], api_key=api_key,
        temperature=route["temperature"], top_p=route["top_p"], max_tokens=route["max_tokens"],
        extra_body=route["extra_body"], timeout=120.0,
    ))

    def _call(prompt: str, *, system: str, kind: str) -> str:
        """One real judge network call: reserve, call (resilient retries,
        semaphore slot released during backoff), log, gate, settle."""
        if not guard.can_reserve(EST_COST_PER_JUDGE_CALL, kind="judge"):
            raise BudgetExhaustedError(guard.stopped_reason)
        guard.reserve(EST_COST_PER_JUDGE_CALL, kind="judge")
        t0 = time.perf_counter()
        result = _complete_with_slot(
            client, system=system, user=prompt,
            semaphore=llm_semaphore, attempts=RESILIENT_ATTEMPTS, backoff=RESILIENT_BACKOFF,
        )
        if call_logger is not None:
            call_logger.log(result, kind=kind, model=route["model"],
                             latency_ms=(time.perf_counter() - t0) * 1000)
        _gate_reply(result, kind=kind, model=route["model"], pin=route["provider_pin"],
                    expect_reasoning=route["expect_reasoning"], context=f"{kind} call")
        actual_cost = result.usage.cost_usd
        if actual_cost is None and result.usage.prompt_tokens:
            actual_cost = (result.usage.prompt_tokens * PRICE_IN
                           + result.usage.completion_tokens * PRICE_OUT)
        guard.settle(EST_COST_PER_JUDGE_CALL, actual_cost, kind="judge")
        return result.content

    def _parse(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)

    def judge(prompt: str) -> dict:
        try:
            content = _call(prompt, system=JUDGE_SYSTEM_PROMPT, kind="judge")
        except Exception as exc:  # noqa: BLE001 -- re-raised either way, see docstring
            if tracker is not None and is_transient_error(exc):
                tracker.record_failed_judge_call()
            raise

        try:
            return _parse(content)
        except json.JSONDecodeError:
            pass  # one corrective re-ask below before giving up

        try:
            content = _call(prompt, system=JUDGE_REASK_SYSTEM_PROMPT, kind="judge_reask")
        except Exception as exc:  # noqa: BLE001 -- re-raised either way, see docstring
            if tracker is not None and is_transient_error(exc):
                tracker.record_failed_judge_call()
            raise

        try:
            return _parse(content)
        except json.JSONDecodeError:
            if tracker is not None:
                tracker.record_failed_judge_call()
            raise

    return judge


def _canonicalize_fn(wd: WikidataClient):
    """QID -> canonical QID via the same redirect path GT used (E-D18):
    wbgetentities on a redirect returns the target under `entity["id"]`.

    Thread safety (ticket 002b): this closure is built once per config in
    ``_run_one_config`` and shared across every concurrent article worker --
    ``cache`` is a plain dict, so get/set races (lost updates, or a
    dict-mutated-during-iteration crash) are possible without a lock. ``lock``
    guards only the dict read/write, never the network call (``wd.get_entities``
    is itself thread-safe, see wikidata.py) -- a rare double-compute on an
    identical concurrent miss is accepted, not a correctness bug.
    """
    cache: dict[str, str] = {}
    lock = threading.Lock()

    def canonicalize(qid: str) -> str:
        with lock:
            if qid in cache:
                return cache[qid]
        entities = wd.get_entities([qid], props="")
        entity = entities.get(qid) or {}
        canonical = entity.get("id", qid)
        with lock:
            cache[qid] = canonical
        return canonical

    return canonicalize


def _p31_of_fn(wd: WikidataClient):
    """QID -> set of target P31 (instance-of) QIDs, for the chronology filter.

    Thread safety (ticket 002b): same dict-lock pattern as ``_canonicalize_fn``
    -- see its docstring.
    """
    cache: dict[str, set[str]] = {}
    lock = threading.Lock()

    def p31_of(qid: str) -> set[str]:
        with lock:
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
        with lock:
            cache[qid] = values
        return values

    return p31_of


# ── gt.jsonl I/O ──────────────────────────────────────────────────────────────


def _load_gt(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _assert_pred_gt_coverage(gt_records: list[dict], pred_records: list[dict], gt_path: Path, pred_source: object) -> None:
    """Guard against a pred/GT corpus mismatch passing silently (2026-07-10
    gt.jsonl drift incident, docs/known_issues.md): gt.jsonl silently held a
    stale 20-article pilot while a 100-article run's pred.jsonl kept scoring
    against it, because the report loop only looks up GT titles in
    pred_by_title and never checks the reverse direction. Any pred title
    absent from GT means the two corpora don't match -- fail loudly instead
    of silently under-scoring."""
    gt_titles = {rec["title"] for rec in gt_records}
    extra = sorted({r["title"] for r in pred_records} - gt_titles)
    if extra:
        raise SystemExit(
            f"wiki_eval: {len(extra)} pred title(s) absent from GT; wrong --gt corpus?\n"
            f"  --gt {gt_path}\n"
            f"  pred source: {pred_source}\n"
            f"  example mismatched titles: {extra[:5]}"
        )


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


class Checkpointer:
    """Per-article on-disk checkpoint (container-restart resilience patch):
    the container hosting long ``run`` invocations has been restarted twice
    in 1.5h, killing multi-hour runs -- pred records were held only in memory
    and written to disk once at the very end, so every restart lost ALL paid
    LLM work for that run. This writes each completed article's pred records
    to ``<out_dir>/pred.partial.jsonl`` (one JSON line per record, same
    schema as the final ``pred.jsonl``) and a progress line to
    ``<out_dir>/progress.jsonl`` the moment that article finishes --
    ``record()`` is called from inside ``_process_articles_parallel``'s
    ``process_one``, i.e. from the completing worker thread itself, NOT from
    the main thread's ``pool.map`` loop (which only yields results in
    submission order, well after earlier-submitted-but-slower articles
    block it). ``_lock`` serializes both files' writes plus the ``n_done``
    counter since several article workers can finish back-to-back; each
    write is flushed immediately so a killed container never loses more
    than the article(s) still in flight at kill time.

    ``--resume`` (``cmd_run``) reads ``pred.partial.jsonl`` back to skip
    already-done titles and seeds a fresh ``BudgetGuard`` from
    ``progress.jsonl``'s last recorded ``spent`` (plus, since the 2026-07-10
    rework, ``spent_by_kind``/``calls_by_kind`` -- see ``cmd_run``, finding
    3). ``pred.partial.jsonl`` is deleted once ``cmd_run`` finishes cleanly
    and has written the merged final ``pred.jsonl``.
    """

    def __init__(self, out_dir: Path, *, n_total: int, n_done: int = 0,
                 guard: BudgetGuard | None = None) -> None:
        self.pred_path = out_dir / "pred.partial.jsonl"
        self.progress_path = out_dir / "progress.jsonl"
        self.n_total = n_total
        self.n_done = n_done
        self.guard = guard
        self._lock = threading.Lock()

    def record(self, title: str, records: list[dict]) -> None:
        with self._lock:
            with self.pred_path.open("a", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
            self.n_done += 1
            line = {"article": title, "done": self.n_done, "of": self.n_total,
                     "spent": self.guard.spent if self.guard is not None else 0.0}
            if self.guard is not None:
                # finding 3: --resume needs the split, not just the total, to
                # restore the judge-call ceiling and the spend-by-kind meta.
                line["spent_by_kind"] = dict(self.guard.spent_by_kind)
                line["calls_by_kind"] = dict(self.guard.calls_by_kind)
            with self.progress_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                fh.flush()


def _process_articles_parallel(
    articles: list[tuple[str, list[str], str]], *, article_workers: int,
    extract_fn, judge, canonicalize, wd: WikidataClient, config: GroundingConfig,
    guard: BudgetGuard | None, tracker: FailureTracker | None = None,
    checkpoint: Checkpointer | None = None,
) -> tuple[list[dict], int]:
    """Article-level parallelism (ticket 002b): process every ``(title,
    paragraphs, article_text)`` triple in ``articles`` CONCURRENTLY, up to
    ``article_workers`` at a time, each keeping its own ``judge_cache`` and
    running its own phase-1(parallel extract)/phase-2(sequential ground)
    flow -- unchanged from ticket 002 per article. The speedup comes from
    overlapping Wikidata I/O and judge latency across articles, not from more
    LLM concurrency: ``extract_fn``/``judge`` are the SAME shared closures for
    every article, both bound by the one process-wide ``llm_semaphore``
    built in ``_run_one_config`` (see ``_build_extract_fn``/``_build_judge``).

    ``wd`` (the WikidataClient) and ``canonicalize`` are likewise shared --
    both are thread-safe (see wikidata.py and ``_canonicalize_fn``). A fresh
    ``LabelFirstGrounding`` instance is built PER ARTICLE over the shared
    ``wd``: the strategy object itself is stateless besides ``wd``/``config``
    refs, but instantiating fresh per article removes any doubt about future
    per-call state leaking across concurrent articles (ticket 002b's "if in
    doubt, one grounder per worker" guidance) at negligible cost.

    Returns ``(pred_records, n_paragraphs_total)`` with ``pred_records`` in
    ``articles`` order regardless of completion order -- ``ThreadPoolExecutor.
    map`` submits every task immediately but yields results positionally, the
    same order-preserving guarantee ``_parallel_extract_fn`` already relies on
    for paragraphs, applied here one level up for articles.

    ``checkpoint`` (container-restart resilience patch, optional): when given,
    ``checkpoint.record(title, records)`` is called from inside
    ``process_one`` -- the completing worker thread -- the instant that one
    article's records are ready, so on-disk progress reflects REAL completion
    order, not ``pool.map``'s submission-order yield. ``None`` (default)
    keeps every pre-existing caller/test of this function unchanged.
    """

    def process_one(item: tuple[str, list[str], str]) -> tuple[list[dict], int]:
        title, paragraphs, article_text = item
        # Budget already exhausted by another (already-running) article worker:
        # skip starting a NEW article's calls entirely -- mirrors ticket 002's
        # sequential early-break, just checked at article-start instead of
        # article-end since concurrent workers can't "break a shared for-loop".
        if guard is not None and guard.stopped_reason is not None:
            return [], 0

        grounder = LabelFirstGrounding(wd, config)

        def ground_fn(mention, *, judge=judge, scope_id=None, judge_cache=None):
            return grounder.ground(mention, judge=judge, scope_id=scope_id, judge_cache=judge_cache)

        judge_cache: dict = {}
        # Phase 1 (parallel, capped at DEFAULT_MAX_CONCURRENCY per article):
        # extract every paragraph's mentions concurrently. Phase 2 (grounding +
        # judge, inside predict_tuples) is untouched and stays sequential
        # WITHIN one article -- it's the across-article overlap that's new.
        # title/tracker (qwen-run resilience patch): _parallel_extract_fn needs
        # both to record which article/paragraph a tolerated transient failure
        # came from -- see its docstring.
        paragraph_extract_fn = _parallel_extract_fn(extract_fn, paragraphs, title=title, tracker=tracker)
        result = predict.predict_tuples(
            article_text, paragraphs, paragraph_extract_fn, ground_fn,
            judge=judge, judge_cache=judge_cache, scope_id=title, canonicalize=canonicalize,
        )
        records = [{"title": title, **r} for r in result["records"]]
        if checkpoint is not None:
            checkpoint.record(title, records)
        return records, len(paragraphs)

    pred_records: list[dict] = []
    n_paragraphs_total = 0
    with ThreadPoolExecutor(max_workers=article_workers) as pool:
        for records, n_paragraphs in pool.map(process_one, articles):
            pred_records.extend(records)
            n_paragraphs_total += n_paragraphs
    return pred_records, n_paragraphs_total


def _run_one_config(bits: str, gt_records: list[dict], cache_dir: str, *, dry_run: bool, guard: BudgetGuard | None,
                     model: str | None = None, provider: str | None = None, extra_body: dict | None = None,
                     base_url: str | None = None, temperature: float | None = None,
                     top_p: float | None = None, top_k: int | None = None,
                     max_tokens: int | None = None,
                     article_workers: int = DEFAULT_ARTICLE_WORKERS,
                     llm_workers: int = DEFAULT_LLM_WORKERS,
                     wikidata_cache: str | Path = WIKIDATA_CACHE,
                     wikidata_workers: int = DEFAULT_NETWORK_CONCURRENCY,
                     out_dir: str | Path | None = None,
                     skip_titles: frozenset[str] = frozenset(),
                     n_done_start: int = 0,
                     use_sitelink: bool | None = None,
                     no_judge: bool = False) -> tuple[list[dict], dict]:
    config = _config_from_bits(bits, use_sitelink=use_sitelink)
    wd = WikidataClient(cache_path=wikidata_cache, network_concurrency=wikidata_workers)
    canonicalize = _canonicalize_fn(wd)

    if dry_run:
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
            n_mentions_est += sum(len(p.split()) for p in paragraphs) // 20  # rough forecast only
        counters = {
            "n_articles": len(gt_records),
            "n_paragraphs": n_paragraphs_total,
            "n_pred_mentions": n_mentions_est,
        }
        return [], counters

    # Non-dry-run: build the shared extractor/judge (and the ONE process-wide
    # llm_semaphore bounding both) once, then fan out across `article_workers`
    # concurrent article workers (ticket 002b). ``llm_workers`` sizes the
    # semaphore (ticket 004; default DEFAULT_LLM_WORKERS mirrors
    # palimpsest.llm.client.DEFAULT_MAX_CONCURRENCY, raised via --llm-workers
    # for matrix runs).
    llm_semaphore = _CountingSemaphore(llm_workers)
    # FailureTracker (qwen-run resilience patch): ONE shared instance per run,
    # threaded into the judge (transient-exhausted/unparseable-JSON tolerance)
    # and into _process_articles_parallel (per-paragraph extraction tolerance)
    # so both loud-accounting counters land in this run's meta.json.
    tracker = FailureTracker()
    # CallLogger (spec Р8): built only when the caller hands us a run dir --
    # same "no out_dir -> no artifact I/O" contract as Checkpointer, so
    # tests/ablate-without-persistence paths stay unaffected.
    call_logger = CallLogger(Path(out_dir)) if out_dir is not None else None
    # --no-judge (NER-extraction-only mode): judge=None makes
    # LabelFirstGrounding.ground() take its own pre-existing "judge not
    # configured" branch -- resolved_by=judge_unavailable, no LLM call, no
    # cost -- while exact-label matches (no ambiguity) and the free Wikidata
    # candidate search still run exactly as before. See grounding/label_first.py
    # `if judge is None:` branch; this flag only decides which callable
    # (real judge vs None) is threaded in, no grounding logic changes.
    judge = None if no_judge else _build_judge(
        guard, llm_semaphore, model=model, provider=provider, extra_body=extra_body,
        base_url=base_url, temperature=temperature, top_p=top_p, top_k=top_k,
        max_tokens=max_tokens, tracker=tracker, call_logger=call_logger)
    extract_fn = _build_extract_fn(guard, llm_semaphore, model=model, provider=provider, extra_body=extra_body,
                                    base_url=base_url, temperature=temperature, top_p=top_p, top_k=top_k,
                                    max_tokens=max_tokens, call_logger=call_logger)

    # Checkpointer (container-restart resilience patch): built only when the
    # caller (cmd_run) hands us a run dir -- ``n_done_start``/``skip_titles``
    # come from --resume (0/empty on a fresh run). ``n_total`` is the FULL
    # gt_records count (not just the remaining/filtered articles) so
    # progress.jsonl's "of" field reads as real end-to-end progress across a
    # resume boundary, e.g. done=41/100 rather than resetting to 1/60.
    checkpoint = None
    if out_dir is not None:
        checkpoint = Checkpointer(
            Path(out_dir), n_total=len(gt_records), n_done=n_done_start, guard=guard,
        )

    articles: list[tuple[str, list[str], str]] = []
    for rec in gt_records:
        title = rec["title"]
        if title in skip_titles:  # --resume: already checkpointed in a prior invocation
            continue
        html_path = Path(cache_dir) / f"{wiki_gt._safe_filename(title)}.html"
        if not html_path.exists():
            continue
        html = html_path.read_text(encoding="utf-8")
        article_text = flatten(html)
        paragraphs = article_text.split("\n")
        articles.append((title, paragraphs, article_text))

    pred_records, n_paragraphs_total = _process_articles_parallel(
        articles, article_workers=article_workers, extract_fn=extract_fn, judge=judge,
        canonicalize=canonicalize, wd=wd, config=config, guard=guard, tracker=tracker,
        checkpoint=checkpoint,
    )

    counters = {
        "n_articles": len(gt_records),
        "n_paragraphs": n_paragraphs_total,
        "n_pred_mentions": len(pred_records),
        # Self-evidencing (wiki-eval sitelink-circularity protocol, Subtleties):
        # every run's meta.json records the actually-applied grounding toggles,
        # not just the requested --config bits + --no-sitelink flag.
        "grounding_config": {
            "use_lemma": config.use_lemma,
            "use_cirrus": config.use_cirrus,
            "use_sitelink": config.use_sitelink,
            "match_aliases": config.match_aliases,
        },
        # Observed peak of simultaneous in-flight LLM calls (extract + judge
        # combined) -- must never exceed llm_workers (the llm_semaphore size,
        # ticket 004); recorded so every run's meta.json carries the evidence,
        # not just the configured cap (ticket 002b).
        "llm_max_in_flight_observed": llm_semaphore.max_in_use,
        # Last-resort tolerance accounting (qwen-run resilience patch): loud,
        # never silent -- see FailureTracker's docstring.
        "n_failed_paragraphs": tracker.n_failed_paragraphs,
        "failed_paragraphs": tracker.failed_paragraphs,
        "n_failed_judge_calls": tracker.n_failed_judge_calls,
        # Parse-fail accounting (spec §4.2.5, finding 1): a malformed LLM NER
        # reply, distinct from an honest empty [] and from network flakiness.
        "n_extraction_parse_failures": tracker.n_extraction_parse_failures,
        "parse_failed_paragraphs": tracker.parse_failed_paragraphs,
        # Wikidata usage evidence (run-metadata counters): merged into
        # cmd_run's meta.json via `**counters`, alongside "calls" for the LLM
        # side (extract/judge, already tracked by BudgetGuard). `getattr`
        # defaults keep this safe against the plain `object()`/minimal fakes
        # several existing tests inject as `wd` when they don't care about
        # Wikidata behavior at all (e.g. checkpoint/semaphore-sizing tests).
        "wikidata": {
            "calls": getattr(wd, "n_network_calls", 0),
            "cache_hits": getattr(wd, "n_cache_hits", 0),
            "seconds": round(getattr(wd, "total_network_seconds", 0.0), 3),
        },
        # NER-extraction-only mode marker (--no-judge): disclosed in meta.json
        # so a run dir is self-evidencing about whether judge calls were even
        # attempted, not just their count (which would read 0 either way if
        # every mention happened to resolve by exact_label).
        "no_judge": no_judge,
    }
    return pred_records, counters


def _parse_extra_body(raw: str | None) -> dict | None:
    """``--extra-body`` CLI value (a JSON object string) -> dict, or ``None``
    when the flag wasn't passed (sr004 local-judge patch, 2026-07-09).
    Deliberately not caught here -- a malformed JSON string should fail loud
    at argument-parse time, not silently fall back to no override."""
    return json.loads(raw) if raw else None


def cmd_run(args) -> int:
    gt_records = _load_gt(Path(args.gt))
    guard = BudgetGuard(args.max_usd, max_judge_calls=args.max_judge_calls)
    use_sitelink = False if getattr(args, "no_sitelink", False) else None
    extra_body = _parse_extra_body(getattr(args, "extra_body", None))

    if args.dry_run:
        _, counters = _run_one_config(args.config, gt_records, args.cache, dry_run=True, guard=None,
                                       wikidata_cache=args.wikidata_cache, use_sitelink=use_sitelink)
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

    route = _resolve_route(args.model, args.provider, extra_body, args.base_url,
                            args.temperature, args.top_p, args.top_k, args.max_tokens)
    model = route["model"]
    provider = route["provider_pin"] or "auto"
    slug = model_slug(model, provider)

    # --resume (container-restart resilience patch): reuse a prior run's dir
    # and run_id, skip articles it already finished (by title, read back from
    # its pred.partial.jsonl), and seed THIS invocation's guard from
    # progress.jsonl's last recorded spend/spend-split -- so a killed
    # container loses at most the article(s) in flight when it died, never
    # the whole run.
    resume_dir = getattr(args, "resume", None)
    old_pred_records: list[dict] = []
    skip_titles: set[str] = set()
    resumed_from_n_articles: int | None = None
    run_id: str | None = None
    if resume_dir:
        out_dir = Path(resume_dir)
        run_id = out_dir.name
        partial_path = out_dir / "pred.partial.jsonl"
        if partial_path.exists():
            old_pred_records = [
                json.loads(line) for line in partial_path.open(encoding="utf-8") if line.strip()
            ]
        _assert_pred_gt_coverage(gt_records, old_pred_records, Path(args.gt), partial_path)
        skip_titles = {r["title"] for r in old_pred_records}
        resumed_from_n_articles = len(skip_titles)
        progress_path = out_dir / "progress.jsonl"
        if progress_path.exists():
            progress_text = progress_path.read_text(encoding="utf-8")
            progress_lines = [line for line in progress_text.splitlines() if line.strip()]
            if progress_lines:
                last = json.loads(progress_lines[-1])
                guard.spent = last["spent"]
                # finding 3: restore the spend/call SPLIT too, not just the
                # total -- otherwise a resumed run's max_judge_calls ceiling
                # silently resets to zero judge calls spent, and meta.json's
                # spend-by-kind undercounts everything before the resume.
                if "spent_by_kind" in last and "calls_by_kind" in last:
                    guard.spent_by_kind = dict(last["spent_by_kind"])
                    guard.calls_by_kind = dict(last["calls_by_kind"])
                else:
                    print(
                        "wiki_eval: WARNING --resume from an old-format progress.jsonl line "
                        "(no spent_by_kind/calls_by_kind) -- spend split and judge-call ceiling "
                        "reset to zero for the resumed portion (bounded imprecision, spec finding 3)",
                        file=sys.stderr,
                    )

    started_at = datetime.now(timezone.utc)
    if run_id is None:
        run_id = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = OUT_ROOT / slug / args.config / run_id
    # Created at START, not at the end (checkpoint patch): _process_articles_
    # parallel needs somewhere to append pred.partial.jsonl/progress.jsonl as
    # each article finishes, well before this invocation itself completes.
    out_dir.mkdir(parents=True, exist_ok=True)

    new_pred_records, counters = _run_one_config(
        args.config, gt_records, args.cache, dry_run=False, guard=guard,
        model=args.model, provider=args.provider, extra_body=extra_body,
        base_url=args.base_url, temperature=args.temperature, top_p=args.top_p,
        top_k=args.top_k, max_tokens=args.max_tokens,
        article_workers=args.article_workers,
        llm_workers=args.llm_workers, wikidata_cache=args.wikidata_cache,
        wikidata_workers=args.wikidata_workers, use_sitelink=use_sitelink,
        out_dir=out_dir, skip_titles=frozenset(skip_titles), n_done_start=len(skip_titles),
        no_judge=getattr(args, "no_judge", False),
    )
    finished_at = datetime.now(timezone.utc)

    # Merge resumed + newly-produced records, then replay gt_records' input
    # order (checkpoint patch): pred.partial.jsonl only guarantees REAL
    # completion order across however many invocations wrote to it, which is
    # not deterministic across article workers -- grouping by title and
    # replaying gt_records' order restores the same deterministic layout
    # `run` always gave before checkpointing existed.
    records_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in old_pred_records + new_pred_records:
        records_by_title[r["title"]].append(r)
    pred_records = [r for rec in gt_records for r in records_by_title.get(rec["title"], [])]

    with (out_dir / "pred.jsonl").open("w", encoding="utf-8") as fh:
        for r in pred_records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Clean completion (checkpoint patch): the merged, authoritative pred.jsonl
    # is now on disk, so the partial file that made this resumable is spent.
    partial_path = out_dir / "pred.partial.jsonl"
    if partial_path.exists():
        partial_path.unlink()

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
        "article_workers": args.article_workers,
        "llm_semaphore": args.llm_workers,
        "wikidata_workers": args.wikidata_workers,
        "stopped_reason": guard.stopped_reason,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "wall_clock_s": (finished_at - started_at).total_seconds(),
        # Per-run effective generation params (spec Р3/Р8): audit trail for
        # exactly what was sent on the wire, not just the CLI flags given.
        "generation_params": {
            "model": route["model"],
            "base_url": route["base_url"],
            "provider_pin": route["provider_pin"],
            "temperature": route["temperature"],
            "top_p": route["top_p"],
            "top_k": route["extra_body"].get("top_k"),
            "max_tokens": route["max_tokens"],
            "reasoning": route["extra_body"].get("reasoning"),
            "extra_body_effective": route["extra_body"],
        },
        **counters,
    }
    if resumed_from_n_articles is not None:
        meta["resumed_from_n_articles"] = resumed_from_n_articles
    # Self-consistency fix (finding 3): counters["n_pred_mentions"] from
    # _run_one_config only counts THIS invocation's newly-produced records --
    # on a --resume run that undercounts the merged total. pred_records above
    # is already the full resumed+new merge, so it's the honest count.
    meta["n_pred_mentions"] = len(pred_records)
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
    # No separate coverage guard here: `ablate` never reads an external
    # pred.jsonl itself, it only loops `cmd_run` (whose own
    # _assert_pred_gt_coverage call fires when --resume replays a prior
    # pred.partial.jsonl) -- so the guard is inherited per-config for free.
    for bits in ALL_CONFIG_BITS:
        sub_args = argparse.Namespace(**{**vars(args), "config": bits})
        rc = cmd_run(sub_args)
        if rc != 0:
            return rc
    return 0


# ── report (protocol v3, spec 2026-07-10 Р9) ────────────────────────────────
#
# GT/pred token indices are ARTICLE-LOCAL (reset to 0 per article -- spec
# E-D6). Aggregation must therefore group by article title and dedup each
# article's tuples independently (metrics.aggregate_corpus_v3); flattening
# all articles' tuples into one list before dedup would cross-collide
# identical QIDs from unrelated articles.


def cmd_report(args) -> int:
    gt_records = _load_gt(Path(args.gt))
    tier_assignment: dict[str, int] = json.loads(Path(args.tier).read_text(encoding="utf-8"))

    pred_dir = Path(args.pred)
    pred_path = pred_dir / "pred.jsonl"
    all_pred_records = [json.loads(l) for l in pred_path.open(encoding="utf-8") if l.strip()] if pred_path.exists() else []
    _assert_pred_gt_coverage(gt_records, all_pred_records, Path(args.gt), pred_path)

    pred_by_title: dict[str, list[dict]] = defaultdict(list)
    for r in all_pred_records:
        pred_by_title[r["title"]].append(r)

    articles: list[M.ArticleUnits] = []
    for rec in gt_records:
        gt_tuples = [tuple(t) for t in rec["gt_tuples"]]
        title_pred_records = pred_by_title.get(rec["title"], [])
        pred_tuples = [
            (r["index"], r["surface"], r["qid"], r["span_len"])
            for r in title_pred_records if r.get("qid")
        ]
        articles.append({"gt_tuples": gt_tuples, "pred_tuples": pred_tuples})

    result = M.aggregate_corpus_v3(articles, tier_assignment=tier_assignment)

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

    html_body = report.render_html_v3(result, meta)
    html_doc = f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Wiki-eval report — {meta['config']}</title></head><body>{html_body}</body></html>"
    report_out = pred_dir / "report.html"
    report_out.write_text(html_doc, encoding="utf-8")

    print(f"wrote {metrics_out}")
    print(f"wrote {report_out}")
    for cls in ("named", "term"):
        s = result["classes"][cls]
        print(f"{cls}: gold_units={s['gold_units']}  R_doc={s['R_doc']['value']}  P_doc={s['P_doc']['value']}")
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
    p_run.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model id (default: %(default)s)")
    p_run.add_argument("--provider", default=None,
                        help="OpenRouter provider pin (display name, e.g. \"Novita\"); default "
                             "from MODEL_PARAMS for known models; \"auto\" disables pinning and "
                             "the per-call served-by gate")
    p_run.add_argument("--base-url", default=None, help=f"OpenAI-compatible base URL (default: {DEFAULT_BASE_URL}; "
                        "local vLLM runs pass their own, spec Р12)")
    p_run.add_argument("--temperature", type=float, default=None, help="default: MODEL_PARAMS per-model vendor recommendation")
    p_run.add_argument("--top-p", type=float, default=None, help="default: MODEL_PARAMS per-model vendor recommendation")
    p_run.add_argument("--top-k", type=int, default=None, help="default: MODEL_PARAMS per-model vendor recommendation")
    p_run.add_argument("--max-tokens", type=int, default=None, help=f"default: {DEFAULT_MAX_TOKENS} (spec Р3, both roles)")
    p_run.add_argument("--extra-body", default=None,
                        help="JSON object merged PER-KEY over the computed defaults (provider pin, "
                             "reasoning shape, top_k, OpenRouter usage.include) -- never replaces "
                             "them wholesale (sr004 local-judge patch: e.g. "
                             "'{\"chat_template_kwargs\": {\"enable_thinking\": false}}' for a local "
                             "vLLM thinking-capable model -- see docs/runbooks/sr004-local-eval-runbook.md)")
    p_run.add_argument("--max-judge-calls", type=int, default=MAX_JUDGE_CALLS, help="hard ceiling on judge calls (spec Sec.11)")
    p_run.add_argument("--article-workers", type=int, default=DEFAULT_ARTICLE_WORKERS,
                        help="articles processed concurrently (ticket 002b); LLM calls "
                             "stay capped at --llm-workers regardless of this value")
    p_run.add_argument("--llm-workers", type=int, default=DEFAULT_LLM_WORKERS,
                        help="process-wide cap on concurrent in-flight LLM calls (extract+judge "
                             "combined); sizes the llm_semaphore (ticket 004; owner-approved 16 "
                             "for model-comparison matrix runs)")
    p_run.add_argument("--wikidata-cache", default=str(WIKIDATA_CACHE),
                        help="Wikidata JSONL cache path (ticket 004: per-run copies avoid a "
                             "cross-process append race when several runs execute in parallel)")
    p_run.add_argument("--wikidata-workers", type=int, default=DEFAULT_NETWORK_CONCURRENCY,
                        help="concurrent live Wikidata API calls for this process (politeness "
                             "bound; matrix runs pass 2 so 4 parallel processes stay under the "
                             "API's rate limit -- 2026-07-05 canary 429-storm adaptation)")
    p_run.add_argument("--dry-run", action="store_true", help="print cost forecast only, write nothing")
    p_run.add_argument("--no-sitelink", action="store_true",
                        help="force GroundingConfig.use_sitelink=False regardless of --config's "
                             "bits (docs/stages/wiki-eval.md Subtleties: the RU-title->Wikidata "
                             "sitelink rung shares its mapping with wiki-eval's own GT construction, "
                             "so scoring runs must disable it to avoid annotation-mechanism "
                             "circularity; use_cirrus stays whatever --config's middle bit says)")
    p_run.add_argument("--resume", default=None,
                        help="resume a prior run dir: skip articles already in its "
                             "pred.partial.jsonl (by title), reuse its run_id, and seed the "
                             "budget guard from progress.jsonl's last recorded spend")
    p_run.add_argument("--no-judge", action="store_true",
                        help="NER-extraction-only cost mode: never build/call the disambiguation "
                             "judge (judge=None). Exact-label matches (no ambiguity) and the free "
                             "Wikidata candidate search still run unchanged; genuinely ambiguous "
                             "mentions resolve to resolved_by=judge_unavailable instead of an LLM "
                             "judge call. meta.json's no_judge field discloses this.")
    p_run.set_defaults(func=cmd_run)

    p_ablate = sub.add_parser("ablate", help="loop `run` over all 8 configs, sharing the judge cache")
    p_ablate.add_argument("--gt", default=str(DEFAULT_GT))
    p_ablate.add_argument("--cache", default=str(DEFAULT_PAGES_CACHE))
    p_ablate.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    p_ablate.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model id (default: %(default)s)")
    p_ablate.add_argument("--provider", default=None,
                           help="OpenRouter provider pin (display name, e.g. \"Novita\"); default "
                                "from MODEL_PARAMS for known models; \"auto\" disables pinning and "
                                "the per-call served-by gate")
    p_ablate.add_argument("--base-url", default=None, help=f"OpenAI-compatible base URL (default: {DEFAULT_BASE_URL}; "
                           "local vLLM runs pass their own, spec Р12)")
    p_ablate.add_argument("--temperature", type=float, default=None, help="default: MODEL_PARAMS per-model vendor recommendation")
    p_ablate.add_argument("--top-p", type=float, default=None, help="default: MODEL_PARAMS per-model vendor recommendation")
    p_ablate.add_argument("--top-k", type=int, default=None, help="default: MODEL_PARAMS per-model vendor recommendation")
    p_ablate.add_argument("--max-tokens", type=int, default=None, help=f"default: {DEFAULT_MAX_TOKENS} (spec Р3, both roles)")
    p_ablate.add_argument("--extra-body", default=None,
                           help="JSON object merged PER-KEY over the computed defaults -- see "
                                "`run --extra-body`'s help for the sr004 local-judge use case")
    p_ablate.add_argument("--max-judge-calls", type=int, default=MAX_JUDGE_CALLS, help="hard ceiling on judge calls (spec Sec.11)")
    p_ablate.add_argument("--article-workers", type=int, default=DEFAULT_ARTICLE_WORKERS,
                           help="articles processed concurrently (ticket 002b); LLM calls "
                                "stay capped at --llm-workers regardless of this value")
    p_ablate.add_argument("--llm-workers", type=int, default=DEFAULT_LLM_WORKERS,
                           help="process-wide cap on concurrent in-flight LLM calls (extract+judge "
                                "combined); sizes the llm_semaphore (ticket 004; owner-approved 16 "
                                "for model-comparison matrix runs)")
    p_ablate.add_argument("--wikidata-cache", default=str(WIKIDATA_CACHE),
                           help="Wikidata JSONL cache path (ticket 004: per-run copies avoid a "
                                "cross-process append race when several runs execute in parallel)")
    p_ablate.add_argument("--wikidata-workers", type=int, default=DEFAULT_NETWORK_CONCURRENCY,
                           help="concurrent live Wikidata API calls for this process (politeness "
                                "bound; matrix runs pass 2 so 4 parallel processes stay under the "
                                "API's rate limit -- 2026-07-05 canary 429-storm adaptation)")
    p_ablate.add_argument("--dry-run", action="store_true")
    p_ablate.set_defaults(func=cmd_ablate)

    p_report = sub.add_parser("report", help="offline recompute: metrics.json + report.html from persisted pred + gt")
    p_report.add_argument("--gt", default=str(DEFAULT_GT))
    p_report.add_argument("--pred", required=True, help="run dir containing pred.jsonl, e.g. reports/terminology/wiki-eval/<model-slug>/111/<run_id>")
    p_report.add_argument("--ablation", action="store_true", help="reserved for a future multi-config comparison report")
    p_report.add_argument("--tier", default=str(TIER_PATH),
                           help="tier_assignment.json path (QID -> tier int; protocol v3's "
                                "generic-lexical-class gold filter, spec Sec.4.5)")
    p_report.set_defaults(func=cmd_report)

    return ap


def main() -> int:
    args = _build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
