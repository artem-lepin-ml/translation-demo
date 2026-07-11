#!/usr/bin/env python3
"""Re-score the 4 vendored BOUQUET ru2en translation systems with pluggable
cloud LLM judges, through an OpenAI-compatible gateway (env
OPENROUTER_BASE_URL + OPENROUTER_API_KEY -- the key is read from the
environment only and never printed or logged).

Paper goal: Table A "LLM-as-a-judge" -- same-translations-different-judges
comparison. Grounded on the vendored pipeline in external/gse-translation
(read-only, untouched):

- Prompts: external/gse-translation/prompts/03_scoring/v1_core3/{accuracy,
  fluency,style}.md -- one file = one criterion's system prompt (mirrors
  `load_prompts()` in external/gse-translation/src/palimpsest/scoring.py:
  sorted `*.md` glob, filename stem as key).
- User message: byte-identical to scoring.py's `_USER_MSG_TEMPLATE`.
- Output contract: `response_format={"type":"json_object"}`; a valid reply is
  a JSON object with an integer `final_score` in [1, 10] (plus
  `identified_issues` / `criteria_assessment` / `summary`, which are not
  validated but are persisted verbatim in `llm_report`). Extraction/validation
  in `parse_judge_response()` below is a byte-for-byte port of scoring.py's
  function of the same name -- same JSON-fence handling, same failure
  categories ("empty" / "json_decode" / "missing_score" / "score_out_of_range"),
  same 1-retry-on-parse-failure policy (`_MAX_PARSE_ATTEMPTS = 2`) -- so scores
  produced here are comparable with Danil's own judge runs.
- The 4 judged systems (`qwen-27b-bouquet`, `qwen-27b-bouquet-refined`,
  `translate-gemma-bouquet`, `translate-gemma-bouquet-refined`) live under
  external/gse-translation/data/bouquet/{translation,evaluation}/<system>/;
  translations are `translation/<system>/translation.json` (flat list[str],
  198 entries, index-aligned with `bouquet_original.json`); vendored
  per-paragraph automatic-metric scores for the `stats` subcommand live at
  `evaluation/<system>/metricx/scores{,_wo_ref}.jsonl` (`prediction` field,
  same 0-based positional order as the source file -- no explicit id column,
  confirmed by scripts/judge_metric_stats.py's validated read of this same
  data) and `evaluation/<system>/comet/scores.json` (`paragraph_scores` list).
- BOUQUET paragraphs carry no `"* * *"` / `"picture"` / `"[TRANSLATION
  FAILED]"` markers (checked directly against all 4 translation.json files --
  0 hits), so this runner does not port scoring.py's `classify_paragraph`
  marker-skip branch: it cannot fire on this dataset.
- HTTP retry policy (transient errors only: timeout / connection drop / 429 /
  5xx) and the neutral `User-Agent: palimpsest-llm/1.0` header follow this
  repo's OWN llm client (src/palimpsest/llm/client.py) -- the owner-directed
  "3 attempts, 1s/3s/9s backoff" convention for CloseRouter's ~90% per-route
  success rate, not the vendored external package's numbers.
- deepseek-v4-flash judge-role regime (T=0, `reasoning.enabled=false`, no
  provider pin) is exactly the config validated by the 2026-07-07 live smoke
  (docs/reports/2026-07-07-deepseek-closerouter-smoke.md) and recorded in
  docs/known_issues.md.

Usage:
    python scripts/bouquet_judge_rerun.py run --judge deepseek-v4-flash \\
        --system translate-gemma-bouquet --pilot 5

    python scripts/bouquet_judge_rerun.py stats --judge deepseek-v4-flash

Output layout (append-only; existing rows are NEVER overwritten or deleted --
LLM predictions are irreplaceable, CLAUDE.md/.claude/rules/invariants.md):
    reports/bouquet/judges/<judge_slug>/scores.jsonl          one row per
        (system, paragraph id, criterion)
    reports/bouquet/judges/<judge_slug>/parse_failures.jsonl  diagnostic log,
        absence from scores.jsonl is what drives the resumable retry
    reports/bouquet/judges/<judge_slug>/stats.json            `stats` output
    reports/bouquet/judges/summary.md                         combined table
        across every judge with a stats.json present
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import yaml

try:
    from scipy import stats as _scipy_stats
except ImportError:  # pragma: no cover -- exercised whenever scipy isn't installed
    _scipy_stats = None

ROOT = Path(__file__).resolve().parents[1]
GSE_ROOT = ROOT / "external/gse-translation"
PROMPTS_DIR = GSE_ROOT / "prompts/03_scoring/v1_core3"
BOUQUET_DIR = GSE_ROOT / "data/bouquet"
TRANSLATION_DIR = BOUQUET_DIR / "translation"
DEFAULT_EVAL_ROOT = BOUQUET_DIR / "evaluation"
ORIGINAL_JSON = BOUQUET_DIR / "bouquet_original.json"

DEFAULT_JUDGE_CONFIG = ROOT / "configs/bouquet_judges.yaml"
DEFAULT_OUT_DIR = ROOT / "reports/bouquet/judges"

SYSTEMS: tuple[str, ...] = (
    "qwen-27b-bouquet",
    "qwen-27b-bouquet-refined",
    "translate-gemma-bouquet",
    "translate-gemma-bouquet-refined",
)
SYSTEM_LABELS: dict[str, str] = {
    "qwen-27b-bouquet": "Qwen3.6-27B",
    "qwen-27b-bouquet-refined": "Qwen3.6-27B Refined",
    "translate-gemma-bouquet": "Translate Gemma",
    "translate-gemma-bouquet-refined": "Translate Gemma Refined",
}
CRITERIA: tuple[str, ...] = ("accuracy", "fluency", "style")
METRICS: tuple[str, ...] = ("metricx_ref", "metricx_qe", "comet")

# repo-wide fallback (probe_providers.py, wiki_eval.py, rebuild_demo.py, ...).
DEFAULT_BASE_URL = "https://api.closerouter.dev/v1"
# matches src/palimpsest/llm/client.py -- CloseRouter WAF workaround.
USER_AGENT = "palimpsest-llm/1.0"

# ---------------------------------------------------------------------------
# Prompt assembly -- mirrors external/gse-translation/src/palimpsest/scoring.py
# ---------------------------------------------------------------------------

_USER_MSG_TEMPLATE = (
    '**Source text (Russian)** — for reference when identifying recurring'
    ' elements:\n{}\n\n**Translation (English)** — this is what you are evaluating:\n{}'
)
_JUDGE_RESPONSE_FORMAT = {"type": "json_object"}
_JSON_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)
_MAX_PARSE_ATTEMPTS = 2  # 1 initial + 1 retry -- scoring.py's `_MAX_PARSE_ATTEMPTS`


def load_prompts(prompts_dir: Path = PROMPTS_DIR) -> dict[str, str]:
    """`{criterion: system_prompt_text}`, sorted by filename stem (mirrors
    scoring.py's `load_prompts`). Raises if the directory is empty/missing."""
    files = sorted(prompts_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"no *.md prompts found in {prompts_dir}")
    return {f.stem: f.read_text(encoding="utf-8") for f in files}


class JudgeParseError(Exception):
    """A judge response could not be parsed into a valid payload.

    Byte-for-byte port of scoring.py's `JudgeParseError` / `parse_judge_response`
    (reasons: "empty" | "json_decode" | "missing_score" | "score_out_of_range").
    """

    def __init__(self, criterion: str, raw: str, reason: str):
        self.criterion = criterion
        self.raw = raw
        self.reason = reason
        super().__init__(f"{criterion}: {reason}")


def parse_judge_response(raw: str, criterion: str) -> dict[str, Any]:
    """Extract a JSON object from a judge response and validate `final_score`.

    Mirrors scoring.py's `parse_judge_response` exactly: handles a
    ```json fenced block or bare JSON (with prose around it tolerated only
    via the fence match -- unfenced prose-wrapped JSON still fails to
    `json.loads` and raises, same as upstream).
    """
    if not raw or not raw.strip():
        raise JudgeParseError(criterion, raw or "", "empty")
    match = _JSON_FENCE.search(raw)
    candidate = match.group(1) if match else raw
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise JudgeParseError(criterion, raw, f"json_decode: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise JudgeParseError(criterion, raw, "json_decode: not an object")
    score = parsed.get("final_score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise JudgeParseError(criterion, raw, "missing_score")
    if not 1 <= score <= 10:
        raise JudgeParseError(criterion, raw, "score_out_of_range")
    return parsed


# ---------------------------------------------------------------------------
# Judge config
# ---------------------------------------------------------------------------

_REGIMES = ("t0_no_reasoning", "frontier_default", "t0_reasoning_on", "vendor_default", "t0_local")


@dataclass(slots=True)
class JudgeSpec:
    slug: str
    router_id: str
    regime: str
    max_tokens: int = 8192
    enabled: bool = True
    supports_structured_output: bool = True
    # Raw dict merged verbatim into the request body (sr004 local-judge patch,
    # 2026-07-09: docs/runbooks/sr004-local-eval-runbook.md). Only consumer
    # today is a local vLLM judge that needs `chat_template_kwargs:
    # {enable_thinking: false}` -- vLLM's OpenAI-compat server exposes that as
    # a first-party top-level request field (same mechanism Danil's
    # models.yaml `extra_body` already uses for this exact model, see
    # docs/stages/translation-eval.md). Not an OpenRouter/CloseRouter
    # `extra_body` passthrough (this runner has no such wrapper) -- the dict's
    # keys are merged straight into the top-level JSON payload.
    extra_body: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.regime not in _REGIMES:
            raise ValueError(
                f"judge {self.slug!r}: unknown regime {self.regime!r} (want one of {_REGIMES})"
            )


def load_judges(path: Path) -> dict[str, JudgeSpec]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs: dict[str, JudgeSpec] = {}
    for entry in data["judges"]:
        spec = JudgeSpec(
            slug=entry["slug"],
            router_id=entry["router_id"],
            regime=entry["regime"],
            max_tokens=int(entry.get("max_tokens", 8192)),
            enabled=bool(entry.get("enabled", True)),
            supports_structured_output=bool(entry.get("supports_structured_output", True)),
            extra_body=entry.get("extra_body"),
        )
        if spec.slug in specs:
            raise ValueError(f"duplicate judge slug in {path}: {spec.slug!r}")
        specs[spec.slug] = spec
    return specs


def build_payload(judge: JudgeSpec, system_prompt: str, user_msg: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": judge.router_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": judge.max_tokens,
    }
    if judge.supports_structured_output:
        payload["response_format"] = _JUDGE_RESPONSE_FORMAT
    if judge.regime == "t0_no_reasoning":
        payload["temperature"] = 0
        payload["reasoning"] = {"enabled": False}
    elif judge.regime == "t0_reasoning_on":
        # T=0 (deterministic scoring) + reasoning explicitly ON. 2026-07-08
        # owner decision (docs/paper/paper-state.md "Table A protocol"):
        # `reasoning.enabled=false` never actually suppressed deepseek-v4-flash's
        # thinking on this route (confirmed twice: the judge-probe's 2 realistic
        # calls at 89% reasoning share, and this runner's own reasoning-suppression
        # follow-up -- omitting the param entirely, and `reasoning.effort="none"`,
        # both still reasoned at 53-100% of completion tokens) -- so the config
        # now discloses the true behavior instead of a misleading `enabled=false`.
        payload["temperature"] = 0
        payload["reasoning"] = {"enabled": True}
    elif judge.regime == "frontier_default":
        # No `temperature` (rejected/ignored by several reasoning models on this
        # proxy). `reasoning: {enabled: true}` IS sent explicitly, at default
        # effort -- 2026-07-08 probe (docs/experiments/2026-07-08-judge-probe/
        # probe-results.md) confirmed this is a harmless no-op for Opus 4.8
        # (reasoning silently stays 0 either way, same as the OpenAI-compat
        # bridge's known Claude behaviour) and works as intended for GPT-5.5 /
        # Gemini 3.1 Pro (both reason with it set).
        payload["reasoning"] = {"enabled": True}
    elif judge.regime == "vendor_default":
        # Neither `temperature` nor `reasoning` is sent -- true provider
        # defaults, no override either way. 2026-07-08 smoke (2 realistic
        # calls, docs/reports/python-pro-judge-run-gemini-flash-lite.md)
        # confirmed gemini-3.1-flash-lite reasons OFF by default on this route
        # (reasoning_tokens=0 both times) and accepts response_format=
        # json_object cleanly (unlike gemini-3.1-pro-preview's frontier_default
        # regime, which needs supports_structured_output: false).
        pass
    elif judge.regime == "t0_local":
        # sr004 local vLLM judges (2026-07-09, docs/runbooks/
        # sr004-local-eval-runbook.md): temperature=0 only, deliberately no
        # `reasoning` key -- that field is an OpenRouter/CloseRouter
        # convention a raw vLLM OpenAI-compat server doesn't implement.
        # Thinking-capable local models (Qwen3.6-27B) toggle via
        # `judge.extra_body`'s `chat_template_kwargs.enable_thinking` below,
        # not via this regime.
        payload["temperature"] = 0
    # `extra_body` (any regime): merged last so it can add fields no regime
    # branch above sets (e.g. vLLM's `chat_template_kwargs`) without needing
    # a bespoke regime per model.
    if judge.extra_body:
        payload.update(judge.extra_body)
    return payload


# ---------------------------------------------------------------------------
# HTTP: retry policy mirrors src/palimpsest/llm/client.py's owner directive
# ("3 attempts, 1s/3s/9s backoff" for CloseRouter's ~90% per-route success).
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_S: tuple[float, ...] = (1.0, 3.0, 9.0)


class TransientHTTPError(Exception):
    """Retryable: timeout / connection drop / 429 / 5xx / empty content."""


class JudgeCallError(Exception):
    """Non-retryable: 4xx other than 429, or malformed response envelope."""


def _usage_from_response(usage: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize the provider `usage` block. OpenRouter surfaces `cost`;
    CloseRouter surfaces `cost_usd` -- mirrors llm/client.py's fallback."""
    if not usage:
        return None
    details = usage.get("completion_tokens_details") or {}
    cost = usage.get("cost", usage.get("cost_usd"))
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
        "reasoning_tokens": int(details.get("reasoning_tokens", 0) or 0),
        "cost": float(cost) if cost is not None else None,
    }


async def _post_chat(
    client: httpx.AsyncClient, base_url: str, api_key: str, payload: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """POST one chat/completions call with retry-on-transient. Returns
    (content, usage_dict). Never logs `api_key` -- only used in the header."""
    last_exc: Exception | None = None
    url = f"{base_url.rstrip('/')}/chat/completions"
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=120.0,
            )
        except httpx.TransportError as exc:
            # httpx.TransportError is the base of ConnectError/ConnectTimeout/
            # ReadTimeout/TimeoutException (already handled below) plus
            # ReadError/WriteError/RemoteProtocolError -- all connection-drop
            # variants per the module docstring's "transient errors only:
            # timeout / connection drop / 429 / 5xx" intent. The narrower
            # tuple this replaces missed httpx.ReadError, which crashed a
            # live 2026-07-08 deepseek-v4-flash pilot run mid-flight (an
            # unhandled exception from asyncio.as_completed aborts the whole
            # `run` invocation, not just the one in-flight call).
            last_exc = TransientHTTPError(f"{type(exc).__name__}: {exc}")
        else:
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = TransientHTTPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            elif resp.status_code >= 400:
                raise JudgeCallError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            else:
                data = resp.json()
                choice = data["choices"][0]["message"]
                content = choice.get("content") or ""
                usage = _usage_from_response(data.get("usage"))
                if not content.strip():
                    last_exc = TransientHTTPError("empty content from provider")
                else:
                    return content, usage

        if attempt >= _RETRY_ATTEMPTS:
            break
        delay = _RETRY_BACKOFF_S[min(attempt - 1, len(_RETRY_BACKOFF_S) - 1)]
        print(
            f"[retry] {payload['model']} attempt {attempt}/{_RETRY_ATTEMPTS} "
            f"after {type(last_exc).__name__}: sleep {delay:.1f}s",
            file=sys.stderr, flush=True,
        )
        await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc


async def score_one_criterion(
    client: httpx.AsyncClient, base_url: str, api_key: str,
    judge: JudgeSpec, criterion: str, system_prompt: str, source: str, translated: str,
) -> tuple[dict[str, Any] | JudgeParseError, dict[str, Any] | None]:
    """One criterion call with `_MAX_PARSE_ATTEMPTS` inline retries on parse
    failure (mirrors scoring.py's `score_paragraph._one`)."""
    user_msg = _USER_MSG_TEMPLATE.format(source, translated)
    payload = build_payload(judge, system_prompt, user_msg)
    last_exc: JudgeParseError | None = None
    last_usage: dict[str, Any] | None = None
    for attempt in range(_MAX_PARSE_ATTEMPTS):
        content, usage = await _post_chat(client, base_url, api_key, payload)
        last_usage = usage
        try:
            return parse_judge_response(content, criterion), last_usage
        except JudgeParseError as exc:
            last_exc = exc
            if attempt + 1 < _MAX_PARSE_ATTEMPTS:
                print(
                    f"warning: parse failure for {criterion} "
                    f"(attempt {attempt + 1}/{_MAX_PARSE_ATTEMPTS}, reason={exc.reason}); retrying",
                    file=sys.stderr, flush=True,
                )
    assert last_exc is not None
    return last_exc, last_usage


# ---------------------------------------------------------------------------
# JSONL persistence -- append-only, fsync'd (never overwrite/delete a row:
# .claude/rules/invariants.md "Never delete LLM predictions").
# ---------------------------------------------------------------------------


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_existing_keys(scores_path: Path) -> set[tuple[str, int, str]]:
    """`{(system, paragraph_id, criterion)}` already persisted -- presence in
    scores.jsonl = done, absence = retry target on resume."""
    keys: set[tuple[str, int, str]] = set()
    for row in read_jsonl(scores_path):
        if {"system", "id", "criterion"} <= row.keys():
            keys.add((row["system"], row["id"], row["criterion"]))
    return keys


# $/Mtok (prompt, completion) -- owner-supplied catalog prices, mirrors
# scripts/probe_providers.py's PRICE_TABLE. Used only as a *display* fallback
# when the gateway surfaces no `usage.cost`/`usage.cost_usd` at all -- observed
# for every deepseek-v4-flash call in the 2026-07-08 validation pilot on this
# CloseRouter route (neither key present in any of 15 raw responses; see the
# known_issues.md addendum this runner's grounding added).
PRICE_TABLE_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "deepseek/deepseek-v4-flash": (0.07, 0.14),
}


def compute_usage_totals(scores_path: Path) -> dict[str, Any]:
    """Cumulative usage/cost read back from disk (correct across resumes:
    covers both pre-existing and newly-appended rows). `cost_usd_real` sums
    only rows where the provider actually surfaced a cost; `cost_usd_estimated`
    fills the gap for the rest from `PRICE_TABLE_USD_PER_MTOK` (0.0 for an
    unlisted router_id -- no silent guess)."""
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
              "reasoning_tokens": 0, "cost_usd_real": 0.0, "cost_usd_estimated": 0.0,
              "rows_with_real_cost": 0, "rows_with_usage": 0, "rows_total": 0}
    for row in read_jsonl(scores_path):
        totals["rows_total"] += 1
        u = row.get("usage")
        if not u:
            continue
        totals["rows_with_usage"] += 1
        prompt_tok = int(u.get("prompt_tokens", 0) or 0)
        completion_tok = int(u.get("completion_tokens", 0) or 0)
        totals["prompt_tokens"] += prompt_tok
        totals["completion_tokens"] += completion_tok
        totals["total_tokens"] += int(u.get("total_tokens", 0) or 0)
        totals["reasoning_tokens"] += int(u.get("reasoning_tokens", 0) or 0)
        real_cost = u.get("cost")
        if real_cost is not None:
            totals["cost_usd_real"] += float(real_cost)
            totals["rows_with_real_cost"] += 1
        else:
            router_id = (row.get("request_params") or {}).get("router_id")
            prices = PRICE_TABLE_USD_PER_MTOK.get(router_id)
            if prices:
                price_in, price_out = prices
                totals["cost_usd_estimated"] += (
                    prompt_tok * price_in + completion_tok * price_out
                ) / 1_000_000
    return totals


# ---------------------------------------------------------------------------
# `run` -- score (judge x system x paragraph x criterion)
# ---------------------------------------------------------------------------


def _load_original() -> list[str]:
    return json.loads(ORIGINAL_JSON.read_text(encoding="utf-8"))


def _load_translation(system: str) -> list[str]:
    return json.loads((TRANSLATION_DIR / system / "translation.json").read_text(encoding="utf-8"))


async def run_judge(
    judge: JudgeSpec, systems: list[str], *, pilot: int | None, concurrency: int,
    out_dir: Path, base_url: str, api_key: str,
) -> None:
    prompts = load_prompts()
    original = _load_original()
    judge_dir = out_dir / judge.slug
    scores_path = judge_dir / "scores.jsonl"
    failures_path = judge_dir / "parse_failures.jsonl"
    existing = load_existing_keys(scores_path)

    translations = {s: _load_translation(s) for s in systems}
    for system, translated in translations.items():
        if len(translated) != len(original):
            raise ValueError(
                f"{system}: translation.json has {len(translated)} rows, "
                f"bouquet_original.json has {len(original)} -- index alignment broken"
            )

    plan: list[tuple[str, int, str]] = []
    n_in_scope = 0
    for system in systems:
        n = len(original) if pilot is None else min(pilot, len(original))
        n_in_scope += n * len(CRITERIA)
        for pid in range(n):
            for criterion in CRITERIA:
                if (system, pid, criterion) not in existing:
                    plan.append((system, pid, criterion))

    total = len(plan)
    skipped = n_in_scope - total
    print(
        f"[{judge.slug}] {total} calls planned across {len(systems)} system(s) "
        f"({skipped} already scored, skipped) -- concurrency={concurrency}",
        file=sys.stderr, flush=True,
    )
    if total == 0:
        print(f"[{judge.slug}] nothing to do.", file=sys.stderr, flush=True)
        return

    sem = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    # provenance metadata persisted per row -- t0_reasoning_on added alongside
    # t0_no_reasoning; frontier_default/unknown regimes keep their prior (None,
    # None) representation unchanged (other judges' in-flight runs read this
    # same module).
    _temperature = {"t0_no_reasoning": 0, "t0_reasoning_on": 0}.get(judge.regime)
    _reasoning_enabled = {"t0_no_reasoning": False, "t0_reasoning_on": True}.get(judge.regime)
    request_params = {
        "router_id": judge.router_id,
        "regime": judge.regime,
        "max_tokens": judge.max_tokens,
        "temperature": _temperature,
        "reasoning_enabled": _reasoning_enabled,
    }

    completed = 0
    failed = 0
    t0 = time.monotonic()

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:

        async def _one(system: str, pid: int, criterion: str) -> None:
            nonlocal completed, failed
            async with sem:
                source = original[pid]
                translated = translations[system][pid]
                try:
                    payload, usage = await score_one_criterion(
                        client, base_url, api_key, judge, criterion,
                        prompts[criterion], source, translated,
                    )
                except (TransientHTTPError, JudgeCallError) as exc:
                    # score_one_criterion only catches JudgeParseError inline;
                    # an HTTP failure (transient-exhausted-after-3-attempts, or
                    # a non-retryable 4xx) previously propagated straight
                    # through asyncio.as_completed and crashed the WHOLE batch,
                    # discarding every other in-flight/pending call -- observed
                    # live on 2026-07-08 (a genuine 400 from the gateway killed
                    # a 221-call deepseek-v4-flash pilot run after only 1 row).
                    # Recorded the same way as a parse failure: absence from
                    # scores.jsonl is what drives the resumable retry.
                    payload = JudgeParseError(criterion, "", f"http_error: {exc}")
                    usage = None
            ts = time.time()
            if isinstance(payload, JudgeParseError):
                failed += 1
                row = {
                    "system": system, "id": pid, "criterion": criterion,
                    "reason": payload.reason, "raw": payload.raw,
                    "judge_slug": judge.slug, "ts": ts,
                }
                async with write_lock:
                    append_jsonl_row(failures_path, row)
            else:
                completed += 1
                row = {
                    "judge_slug": judge.slug,
                    "system": system,
                    "id": pid,
                    "criterion": criterion,
                    "source": source,
                    "translated": translated,
                    "score": payload.get("final_score"),
                    "llm_report": payload,
                    "usage": usage,
                    "request_params": request_params,
                    "ts": ts,
                }
                async with write_lock:
                    append_jsonl_row(scores_path, row)

        tasks = [_one(system, pid, criterion) for system, pid, criterion in plan]
        done_n = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done_n += 1
            if done_n % 25 == 0 or done_n == total:
                print(
                    f"[{judge.slug}] {done_n}/{total} done "
                    f"({time.monotonic() - t0:.0f}s elapsed)",
                    file=sys.stderr, flush=True,
                )

    totals = compute_usage_totals(scores_path)
    print(
        f"[{judge.slug}] run finished: {completed} scored, {failed} parse failures "
        f"(logged to {failures_path.relative_to(ROOT)}), "
        f"{time.monotonic() - t0:.0f}s elapsed.",
        file=sys.stderr, flush=True,
    )
    print(
        f"[{judge.slug}] cumulative usage (all rows in scores.jsonl, incl. resumed): "
        f"prompt={totals['prompt_tokens']} completion={totals['completion_tokens']} "
        f"reasoning={totals['reasoning_tokens']} total={totals['total_tokens']} "
        f"({totals['rows_with_usage']}/{totals['rows_total']} rows with usage)",
        file=sys.stderr, flush=True,
    )
    print(
        f"[{judge.slug}] cost: real=${totals['cost_usd_real']:.4f} "
        f"({totals['rows_with_real_cost']}/{totals['rows_with_usage']} rows surfaced a real cost) "
        f"+ estimated=${totals['cost_usd_estimated']:.4f} (catalog price for rows with no real "
        f"cost) => total=${totals['cost_usd_real'] + totals['cost_usd_estimated']:.4f}",
        file=sys.stderr, flush=True,
    )


def cmd_run(args: argparse.Namespace) -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("error: OPENROUTER_API_KEY not set in environment", file=sys.stderr)
        return 2
    base_url = os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)

    judges = load_judges(args.config)
    slugs = args.judge or [s for s, j in judges.items() if j.enabled]
    unknown = [s for s in slugs if s not in judges]
    if unknown:
        print(f"error: unknown judge slug(s) {unknown} (known: {sorted(judges)})", file=sys.stderr)
        return 2
    blocked = [s for s in slugs if not judges[s].enabled and not args.allow_disabled]
    if blocked:
        print(
            f"error: judge(s) {blocked} are disabled in {args.config} "
            f"(requirement 7: frontier judges are not validated -- pass "
            f"--allow-disabled to override deliberately)",
            file=sys.stderr,
        )
        return 2

    systems = args.system or list(SYSTEMS)
    unknown_systems = [s for s in systems if s not in SYSTEMS]
    if unknown_systems:
        print(
            f"error: unknown system(s) {unknown_systems} (known: {list(SYSTEMS)})",
            file=sys.stderr,
        )
        return 2

    for slug in slugs:
        asyncio.run(run_judge(
            judges[slug], systems, pilot=args.pilot, concurrency=args.concurrency,
            out_dir=args.out_dir, base_url=base_url, api_key=api_key,
        ))
    return 0


# ---------------------------------------------------------------------------
# `stats` -- means / tie-rate / Spearman vs vendored MetricX-ref, MetricX-QE, COMET
# ---------------------------------------------------------------------------


def _rankdata_average(x: np.ndarray) -> np.ndarray:
    """Average-rank ranking (ties share the mean rank of their block), 1-based
    -- the same tie convention scipy.stats.spearmanr uses by default."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    sorted_x = x[order]
    n = len(x)
    i = 0
    while i < n:
        j = i
        while j < n - 1 and sorted_x[j + 1] == sorted_x[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman_rho(a: np.ndarray, b: np.ndarray) -> tuple[float | None, int]:
    """Paragraph-level Spearman rho over the paired non-NaN entries of `a`/`b`.
    Uses scipy if importable, else an exact average-rank fallback (same tie
    handling scipy's default uses -- requirement 5)."""
    mask = ~np.isnan(a) & ~np.isnan(b)
    a, b = a[mask], b[mask]
    n = len(a)
    if n < 2:
        return None, n
    if _scipy_stats is not None:
        rho, _p = _scipy_stats.spearmanr(a, b)
    else:
        ra, rb = _rankdata_average(a), _rankdata_average(b)
        if np.ptp(ra) == 0 or np.ptp(rb) == 0:
            return None, n
        rho = float(np.corrcoef(ra, rb)[0, 1])
    return (float(rho) if rho == rho else None), n


def load_metric_arrays(eval_root: Path, system: str) -> dict[str, np.ndarray]:
    """`{metric_name: per-paragraph array}`, positionally aligned with
    `bouquet_original.json` (no explicit id column in these vendored files --
    see module docstring)."""
    sys_dir = eval_root / system
    metricx_ref_rows = read_jsonl(sys_dir / "metricx" / "scores.jsonl")
    metricx_qe_rows = read_jsonl(sys_dir / "metricx" / "scores_wo_ref.jsonl")
    with (sys_dir / "comet" / "scores.json").open(encoding="utf-8") as fh:
        comet_scores = json.load(fh)["paragraph_scores"]

    lengths = {"metricx_ref": len(metricx_ref_rows), "metricx_qe": len(metricx_qe_rows),
               "comet": len(comet_scores)}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"{system}: misaligned vendored metric row counts: {lengths}")

    def col(rows: list[dict[str, Any]], key: str) -> np.ndarray:
        return np.array([r[key] if r.get(key) is not None else np.nan for r in rows], dtype=float)

    return {
        "metricx_ref": col(metricx_ref_rows, "prediction"),
        "metricx_qe": col(metricx_qe_rows, "prediction"),
        "comet": np.array(comet_scores, dtype=float),
    }


def build_judge_arrays(scores_path: Path, system: str, n_paragraphs: int) -> dict[str, np.ndarray]:
    by_criterion = {c: np.full(n_paragraphs, np.nan) for c in CRITERIA}
    for row in read_jsonl(scores_path):
        if row.get("system") != system:
            continue
        pid, criterion, score = row.get("id"), row.get("criterion"), row.get("score")
        if pid is None or criterion not in by_criterion or not (0 <= pid < n_paragraphs):
            continue
        if score is not None:
            by_criterion[criterion][pid] = float(score)
    return by_criterion


def _tie_and_mean(values: np.ndarray) -> dict[str, Any]:
    finite = values[~np.isnan(values)]
    n = int(finite.size)
    if n == 0:
        return {"n": 0, "mean": None, "tie_rate_9_10": None}
    return {
        "n": n,
        "mean": round(float(finite.mean()), 4),
        "tie_rate_9_10": round(float(np.isin(finite, [9, 10]).sum() / n), 4),
    }


def compute_stats_for_judge(
    judge_slug: str, out_dir: Path, eval_root: Path, systems: list[str],
) -> dict[str, Any]:
    scores_path = out_dir / judge_slug / "scores.jsonl"
    if not scores_path.is_file():
        raise FileNotFoundError(f"no scores.jsonl for judge {judge_slug!r} at {scores_path}")
    n_paragraphs = len(_load_original())

    result: dict[str, Any] = {
        "judge_slug": judge_slug,
        "generated_at": datetime.now(UTC).isoformat(),
        "n_paragraphs_total": n_paragraphs,
        "systems": {},
    }
    for system in systems:
        judge_arr = build_judge_arrays(scores_path, system, n_paragraphs)
        metric_arr = load_metric_arrays(eval_root, system)
        per_criterion: dict[str, Any] = {}
        for criterion in CRITERIA:
            cell = _tie_and_mean(judge_arr[criterion])
            cell["spearman"] = {}
            for metric_name in METRICS:
                rho, cell_n = spearman_rho(judge_arr[criterion], metric_arr[metric_name])
                cell["spearman"][metric_name] = {
                    "rho": round(rho, 4) if rho is not None else None, "n": cell_n,
                }
            per_criterion[criterion] = cell
        result["systems"][system] = per_criterion
    return result


def build_summary_md(out_dir: Path, judge_slugs: list[str]) -> str:
    lines = [
        "# BOUQUET multi-judge re-scoring — summary",
        "",
        f"Generated {datetime.now(UTC).isoformat()} by "
        "`scripts/bouquet_judge_rerun.py stats`.",
        "",
        "Per (judge × system × criterion): mean score, tie-rate (share of scores "
        "in {9,10}), paragraph-level Spearman rho vs vendored MetricX-ref / "
        "MetricX-QE / COMET (`n` = paired non-null paragraphs).",
        "",
        "| Judge | System | Criterion | N | Mean | Tie% 9-10 "
        "| ρ MetricX-ref | ρ MetricX-QE | ρ COMET |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def fmt_rho(cell: dict[str, Any]) -> str:
        if cell["rho"] is None:
            return f"n/a (n={cell['n']})"
        return f"{cell['rho']:+.4f} (n={cell['n']})"

    any_rows = False
    for slug in judge_slugs:
        stats_path = out_dir / slug / "stats.json"
        if not stats_path.is_file():
            continue
        data = json.loads(stats_path.read_text(encoding="utf-8"))
        for system, per_criterion in data["systems"].items():
            label = SYSTEM_LABELS.get(system, system)
            for criterion in CRITERIA:
                c = per_criterion[criterion]
                if c["n"] == 0:
                    continue
                any_rows = True
                sp = c["spearman"]
                lines.append(
                    f"| {slug} | {label} | {criterion} | {c['n']} | "
                    f"{c['mean']:.3f} | {c['tie_rate_9_10'] * 100:.1f}% | "
                    f"{fmt_rho(sp['metricx_ref'])} | {fmt_rho(sp['metricx_qe'])} | "
                    f"{fmt_rho(sp['comet'])} |"
                )
    if not any_rows:
        lines.append("| _(no scored rows yet)_ | | | | | | | | |")
    lines.append("")
    return "\n".join(lines)


def cmd_stats(args: argparse.Namespace) -> int:
    out_dir: Path = args.out_dir
    if args.judge:
        known = load_judges(args.config)
        unknown = [s for s in args.judge if s not in known]
        if unknown:
            print(
                f"error: unknown judge slug(s) {unknown} (known: {sorted(known)})",
                file=sys.stderr,
            )
            return 2
        slugs = args.judge
    else:
        slugs = (
            [d.name for d in sorted(out_dir.iterdir())
             if d.is_dir() and (d / "scores.jsonl").is_file()]
            if out_dir.is_dir() else []
        )
    if not slugs:
        print(f"no judges with scores.jsonl found under {out_dir}", file=sys.stderr)
        return 1

    systems = args.system or list(SYSTEMS)
    for slug in slugs:
        stats = compute_stats_for_judge(slug, out_dir, args.eval_root, systems)
        stats_path = out_dir / slug / "stats.json"
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{slug}] stats written to {stats_path.relative_to(ROOT)}", file=sys.stderr)

    # summary.md always aggregates every judge dir with a stats.json on disk,
    # regardless of --judge -- that flag scopes only the stats recomputation
    # above. Using the CLI-filtered `slugs` here silently dropped every other
    # judge's rows from summary.md (2026-07-09, docs/reports/
    # docs-keeper-tree-cleanup-b0ozsc.md).
    summary_slugs = sorted(
        d.name for d in out_dir.iterdir() if d.is_dir() and (d / "stats.json").is_file()
    )
    summary_md = build_summary_md(out_dir, summary_slugs)
    summary_path = out_dir / "summary.md"
    summary_path.write_text(summary_md, encoding="utf-8")
    print(f"combined summary written to {summary_path.relative_to(ROOT)}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="score (judge x system x paragraph x criterion) pairs")
    run_p.add_argument("--config", type=Path, default=DEFAULT_JUDGE_CONFIG,
                        help="judge registry YAML (default: %(default)s)")
    run_p.add_argument("--judge", nargs="+", default=None,
                        help="judge slug(s) to run (default: every judge with enabled: true)")
    run_p.add_argument("--system", nargs="+", default=None, choices=list(SYSTEMS),
                        help="system(s) to score (default: all 4)")
    run_p.add_argument("--pilot", type=int, default=None,
                        help="score only the first N paragraphs (default: all 198)")
    run_p.add_argument("--concurrency", type=int, default=6,
                        help="concurrent in-flight requests, recommended 4-8 "
                             "(default: %(default)s)")
    run_p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="output root (default: %(default)s)")
    run_p.add_argument("--allow-disabled", action="store_true",
                        help="override the enabled:false run-gate (e.g. frontier judges) -- "
                             "deliberate escape hatch, not for routine use")
    run_p.set_defaults(func=cmd_run)

    stats_p = sub.add_parser(
        "stats", help="means / tie-rate / Spearman vs vendored automatic metrics",
    )
    stats_p.add_argument("--config", type=Path, default=DEFAULT_JUDGE_CONFIG,
                          help="judge registry YAML, used only to validate --judge names")
    stats_p.add_argument("--judge", nargs="+", default=None,
                          help="judge slug(s) (default: every judge dir with a scores.jsonl)")
    stats_p.add_argument("--system", nargs="+", default=None, choices=list(SYSTEMS),
                          help="system(s) to include (default: all 4)")
    stats_p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                          help="root holding <judge_slug>/scores.jsonl (default: %(default)s)")
    stats_p.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT,
                          help="vendored per-system MetricX/COMET root (default: %(default)s)")
    stats_p.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
