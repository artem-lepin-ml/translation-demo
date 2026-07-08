"""Minimal realistic judge-route probe for 4 candidate cloud judge models
against CloseRouter, using the vendored accuracy.md prompt + real BOUQUET
paragraph pairs. Reuses palimpsest.llm.client.LLMClient / LLMConfig from the
top-level repo (src/palimpsest/llm/client.py) — sync OpenAI-compatible
wrapper, already extracts reasoning_tokens + cost_usd/cost from usage.

NEVER prints the API key. Retries transient errors up to 3x (LLMClient's
own complete_retrying: attempts=3, backoff 1/3/9s) before declaring a route
broken.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/user/translation-demo/src")
from palimpsest.llm.client import LLMClient, LLMConfig  # noqa: E402

REPO = Path("/home/user/translation-demo")
GSE = REPO / "external/gse-translation"
OUT_DIR = Path("/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad")

BASE_URL = os.environ["OPENROUTER_BASE_URL"]
API_KEY = os.environ["OPENROUTER_API_KEY"]  # never printed/logged

ACCURACY_PROMPT = (GSE / "prompts/03_scoring/v1/accuracy.md").read_text(encoding="utf-8")

USER_MSG_TEMPLATE = (
    "**Source text (Russian)** — for reference when identifying recurring"
    " elements:\n{}\n\n**Translation (English)** — this is what you are evaluating:\n{}"
)

# (paragraph_id, system_dir) — median-length (id 72, qwen refined) and a
# harder dialogue paragraph (id 178, qwen refined — keeps Cyrillic speaker
# tags untranslated, a genuine accuracy issue) so the judge has something
# real to flag, not a trivial clean pair.
CASES = [
    (72, "qwen-27b-bouquet-refined"),
    (178, "qwen-27b-bouquet-refined"),
]

SRC = json.loads((GSE / "data/bouquet/bouquet_original.json").read_text(encoding="utf-8"))


def load_translation(system_dir: str) -> list[str]:
    p = GSE / "data/bouquet/translation" / system_dir / "translation.json"
    return json.loads(p.read_text(encoding="utf-8"))


# model_key -> (model_id, regime)
MODELS = {
    "opus-4.8": "anthropic/claude-opus-4.8",
    "gpt-5.5": "openai/gpt-5.5",
    "gemini-3.1-pro": "google/gemini-3.1-pro-preview",
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
}

FRONTIER = {"opus-4.8", "gpt-5.5", "gemini-3.1-pro"}


def build_config(model_key: str, model_id: str) -> LLMConfig:
    if model_key in FRONTIER:
        # reasoning ON, default effort, NO temperature sent.
        # gemini-3.1-pro-preview 400s on response_format={"type":"json_object"}
        # (isolated via a 3-variant diagnostic: plain / response_format-only /
        # reasoning-only — only response_format triggers "invalid_request" from
        # the Google upstream; its /models supported_parameters list confirms
        # this: only max_output_tokens/max_tokens/stream are declared, no
        # response_format, no reasoning). It also reasons by default with no
        # reasoning param at all (187 reasoning_tokens on a 2-word ping) — so
        # for gemini we drop response_format and rely on the prompt's own
        # "respond with valid JSON only" instruction (already in accuracy.md).
        if model_key == "gemini-3.1-pro":
            extra_body = {"reasoning": {"enabled": True}}
        else:
            extra_body = {
                "reasoning": {"enabled": True},
                "response_format": {"type": "json_object"},
            }
        return LLMConfig(
            model=model_id, base_url=BASE_URL, api_key=API_KEY,
            temperature=None, max_tokens=8000, extra_body=extra_body, timeout=120,
        )
    else:
        # deepseek-v4-flash: temperature=0, reasoning explicitly OFF, auto route
        # (no provider pin — verifying auto works per task note about
        # provider-9 pin being incompatible with json_object).
        extra_body = {
            "reasoning": {"enabled": False},
            "response_format": {"type": "json_object"},
        }
        return LLMConfig(
            model=model_id, base_url=BASE_URL, api_key=API_KEY,
            temperature=0.0, max_tokens=8000, extra_body=extra_body, timeout=120,
        )


def run_one(model_key: str, model_id: str, paragraph_id: int, system_dir: str) -> dict:
    translations = load_translation(system_dir)
    source = SRC[paragraph_id]
    translated = translations[paragraph_id]
    user_msg = USER_MSG_TEMPLATE.format(source, translated)

    cfg = build_config(model_key, model_id)
    client = LLMClient(cfg)

    t0 = time.monotonic()
    record: dict = {
        "model_key": model_key, "model_id": model_id,
        "paragraph_id": paragraph_id, "system_dir": system_dir,
        "regime": "reasoning_on_default_no_temp" if model_key in FRONTIER
                  else "temp0_reasoning_off_auto",
    }
    try:
        result = client.complete_retrying(system=ACCURACY_PROMPT, user=user_msg, attempts=3)
        latency = time.monotonic() - t0
        record["ok"] = True
        record["latency_s"] = latency
        record["prompt_tokens"] = result.usage.prompt_tokens
        record["completion_tokens"] = result.usage.completion_tokens
        record["reasoning_tokens"] = result.usage.reasoning_tokens
        record["cost_usd_surfaced"] = result.usage.cost_usd
        record["raw_content"] = result.content
        # Try to parse JSON + validate schema like the vendored scorer would.
        content = result.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            parsed = json.loads(content)
            record["json_parse_ok"] = True
            record["final_score"] = parsed.get("final_score")
            record["has_expected_keys"] = all(
                k in parsed for k in ("identified_issues", "criteria_assessment", "summary", "final_score")
            )
        except json.JSONDecodeError as exc:
            record["json_parse_ok"] = False
            record["json_parse_error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 — classify, never crash the probe
        latency = time.monotonic() - t0
        record["ok"] = False
        record["latency_s"] = latency
        record["error_class"] = type(exc).__name__
        status = getattr(exc, "status_code", None)
        record["http_status"] = status
        msg = str(exc)
        if API_KEY in msg:
            msg = msg.replace(API_KEY, "***REDACTED***")
        record["error_message"] = msg[:1000]
    return record


def main() -> None:
    only = sys.argv[1:] or list(MODELS.keys())
    results = []
    for model_key, model_id in MODELS.items():
        if model_key not in only:
            continue
        for paragraph_id, system_dir in CASES:
            print(f"probing {model_key} ({model_id}) paragraph={paragraph_id} system={system_dir}...",
                  file=sys.stderr, flush=True)
            rec = run_one(model_key, model_id, paragraph_id, system_dir)
            status = "OK" if rec.get("ok") else f"FAIL {rec.get('error_class')}"
            print(f"  -> {status} latency={rec.get('latency_s', 0):.1f}s "
                  f"ptok={rec.get('prompt_tokens')} ctok={rec.get('completion_tokens')} "
                  f"reasoning_tok={rec.get('reasoning_tokens')} cost_usd={rec.get('cost_usd_surfaced')}",
                  file=sys.stderr, flush=True)
            results.append(rec)

    suffix = "_".join(only) if only != list(MODELS.keys()) else "raw"
    out_path = OUT_DIR / f"probe_results_{suffix}.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
