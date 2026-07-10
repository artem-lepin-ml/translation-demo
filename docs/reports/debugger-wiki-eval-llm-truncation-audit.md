# Report — LLM generation params & response truncation audit (NER+Wikidata-grounding eval path)

## Scope

Read-only audit (no code changes) of `scripts/wiki_eval.py` + `src/palimpsest/llm/client.py`
and the NER+grounding eval call path, requested to answer six questions for an
experiment-redo spec: (1) every LLM call site with its params, (2) what happens to a
truncated (`finish_reason=length`) response at each site, (3) data evidence for
truncation from `budget_calls.jsonl` and `reports/terminology/wiki-eval/*/111/*/` run
artifacts, (4) whether the actual serving provider is recorded per call, (5) the
deepseek-v4-flash reasoning-tokens-vs-`max_tokens=512` interaction, and (6) a
recommendation table (proposed `max_tokens`/temperature per role, provider-pinning
policy for CloseRouter vs standard OpenRouter). Two premises in the task were checked
and corrected (see Decisions & rationale).

## Files changed

None — read-only audit. This report is the only file written.

## Decisions & rationale

Full findings (already delivered to the orchestrator as the primary answer; reproduced
here for the record per the reporting schema):

**Premise corrections found before answering:**
- `budget_calls.jsonl` (repo root) is **not** wiki-eval data — it's the demo webapp's
  `BudgetGuard` log (`src/palimpsest/webapp/budget.py:27-28`), synthetic `/evaluate`
  test fixture rows (`model: "m"`), zero rows related to `wiki_eval.py`/NER/grounding.
- **No wiki-eval run exists for 2026-07-10 ~06:00-06:40Z.** Per
  `docs/reports/ml-engineer-deepseek-backfill.md`, the 108-paragraph deepseek backfill
  was blocked on a CloseRouter route-health gate (`502 origin_bad_gateway`,
  05:31-05:49Z) and never executed; `pred.jsonl`/`meta.json` for the deepseek run are
  untouched since 2026-07-08. That report also documents (informationally only, not
  acted on by this audit) an unrelated chain of in-band messages attempting to redirect
  that backfill to an unverified OpenRouter fallback key — all declined by the sessions
  involved, zero extra spend; not something this read-only audit needed to act on.

**1. Call sites** (model / system vs user / temperature / max_tokens / extra_body / retry):
- **Extraction** — `_build_extract_fn`→`extractor()`, `scripts/wiki_eval.py:439-463`.
  `route["extract_model"]` (default `google/gemini-3.1-flash-lite`); system=`""`, user=
  `DEFAULT_NER_PROMPT` (`terminology/extract.py:24`); `temperature=0` hardcoded
  (`wiki_eval.py:448`); `max_tokens` **not set → `LLMConfig` default 4096**
  (`llm/client.py:46`); `extra_body` = `{"provider": <pin>}` or CLI override
  (`wiki_eval.py:108-116`); retry via `_complete_with_slot` (`:363-396`), 6 attempts,
  backoff 1/3/9/20/40/60s (`RESILIENT_ATTEMPTS`/`RESILIENT_BACKOFF`, `:165-166`),
  transient-only.
- **Grounding judge** — `_build_judge`→`_call()`, `wiki_eval.py:597-625`. Same model by
  default; system=`JUDGE_SYSTEM_PROMPT`/`JUDGE_REASK_SYSTEM_PROMPT` (`:547-555`), user=
  formatted judge prompt; `temperature=0` hardcoded (`:606`); **`max_tokens=512`**
  (`JUDGE_MAX_TOKENS`, `:72`); same `extra_body` as extraction — applied to **both roles
  equally**, not independently configurable (`:87-97,116`); same 6-attempt retry plus
  one JSON-parse re-ask.
- Sibling (not part of `wiki_eval.py`'s run path): `scripts/term_pipeline.py:195`
  `cmd_extract`, same `DEFAULT_NER_PROMPT`, `temperature=0`, no `max_tokens` override
  (4096 default), one manual retry only if surfaces are empty, no transient handling.
- No call site anywhere sets `response_format`.

**2. Truncation handling** — `finish_reason` is **never read anywhere** in this
codebase (`client.py:108-123` discards it; grep confirms zero real reads outside a
fake `"stop"/"empty"` inference in `term_pipeline.py:224`). Two divergent silent paths:
  - **Extraction**: truncated/malformed JSON → `parse_surfaces()`
    (`extract.py:110-133`) → `JSONDecodeError` caught → returns `[]`, **no exception, no
    log, no counter** — indistinguishable from a legitimate zero-mention paragraph.
    This is the dangerous silent-recall-loss path.
  - **Judge**: truncated JSON → one corrective re-ask → still fails →
    `tracker.record_failed_judge_call()` fires, exception propagates →
    `LabelFirstGrounding.ground()` (`grounding/label_first.py:164-175`) catches it
    terminally as `resolved_by="judge_unavailable"` — semi-visible, but this bucket also
    catches network failures and other malformed-response cases, so truncation is not
    distinguishable post-hoc from the stored data alone.

**3. Data evidence** — No wiki-eval run artifact inspected (deepseek/gemini/qwen/gpt-5.4
runs under `reports/terminology/wiki-eval/`) persists per-call `finish_reason`,
`completion_tokens`, or provider; the in-memory `Usage`/`LLMResult` data is used only
for cost estimation then discarded (`wiki_eval.py:458-462,620-624`) — so "count
completion_tokens>=4000 events per run" is **not computable** from any stored artifact;
that instrumentation doesn't exist for this script (unlike `probe_providers.py`,
`bouquet_judge_rerun.py`, `rebuild_demo.py`, `eval_grounding.py`, which do capture it).
Best available proxy, `resolved_by` distribution in `pred.jsonl`: deepseek-v4-flash
`judge_unavailable`=457/16931=2.70% (`n_failed_judge_calls=238/4785` in `meta.json`)
vs gemini-3.1-flash-lite `judge_unavailable`=88/20960=0.42% under an identical
`provider-9`/512-token setup — 6.4x higher on the reasoning-capable model, consistent
with (not proof of) truncation. Confound flagged: `docs/known_issues.md:56` documents a
separate, already-known outage/checkpoint bug that also inflates `judge_unavailable`
counts (qwen3.7-plus, 735 vs 12 in one slice) — the stored data cannot separate these
causes from truncation, which is itself the headline observability gap.

**4. Provider recording** — **No**, only the requested/pinned provider is recorded
(`meta.json`'s run-level `"provider"` key), never the actual serving provider per call.
`_extract_usage()` (`client.py:58-74`) never reads a top-level `resp.provider`/
`resp.model_extra`; only `usage.model_extra` is read (for `cost`/`cost_usd`
passthrough). Technically retrievable via the SDK's permissive pydantic model if the
gateway echoes such a field, but nothing in this codebase does so today.

**5. Reasoning-tokens interaction** — Confirmed sharp edge. On the `provider-9` pin,
deepseek-v4-flash reasons by default and `extra_body={"reasoning":{"enabled":false}}`
suppresses it (verified 19/19, `docs/known_issues.md:129-136`); on route `auto` the same
flag does **not** work (`known_issues.md:144-152`; direct evidence in
`docs/experiments/2026-07-08-judge-probe/raw/probe_results_merged.json`, regime
`temp0_reasoning_off_auto`: 2165/2565 completion tokens — 84% — spent on reasoning
despite the flag). The actual deepseek wiki-eval run (`2026-07-05T23-35-52Z`) used the
`provider-9` pin with **no `--extra-body` override** (no evidence of the flag in
`docs/experiments/2026-07-05-model-comparison/SESSION-LOG.md`/`TASK.md`; `meta.json`
never records the effective `extra_body` used — a real gap), and it **predates** the
2026-07-07 smoke that discovered the fix — so it most likely ran with default reasoning
ON at a 512-token judge cap. `scripts/probe_providers.py`'s route-selection triage that
picked `provider-9` never checked `finish_reason`/`reasoning_tokens`
(`call_once()`, `:84-109`); its own `max_tokens=8` probes for deepseek hit the cap on
every single call (`completion_tokens_median=8`, `triage/deepseek-v4-flash.json`) and
were scored as normal successes — origin of the blind spot.
`webapp/model_matrix.py:37-39` independently documents the general trap ("on reasoning
models it truncates the JSON answer and doubles cost").

**6. Recommendation** — delivered as a table to the orchestrator (proposed
`max_tokens`/temperature per role with caveats; provider-pinning risk flagged: current
`{"provider": "provider-9"}` is CloseRouter's own numbered-pin convention, not standard
OpenRouter's `provider:{order,only,allow_fallbacks}` schema — mechanism (extra_body
passthrough) transfers, payload shape does not; needs a live probe against real
openrouter.ai before finalizing a shared policy). Flagged the owner's T=0.7 proposal as
conflicting with this project's own documented `docs/paper/paper-state.md:137`
("all T=0, thinking off") and with `wiki_eval.py`'s hardcoded `temperature=0` literals
(not currently CLI-configurable) — needs owner clarification on whether "the paper"
means this project's paper or an external one before implementing.

## Open questions

- Was the deepseek wiki-eval run's `judge_unavailable` rate (2.70%, 6.4x gemini's)
  actually dominated by reasoning-token truncation, or partly by the same class of
  network/checkpoint issue documented for qwen3.7-plus? Not answerable from stored data
  — requires the observability fix (log `finish_reason`/`completion_tokens`/
  `reasoning_tokens`/effective `extra_body` per call) before a redo run, then compare.
- Does `gemini-3.1-flash-lite`'s API accept or silently ignore `temperature=0.7`? Not
  verified in this repo (sibling `gemini-3.5-flash` row in `model_matrix.py:53` is
  marked `supports_temperature=False`) — needs a live probe.
- Does `extra_body={"provider": {"order": [...]}}` (standard OpenRouter schema) actually
  work through this same OpenAI-compat client against `openrouter.ai` (not
  CloseRouter)? Not tested anywhere in this repo — needs a live probe before the redo
  spec commits to a provider-pinning policy that's meant to work on both gateways.
- Which paper's "declared vLLM settings" specify T=0.7 — this project's own
  (`docs/paper/`, which documents T=0) or an external one being replicated? Owner
  clarification needed.

## NOT done

- No live LLM calls were made (pure static/data audit) — the finish_reason/reasoning-
  token claims are corroborated from existing repo evidence (`known_issues.md`, prior
  agent probe reports, `probe_results_merged.json`), not re-verified live in this
  session.
- No code changes — extract/judge `max_tokens`, temperature, `extra_body` decoupling,
  and per-call observability logging (finish_reason/completion_tokens/reasoning_tokens/
  effective extra_body into `meta.json`) are all recommended but **not implemented**.
- Did not attempt to unblock or re-run the blocked deepseek backfill (out of scope —
  that's a separate, already-in-flight task per `ml-engineer-deepseek-backfill.md`).
- Did not probe standard openrouter.ai directly to confirm/deny the
  `provider.order`/`provider.only` schema question in §6 — flagged as an open question,
  not resolved.
