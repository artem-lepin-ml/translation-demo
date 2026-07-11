#!/usr/bin/env python3
"""Provider sweep for anthropic/claude-opus-4.8 on CloseRouter -- catalog-driven,
cheap (1-2 calls/provider), records padding factor + reasoning engagement."""
import sys, os, json, time
from pathlib import Path
ROOT = Path("/home/user/translation-demo")
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from palimpsest.llm.client import LLMClient, LLMConfig
from palimpsest.terminology.extract import DEFAULT_NER_PROMPT
from palimpsest.terminology.evaluation.tokenize import flatten

base_url = os.environ["OPENROUTER_BASE_URL"]
api_key = os.environ["OPENROUTER_API_KEY"]
model = "anthropic/claude-opus-4.8"

html_path = ROOT / "data/eval/wiki/pages/KV35YL.html"
article_text = flatten(html_path.read_text(encoding="utf-8"))
paragraphs = [p for p in article_text.split("\n") if len(p.split()) > 60]
paragraph = paragraphs[0]
prompt = DEFAULT_NER_PROMPT.replace("{{source}}", paragraph)
BASELINE_PTOK = 1858  # auto, confirmed clean, matches 2026-07-08 doc figure

CATALOG = {
    # name: (supports_reasoning_effort per /providers catalog, extra_body base)
    "auto":       {"reasoning_effort_supported": False, "extra_body": {}},
    "provider-2": {"reasoning_effort_supported": True,  "extra_body": {"provider": "provider-2"}},
    "provider-4": {"reasoning_effort_supported": False, "extra_body": {"provider": "provider-4"}},
    "provider-5": {"reasoning_effort_supported": True,  "extra_body": {"provider": "provider-5"}},
    "provider-8": {"reasoning_effort_supported": True,  "extra_body": {"provider": "provider-8"}},
    "provider-9": {"reasoning_effort_supported": False, "extra_body": {"provider": "provider-9"}},
    "provider-10":{"reasoning_effort_supported": True,  "extra_body": {"provider": "provider-10"}},
}
NEGATIVE_CONTROL = ["provider-3", "provider-6"]  # history-seen IDs, not in this model's catalog

def call(extra_body, max_tokens=800):
    client = LLMClient(LLMConfig(model=model, base_url=base_url, api_key=api_key,
                                  temperature=0, max_tokens=max_tokens, extra_body=extra_body or None))
    t0 = time.monotonic()
    try:
        result = client.complete(system="", user=prompt)
        lat = time.monotonic() - t0
        u = result.usage
        return {"ok": True, "latency_s": round(lat, 2), "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens, "reasoning_tokens": u.reasoning_tokens,
                "cost_usd": u.cost_usd, "content_preview": result.content[:120]}
    except Exception as exc:
        lat = time.monotonic() - t0
        return {"ok": False, "latency_s": round(lat, 2), "error": f"{type(exc).__name__}: {str(exc)[:200]}"}

results = {}

for name, meta in CATALOG.items():
    eb = dict(meta["extra_body"])
    eb["reasoning_effort"] = "high"
    r1 = call(eb)
    entry = {"catalog_reasoning_supported": meta["reasoning_effort_supported"],
              "call_reasoning_effort_flat": r1}
    if r1.get("ok") and r1.get("reasoning_tokens", 0) == 0 and meta["reasoning_effort_supported"]:
        eb2 = dict(meta["extra_body"])
        eb2["thinking"] = {"type": "enabled", "budget_tokens": 4000}
        r2 = call(eb2)
        entry["call_thinking_native"] = r2
    results[name] = entry
    print(f"[{name}] done", file=sys.stderr)

for name in NEGATIVE_CONTROL:
    r = call({"provider": name, "reasoning_effort": "high"}, max_tokens=50)
    results[name] = {"negative_control": True, "call": r}
    print(f"[{name}] (negative control) done", file=sys.stderr)

out_path = Path("/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/provider_sweep_results.json")
out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"written -> {out_path}", file=sys.stderr)

# Cost summary
total_real = 0.0
n_calls = 0
for name, entry in results.items():
    for key in ("call_reasoning_effort_flat", "call_thinking_native", "call"):
        c = entry.get(key)
        if c:
            n_calls += 1
            if c.get("cost_usd"):
                total_real += c["cost_usd"]
print(f"n_calls={n_calls} total_real_cost_usd={total_real}", file=sys.stderr)
