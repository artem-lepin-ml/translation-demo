# Smoke: deepseek-v4-flash via CloseRouter on Danil's vendored pipeline (2026-07-07)

Live smoke test from the cloud session (spec [2026-07-07-wiki-llm-judge-eval.md](../superpowers/specs/2026-07-07-wiki-llm-judge-eval.md)
§4 Ф-1 item 3). Code: `external/gse-translation` (read-only, untouched); env: `uv sync` from the vendored
`uv.lock` (54 packages, clean). 32 real API calls, total spend **$0.0052**.

## Results

- **Translate (Smoke A):** 10/10 real wiki paragraphs (from cached corpus HTML) via Danil's
  `system_universal.md` + `user.md` prompt convention, T=0.3, `max_tokens=2048`,
  `extra_body={"provider":"provider-9","reasoning":{"enabled":false}}`. Mean latency 3.58 s (2.31–5.09),
  26 608 prompt / 1 335 completion tokens, `reasoning_tokens=0` on all calls, cost $0.0012.
- **Judge mechanics (Smoke B):** 3 translations × 3 universal criteria via his `score_paragraph()` →
  **9/9 parsed** (zero retries, zero `parse_failures`); `final_score` valid ints 8–10; `identified_issues`
  schema exactly as the spec expects. Cost $0.0040 (criterion system prompts are ~2.5–3.3k tokens each).

## Findings (feed the sr004 runbook)

1. **deepseek-v4-flash reasons BY DEFAULT on provider-9.** At `max_tokens=8` all tokens went to reasoning
   with empty content (`finish_reason=length`); 26/44 reasoning tokens at 64/256. Reasoning bills against
   `max_tokens`. Fix, verified on 19/19 calls: `extra_body: {reasoning: {enabled: false}}`. The spec v3's
   earlier "проба подтверждает reasoning_tokens==0" was a plan, not a fact — now it is a fact, WITH the flag.
2. **`provider-9` pin is incompatible with `response_format=json_object`** on this model: 400 Bad Request
   from the upstream, isolated by a 3-way diagnostic (json_object alone OK; reasoning-off alone OK;
   pin alone → 400). For the judge role (J′) use route `auto` (was 10/10 in the 2026-07-05 triage at
   ~equal cost); keep the pin for translation.
3. **UA/403 watchpoint:** Danil's `AsyncOpenAI` sets no `default_headers` (our client pins
   `User-Agent: palimpsest-llm/1.0` against CloseRouter's WAF). No 403 occurred in 32 calls this session —
   not proof the WAF rule is gone; keep the header workaround ready.
4. **Vendored-snapshot-only import gap:** `palimpsest/scoring.py` imports `FactExtractor` from
   `palimpsest.factcheck` at module scope; `factcheck/` is excluded from the vendored copy, so
   `import palimpsest.scoring` fails in the cloud checkout (worked around via a scratchpad stub package).
   Irrelevant on sr004 where the full upstream repo is cloned.

## Config deltas for `models.yaml` entries on sr004

```yaml
deepseek-v4-flash-translate:
  name: deepseek/deepseek-v4-flash
  base_url: ${OPENROUTER_BASE_URL}
  api_key_env: OPENROUTER_API_KEY
  temperature: 0.3
  max_tokens: 2048
  extra_body: { provider: provider-9, reasoning: { enabled: false } }

deepseek-v4-flash-judge:   # J' role only: NO provider pin (json_object + pin -> 400)
  name: deepseek/deepseek-v4-flash
  base_url: ${OPENROUTER_BASE_URL}
  api_key_env: OPENROUTER_API_KEY
  temperature: 0
  max_tokens: 4096
  extra_body: { reasoning: { enabled: false } }
```

Raw artifacts (scratchpad, not committed): `smoke/calls.jsonl`, `smoke/smoke_b_summary.json`,
smoke scripts. Session-scoped; the durable facts are this file + known_issues entries.
