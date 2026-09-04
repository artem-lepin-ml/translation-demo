"""Provider-route triage for OpenRouter models (ticket 003, 2026-07-05-model-comparison).

For each model id: probe a set of routes (`auto` + `provider-N` pins via
`extra_body={"provider": ...}`) with tiny (`max_tokens=8`) calls through
`palimpsest.llm.client.LLMClient` (carries the neutral User-Agent OpenRouter's
WAF requires). Classifies each route on success rate, latency, prompt-token
honesty (padding disqualifier) and cost/call, then applies the selection rule:

    success >= 9/10 AND honest tokens (median prompt_tokens <= 100)
        -> min cost/call (real cost_usd, else token-price estimate)
        -> tie-break min median latency

A route that fails its first two calls with a 404 or a "no available
provider/upstream" message is dead — the sweep stops early for that route
instead of burning the remaining calls. Other errors (5xx/timeout) don't
trigger early-stop; the full sweep runs so the failure mode is visible in the
stats.

Multiple `--model` values run concurrently (one thread per model); each
model's own route sweep is strictly sequential (`--sleep-s` between calls).

Usage:
    PYTHONPATH=src uv run python scripts/probe_providers.py \\
        --model openai/gpt-5.5 deepseek/deepseek-v4-flash qwen/qwen3.7-plus \\
        --routes auto,provider-1,provider-2,provider-3,provider-4,provider-5,\\
provider-6,provider-7,provider-8,provider-9,provider-10,provider-11,provider-12 \\
        --n 10

    PYTHONPATH=src uv run python scripts/probe_providers.py \\
        --model google/gemini-3.1-flash-lite --routes auto,provider-9 --n 10

Re-running with `--summary-only` (no `--model`) regenerates `summary.md` from
whatever `triage/<basename>.json` files already exist in `--out-dir` — useful
after running model groups in separate invocations.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from palimpsest.llm.client import LLMClient, LLMConfig

PROMPT = "Reply with exactly: ok"
SYSTEM = ""
BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY_ENV = "OPENROUTER_API_KEY"

# $/Mtok (prompt, completion) — owner-supplied catalog prices, used only when a
# call doesn't surface cost_usd itself.
PRICE_TABLE = {
    "openai/gpt-5.5": (0.30, 0.30),
    "deepseek/deepseek-v4-flash": (0.07, 0.14),
    "qwen/qwen3.7-plus": (0.20, 0.80),
}

DEAD_STATUS = {404}
DEAD_MARKERS = ("no available provider", "no available upstream", "no_available_provider")

DEFAULT_ROUTES = ["auto"] + [f"provider-{i}" for i in range(1, 13)]


def _redact(text: str) -> str:
    key = os.environ.get(API_KEY_ENV, "")
    if key and key in text:
        text = text.replace(key, "***REDACTED***")
    return text


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise SystemExit(f"{API_KEY_ENV} not set in environment")
    return key


def call_once(model: str, extra_body: dict | None, *, temperature: float | None = None,
              max_tokens: int = 8, timeout: float = 30.0) -> dict:
    cfg = LLMConfig(model=model, base_url=BASE_URL, api_key=_api_key(),
                     temperature=temperature, max_tokens=max_tokens,
                     extra_body=extra_body, timeout=timeout)
    client = LLMClient(cfg)
    t0 = time.monotonic()
    try:
        result = client.complete(system=SYSTEM, user=PROMPT)
        latency = time.monotonic() - t0
        return {
            "ok": True, "latency_s": latency,
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "cost_usd": result.usage.cost_usd,
            "error_class": None, "error_message": None, "http_status": None,
        }
    except Exception as exc:  # noqa: BLE001 — classify, never crash the sweep
        latency = time.monotonic() - t0
        status = getattr(exc, "status_code", None)
        return {
            "ok": False, "latency_s": latency,
            "prompt_tokens": None, "completion_tokens": None, "cost_usd": None,
            "error_class": type(exc).__name__, "error_message": _redact(str(exc))[:300],
            "http_status": status,
        }


def _is_dead_signal(call: dict) -> bool:
    if call["ok"]:
        return False
    if call["http_status"] in DEAD_STATUS:
        return True
    msg = (call["error_message"] or "").lower()
    return any(marker in msg for marker in DEAD_MARKERS)


def sweep_route(model: str, route: str, n: int, sleep_s: float) -> tuple[list[dict], bool, str | None]:
    """Sequential sweep of one route. Returns (calls, dead, auto_variant)."""
    calls: list[dict] = []
    auto_variant: str | None = None
    dead = False
    for i in range(n):
        if route == "auto" and i == 0:
            res = call_once(model, extra_body=None)
            if res["ok"]:
                auto_variant = "no_extra_body"
            else:
                first_error = {"error_class": res["error_class"], "error_message": res["error_message"]}
                res = call_once(model, extra_body={"provider": "auto"})
                auto_variant = "extra_body_auto"
                res["note"] = f"no_extra_body failed first ({first_error}); fell back to extra_body={{'provider':'auto'}}"
        elif route == "auto":
            extra_body = None if auto_variant == "no_extra_body" else {"provider": "auto"}
            res = call_once(model, extra_body=extra_body)
        else:
            res = call_once(model, extra_body={"provider": route})
        calls.append(res)
        time.sleep(sleep_s)
        if i == 1 and _is_dead_signal(calls[0]) and _is_dead_signal(calls[1]):
            dead = True
            break
    return calls, dead, auto_variant


def _percentile(xs: list[float], pct: float) -> float | None:
    if not xs:
        return None
    xs_sorted = sorted(xs)
    k = max(0, min(len(xs_sorted) - 1, math.ceil(pct / 100 * len(xs_sorted)) - 1))
    return xs_sorted[k]


def aggregate_route(model: str, calls: list[dict], dead: bool, auto_variant: str | None) -> dict:
    n_calls = len(calls)
    oks = [c for c in calls if c["ok"]]
    n_success = len(oks)
    success_rate = (n_success / n_calls) if n_calls else 0.0
    ok_latencies = [c["latency_s"] for c in oks] or [c["latency_s"] for c in calls]
    prompt_toks = [c["prompt_tokens"] for c in oks if c["prompt_tokens"] is not None]
    completion_toks = [c["completion_tokens"] for c in oks if c["completion_tokens"] is not None]
    costs = [c["cost_usd"] for c in oks if c["cost_usd"] is not None]

    ptok_median = statistics.median(prompt_toks) if prompt_toks else None
    ctok_median = statistics.median(completion_toks) if completion_toks else None
    honest = None if ptok_median is None else (ptok_median <= 100)

    cost_source = "unknown"
    cost_per_call = None
    if costs:
        cost_per_call = statistics.median(costs)
        cost_source = "real"
    elif model in PRICE_TABLE and ptok_median is not None and ctok_median is not None:
        price_p, price_c = PRICE_TABLE[model]
        cost_per_call = (ptok_median * price_p + ctok_median * price_c) / 1_000_000
        cost_source = "estimated"

    if dead:
        verdict = "dead"
    elif n_success == 0:
        verdict = "failed"
    elif success_rate < 0.9:
        verdict = "unstable"
    elif honest is False:
        verdict = "padded"
    elif honest is None:
        verdict = "unknown-tokens"
    else:
        verdict = "candidate"

    return {
        "n_calls": n_calls,
        "n_success": n_success,
        "success_rate": success_rate,
        "latency_median_s": statistics.median(ok_latencies) if ok_latencies else None,
        "latency_p90_s": _percentile(ok_latencies, 90),
        "prompt_tokens_median": ptok_median,
        "completion_tokens_median": ctok_median,
        "cost_per_call": cost_per_call,
        "cost_source": cost_source,
        "honest_tokens": honest,
        "dead": dead,
        "auto_variant": auto_variant,
        "verdict": verdict,
    }


def select_route(route_stats: dict[str, dict]) -> dict:
    def not_dead(s):
        return not s["dead"] and s["n_success"] > 0

    eligible = {r: s for r, s in route_stats.items()
                if not_dead(s) and s["success_rate"] >= 0.9 and s["honest_tokens"] is True}
    relaxed_reason = None
    pool = eligible
    if not pool:
        pool = {r: s for r, s in route_stats.items() if not_dead(s) and s["honest_tokens"] is True}
        relaxed_reason = "no route reached success>=9/10 with honest tokens; relaxed success threshold"
    if not pool:
        pool = {r: s for r, s in route_stats.items() if not_dead(s)}
        relaxed_reason = "no honest-token route available at all; relaxed honesty filter too"
    if not pool:
        return {"chosen_route": None, "rule_trace": "no viable (non-dead, successful) route found",
                "relaxed_reason": "all routes dead or 0/10"}

    def sort_key(item):
        _, s = item
        cost = s["cost_per_call"] if s["cost_per_call"] is not None else float("inf")
        latency = s["latency_median_s"] if s["latency_median_s"] is not None else float("inf")
        return (cost, latency)

    chosen_route, chosen_stats = min(pool.items(), key=sort_key)
    trace = (f"eligible={sorted(pool.keys())}; picked min cost/call="
             f"{chosen_stats['cost_per_call']!r} ({chosen_stats['cost_source']}), "
             f"tie-break latency_median_s={chosen_stats['latency_median_s']!r}")
    if relaxed_reason:
        trace = f"RELAXED ({relaxed_reason}) -- {trace}"
    return {"chosen_route": chosen_route, "rule_trace": trace, "relaxed_reason": relaxed_reason}


def _route_extra_body(route: str, route_stats: dict[str, dict]) -> dict | None:
    if route == "auto":
        variant = route_stats.get("auto", {}).get("auto_variant")
        return None if variant == "no_extra_body" else {"provider": "auto"}
    return {"provider": route}


def probe_model(model: str, routes: list[str], n: int, sleep_s: float, out_dir: Path) -> dict:
    route_stats: dict[str, dict] = {}
    raw_calls: dict[str, list[dict]] = {}
    for route in routes:
        calls, dead, auto_variant = sweep_route(model, route, n, sleep_s)
        raw_calls[route] = calls
        route_stats[route] = aggregate_route(model, calls, dead, auto_variant)

    selection = select_route(route_stats)
    chosen = selection.get("chosen_route")
    temp0_check = None
    if chosen:
        extra_body = _route_extra_body(chosen, route_stats)
        res = call_once(model, extra_body=extra_body, temperature=0.0)
        temp0_check = {
            "route": chosen, "extra_body": extra_body, "ok": res["ok"],
            "error_class": res.get("error_class"), "error_message": res.get("error_message"),
        }

    output = {
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_per_route": n,
        "sleep_s": sleep_s,
        "routes_requested": routes,
        "routes": {route: {**route_stats[route], "calls": raw_calls[route]} for route in routes},
        "selection": selection,
        "temp0_check": temp0_check,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    basename = model.split("/")[-1]
    out_path = out_dir / f"{basename}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def _fmt_cost(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"${v:.2e}"


def _fmt_s(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f}s"


def generate_summary(out_dir: Path) -> tuple[str, float, float]:
    """Rebuild triage/summary.md from every <basename>.json present in out_dir.

    Returns (markdown_text, total_real_cost_usd, total_estimated_cost_usd) so
    callers can print/verify the budget without re-parsing the file.
    """
    json_files = sorted(out_dir.glob("*.json"))
    lines = ["# Provider triage summary — 2026-07-05-model-comparison", "",
             "Generated by `scripts/probe_providers.py`. Route × "
             "{success, med latency, p90, median prompt-tokens, cost/call, verdict}; "
             "chosen route + rule trace per model.", ""]

    total_real = 0.0
    total_estimated = 0.0
    total_calls = 0

    for jf in json_files:
        data = json.loads(jf.read_text(encoding="utf-8"))
        model = data["model"]
        lines.append(f"## {model}")
        lines.append("")
        lines.append("| Route | Success | Med latency | P90 | Median ptok | Cost/call | Verdict |")
        lines.append("|---|---|---|---|---|---|---|")
        for route in data["routes_requested"]:
            s = data["routes"][route]
            success_str = f"{s['n_success']}/{s['n_calls']}"
            cost_str = _fmt_cost(s["cost_per_call"])
            if s["cost_source"] == "estimated" and s["cost_per_call"] is not None:
                cost_str += " (est.)"
            ptok_str = "n/a" if s["prompt_tokens_median"] is None else f"{s['prompt_tokens_median']:.0f}"
            lines.append(f"| `{route}` | {success_str} | {_fmt_s(s['latency_median_s'])} | "
                          f"{_fmt_s(s['latency_p90_s'])} | {ptok_str} | {cost_str} | {s['verdict']} |")
            for c in s["calls"]:
                total_calls += 1
                if c["cost_usd"] is not None:
                    total_real += c["cost_usd"]
                elif c["ok"] and model in PRICE_TABLE and c["prompt_tokens"] is not None:
                    price_p, price_c = PRICE_TABLE[model]
                    total_estimated += (c["prompt_tokens"] * price_p +
                                        (c["completion_tokens"] or 0) * price_c) / 1_000_000
        lines.append("")
        sel = data["selection"]
        lines.append(f"**Chosen route:** `{sel.get('chosen_route')}` — {sel.get('rule_trace')}")
        if model == "openai/gpt-5.5":
            lines.append("")
            lines.append("Owner framing: \"самый дешёвый стабильный\" (cheapest stable) — the rule above "
                          "already encodes that: success>=9/10 is the stability gate, then min cost/call "
                          "picks the cheapest among the stable routes.")
        if data.get("temp0_check"):
            t0 = data["temp0_check"]
            verdict = "accepted" if t0["ok"] else f"REJECTED ({t0['error_class']}: {t0['error_message']})"
            lines.append("")
            lines.append(f"`temperature=0` on chosen route: **{verdict}**")
        lines.append("")

    lines.append("## Total triage spend")
    lines.append("")
    lines.append(f"- Real (surfaced `cost_usd`, summed): ${total_real:.6f}")
    lines.append(f"- Estimated (token-price catalog, calls with no surfaced cost): ${total_estimated:.6f}")
    lines.append(f"- **Total: ${total_real + total_estimated:.6f}** across {total_calls} calls "
                  f"(budget ceiling: $2)")
    lines.append("")

    markdown = "\n".join(lines)
    (out_dir / "summary.md").write_text(markdown, encoding="utf-8")
    return markdown, total_real, total_estimated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", nargs="+", default=[],
                         help="One or more model ids (e.g. openai/gpt-5.5). Each runs in its own "
                              "thread, concurrently with the others.")
    parser.add_argument("--routes", default=None,
                         help="Comma-separated route list (default: auto,provider-1..provider-12).")
    parser.add_argument("--n", type=int, default=10, help="Calls per live route.")
    parser.add_argument("--sleep-s", type=float, default=0.2, help="Delay between calls in a sweep.")
    parser.add_argument("--out-dir", default="docs/experiments/2026-07-05-model-comparison/triage",
                         help="Output directory for <basename>.json and summary.md.")
    parser.add_argument("--summary-only", action="store_true",
                         help="Skip probing; just rebuild summary.md from existing JSON files.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)

    if args.summary_only:
        if not args.model:
            _, real, est = generate_summary(out_dir)
            print(f"summary.md rebuilt from {out_dir}. spend: real=${real:.6f} est=${est:.6f}")
            return

    if not args.model:
        parser.error("--model is required unless --summary-only is used without --model")

    routes = (args.routes.split(",") if args.routes else DEFAULT_ROUTES)
    routes = [r.strip() for r in routes if r.strip()]

    _api_key()  # fail fast if missing, before spawning threads

    print(f"Probing {len(args.model)} model(s) x {len(routes)} routes x up to {args.n} calls each, "
          f"concurrently (1 thread/model): {args.model}", file=sys.stderr)

    results = {}
    with ThreadPoolExecutor(max_workers=len(args.model)) as pool:
        futures = {pool.submit(probe_model, model, routes, args.n, args.sleep_s, out_dir): model
                   for model in args.model}
        for fut in as_completed(futures):
            model = futures[fut]
            try:
                results[model] = fut.result()
                sel = results[model]["selection"]
                print(f"[{model}] chosen_route={sel.get('chosen_route')}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 — surface, don't let one model kill the pool
                print(f"[{model}] FAILED: {exc}", file=sys.stderr)

    _, real, est = generate_summary(out_dir)
    print(f"summary.md written to {out_dir}/summary.md. spend so far: real=${real:.6f} est=${est:.6f}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
