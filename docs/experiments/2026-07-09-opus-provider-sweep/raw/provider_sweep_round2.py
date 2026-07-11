#!/usr/bin/env python3
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

def call(extra_body, temperature, max_tokens=800):
    client = LLMClient(LLMConfig(model=model, base_url=base_url, api_key=api_key,
                                  temperature=temperature, max_tokens=max_tokens, extra_body=extra_body or None))
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
        return {"ok": False, "latency_s": round(lat, 2), "error": f"{type(exc).__name__}: {str(exc)[:250]}"}

results = {}

# Hypothesis: thinking/reasoning_effort conflicts with an explicit temperature
# (Anthropic's real extended-thinking API requires temperature unset/default).
# Retest provider-2 and provider-10 with temperature=None (omitted).
for name in ["provider-2", "provider-10"]:
    eb_flat = {"provider": name, "reasoning_effort": "high"}
    eb_thinking = {"provider": name, "thinking": {"type": "enabled", "budget_tokens": 4000}}
    results[f"{name}__reasoning_effort__temp-none"] = call(eb_flat, temperature=None)
    results[f"{name}__thinking__temp-none"] = call(eb_thinking, temperature=None)
    print(f"[{name}] temp=None variants done", file=sys.stderr)

# Retry the two transient failures once, also with temperature=None this time
# (covers both "was it just flaky" and "was it the temperature conflict").
for name in ["provider-5", "provider-8"]:
    eb_flat = {"provider": name, "reasoning_effort": "high"}
    results[f"{name}__reasoning_effort__temp-none__retry"] = call(eb_flat, temperature=None)
    print(f"[{name}] retry done", file=sys.stderr)

out_path = Path("/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/provider_sweep_round2_results.json")
out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"written -> {out_path}", file=sys.stderr)
