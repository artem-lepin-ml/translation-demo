# Runbook — sr004 local judge + grounding runs (Table A local judges, Table C local rows)

Up-link: [docs/README.md](../README.md). Paper mapping: [docs/paper/paper-state.md](../paper/paper-state.md)
("Table A — LLM-as-a-judge", "Table C — NER + Wikidata grounding"). Grounding eval design:
[docs/stages/wiki-eval.md](../stages/wiki-eval.md). BOUQUET judge runner: [scripts/bouquet_judge_rerun.py](../../scripts/bouquet_judge_rerun.py)
+ [configs/bouquet_judges.yaml](../../configs/bouquet_judges.yaml). Grounding runner: [scripts/wiki_eval.py](../../scripts/wiki_eval.py).

**Status of this document: a runbook, not an execution log.** Authored in a cloud session with no GPU/SSH
access to sr004 — every command is either (a) grounded by reading the actual runner code (argparse
definitions, `_resolve_route`/`build_payload` logic, real historical `meta.json` files from the cloud judges
that already ran) or (b) marked **ASSUMPTION**/**UNVERIFIED** because it depends on the sr004 vLLM build and
was never actually run. Two small code patches this runbook depends on (both in *this* repo, not vendored —
see "Code patches" below) **were written, applied, unit-tested and are part of the same commit as this doc.**

## Scope — what this covers, and how it differs from the Table B runbook

This runbook fills the **3 local rows** two different tables still need:

- **Table A** (LLM-as-a-judge, BOUQUET): re-score the 4 already-vendored BOUQUET translation systems with 3
  new local judges — `Qwen3-4B-Instruct-2507`, `Gemma-3-27B-it`, `Qwen3.6-27B` — T=0, thinking off, prompts
  `v1_core3`. Runner: `scripts/bouquet_judge_rerun.py` (this repo). Owner-locked protocol:
  [paper-state.md](../paper/paper-state.md) "Table A protocol" ("Local/open judges → `temperature=0`,
  thinking OFF").
- **Table C** (NER + Wikidata grounding): run the *same* 3 local models as extractor **and** judge over the
  100-article wiki-v2 corpus, sitelink OFF. Runner: `scripts/wiki_eval.py` (this repo). Canonical row order +
  status: [paper-state.md](../paper/paper-state.md) "Table C" (3 of 6 rows pending, all 3 local).

**This is deliberately a much smaller lift than [docs/stages/translation-eval.md](../stages/translation-eval.md)
(Table B)**: that runbook clones Danil's *separate* upstream repo on sr004 and applies 5 patches to it, because
Table B runs his translate→judge→refine pipeline end to end. Table A/C need none of that — both runners
already live in *this* repo (`scripts/`), and both runners' input data is already committed here too
(`external/gse-translation/data/bouquet/` for Table A — vendored, read-only, untouched; `data/eval/wiki/` for
Table C). **All you need on sr004 is this git branch checked out and a local vLLM server per model** — no
second clone, no patches to a foreign codebase. The one thing genuinely shared with Table B: if its
Qwen3.6-27B server (translation-eval.md's GPU2-3, port 8000, TP=2, kept up continuously for that runbook) is
already running when you get to this runbook's Qwen3.6-27B block, **reuse it** instead of starting a second
instance of the same model — same `base_url`, same `--model` id, zero conflict, half the GPU-hours.

## Prereqs

1. **This branch checked out on sr004** — no separate clone needed (contrast with Table B). Confirm the 2
   input datasets are present: `external/gse-translation/data/bouquet/` (vendored BOUQUET, read-only) and
   `data/eval/wiki/gt.jsonl` (100-article grounding GT, committed) + `data/eval/wiki/pages/` (cached
   article HTML `run` reads from — see [wiki-eval.md Subtleties](../stages/wiki-eval.md#subtleties)).
2. **Python env**: whatever this repo's own `pyproject.toml`/`uv.lock` already pins (not Danil's separate
   `uv sync --extra vllm` — that's Table B's concern). `scripts/bouquet_judge_rerun.py` needs `httpx`,
   `numpy`, `yaml`, optionally `scipy`; `scripts/wiki_eval.py` needs `openai` (for `palimpsest.llm.client`)
   — both already repo dependencies.
3. **vLLM**, installed separately per model as needed (see each model's bring-up block) — this is the one
   thing that genuinely needs the sr004 box; not part of this repo's own `pyproject.toml`.
4. **Env vars, common to every run in this doc**:
   ```bash
   export OPENROUTER_API_KEY=EMPTY     # any non-empty placeholder — vLLM ignores the key value
                                        # unless the server was started with --api-key (none of the
                                        # commands below use it). Never log/print this value regardless
                                        # (.claude/rules/invariants.md) — it's a placeholder here, but
                                        # keep the habit for when OPENROUTER_API_KEY is a real cloud key
                                        # in the same shell session.
   export OPENROUTER_BASE_URL=http://localhost:8000/v1   # bouquet_judge_rerun.py (Table A) still reads
                                        # this env var directly. Repoint it at whichever model's server is
                                        # currently up (this runbook reuses port 8000 for all 3 models,
                                        # sequential bring-up — see next section).
   ```
   **⚠️ 2026-07-10 supersession (spec [2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md)
   Р2/Р12):** `wiki_eval.py` (Table C) no longer reads `OPENROUTER_BASE_URL` or the CloseRouter
   `WIKI_EVAL_PROVIDER`/`CLOSEROUTER_MODEL`/`CLOSEROUTER_PROVIDER` env vars at all — it always goes through
   one standard-OpenRouter-shaped route resolver, and a local server is selected with the explicit
   **`--base-url http://127.0.0.1:8000/v1`** CLI flag on `run`/`ablate` instead of an env var. `OPENROUTER_API_KEY`
   is still required (any non-empty placeholder, same as above) because `_resolve_route` always reads the
   key from that env var name regardless of `--base-url`. See the rewritten Table C section below — the env
   var still applies to Table A's `bouquet_judge_rerun.py` unchanged.

   Both scripts run from the repo root; `wiki_eval.py` needs `PYTHONPATH=src` (or run via `uv run`, which
   picks up `pyproject.toml`'s own path config) — same convention as every other invocation in this repo.

## Why no patch was needed for localhost *routing* (verified by reading the code; Table C part superseded 2026-07-10)

The task brief asked to check whether either runner can point at a local OpenAI-compatible server at all
without a patch. Verified, not assumed:

- **`scripts/bouquet_judge_rerun.py`** (Table A, unchanged): `cmd_run` reads `base_url =
  os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)` unconditionally — `OPENROUTER_BASE_URL` already
  fully overrides the CloseRouter default. No patch needed.
- **`scripts/wiki_eval.py`** (Table C, ⚠️ superseded description — see the 2026-07-10 note above): at the
  time this runbook was first written, `_resolve_route`'s `closerouter` branch read `OPENROUTER_BASE_URL`
  from the environment. That whole CloseRouter-gateway/env-var branching is now retired (spec Р2): the
  current `_resolve_route(model, provider, extra_body, base_url, temperature, top_p, top_k, max_tokens)`
  resolves the base URL from an explicit `--base-url` CLI argument (falling back to the standard
  `https://openrouter.ai/api/v1` when omitted), never from an env var. `--provider auto` still disables
  provider pinning and the served-by gate, same as before — verified via `_resolve_route`'s own docstring
  and `tests/test_wiki_eval_runner.py`.

## Code patches — the *real* gap found: no way to force `thinking OFF` on a local server

Routing works out of the box, but a **second**, separate problem does need a patch: the owner-locked protocol
requires `temperature=0, thinking OFF` for every local judge. `Qwen3-4B-Instruct-2507` and `Gemma-3-27B-it`
are non-thinking models by construction (no chat-template toggle exists for either family) — "thinking off"
is free for them. **`Qwen3.6-27B` is a hybrid-thinking model that reasons by default** unless a request sets
`chat_template_kwargs: {"enable_thinking": false}` — a first-party vLLM OpenAI-server request field (the same
mechanism Danil's `models.yaml` already uses for this exact model, see
[translation-eval.md](../stages/translation-eval.md#models-yaml-deltas)). Neither runner had any way to send
this before this patch:

- `bouquet_judge_rerun.py`'s `build_payload()` only ever sets `temperature`/`reasoning`/`response_format` —
  no generic passthrough field, and its `t0_no_reasoning` regime sends an OpenRouter-specific `reasoning:
  {"enabled": false}` key a raw vLLM server doesn't implement (harmless-if-ignored in vLLM's permissive
  request schema, but semantically wrong for a local model and not the mechanism that actually suppresses
  Qwen3.6-27B's thinking).
- `wiki_eval.py`'s `_resolve_route`'s `closerouter` branch only ever computed `extra_body` as `None` or
  `{"provider": ...}` — no CLI-level way to inject anything else, even though `LLMConfig.extra_body` (the
  field `LLMClient` actually sends) already existed and was already fully wired end to end.

**Minimal patch applied (both in this commit, both unit-tested, no GPU needed to verify the logic):**

1. **`scripts/bouquet_judge_rerun.py`**: added `JudgeSpec.extra_body: dict[str, Any] | None = None` (parsed
   from the YAML entry's `extra_body:` key in `load_judges()`), a new `t0_local` regime (temperature=0, no
   `reasoning` key at all), and an unconditional `if judge.extra_body: payload.update(judge.extra_body)` at
   the end of `build_payload()` — any regime can carry extra fields, not just `t0_local`. The 3 new local
   judge entries in `configs/bouquet_judges.yaml` use `regime: t0_local`; only the `qwen3.6-27b` entry sets
   `extra_body: {chat_template_kwargs: {enable_thinking: false}}`.
2. **`scripts/wiki_eval.py`**: added an `extra_body: dict | None` parameter to `_resolve_route`,
   `_build_extract_fn`, `_build_judge`, `_run_one_config`, and a new `--extra-body <JSON string>` CLI flag on
   both `run` and `ablate` — `_parse_extra_body()` does the `json.loads`, failing loud on malformed JSON
   rather than silently ignoring it. **⚠️ 2026-07-10 semantics change (spec Р3/§4.1 finding 4):** at the time
   this patch was written, a passed `--extra-body` **replaced** the provider-pin default entirely; the
   2026-07-10 rework changed this to a **per-key merge** over the computed defaults (provider pin, reasoning
   shape, `top_k`, `usage.include`) so an unrelated override key no longer silently drops the pin — see
   [wiki-eval.md](../stages/wiki-eval.md) "Design decisions". The `chat_template_kwargs.enable_thinking`
   example below is unaffected either way (it doesn't collide with any default key).

**Verified, live, in this session** (no GPU needed — this is pure request-payload logic):
```
$ uv run python3 -c "
import sys, os
sys.path.insert(0, 'scripts')
os.environ['OPENROUTER_BASE_URL'] = 'http://localhost:8000/v1'
import wiki_eval
route = wiki_eval._resolve_route('Qwen/Qwen3.6-27B', 'auto', {'chat_template_kwargs': {'enable_thinking': False}})
..."
{
  "extract_base_url": "http://localhost:8000/v1",
  "judge_base_url": "http://localhost:8000/v1",
  "extract_extra_body": {"chat_template_kwargs": {"enable_thinking": false}},
  "judge_extra_body": {"chat_template_kwargs": {"enable_thinking": false}}
}
```
Plus `uv run pytest tests/test_wiki_eval_runner.py tests/test_bouquet_judge_rerun.py -q` → **81 passed**, and
the full pre-existing suite (`tests/` minus these two files) → **501 passed**, both run in this session — no
regression from either patch. **NOT verified**: whether vLLM's real OpenAI server actually honors
`chat_template_kwargs.enable_thinking=false` for `Qwen/Qwen3.6-27B` on the sr004-installed vLLM build — that
is exactly what the Ф0 probe below (the `curl` smoke test) checks, on real hardware, before any paid-in-GPU-time
volume.

## vLLM bring-up (3 local models, sequential, one at a time)

The task explicitly allows — and this runbook uses — the simpler **sequential, one-model-at-a-time** bring-up
(unlike Table B's runbook, which needs all 3 servers up *simultaneously* for its own GPU-layout reasons). One
consequence: **every server below binds the same port, `:8000`** — always stop the previous `vllm serve`
process before starting the next one; there's no need for translation-eval.md's 3-distinct-port scheme.

**VRAM assumption (ASSUMPTION, same caveat style as translation-eval.md):** A100 80GB cards, inherited from
that runbook's own precedent of running a 27B model (TranslateGemma) on a single A100 with
`--gpu-memory-utilization 0.90`. Re-check against `nvidia-smi` on sr004 before the Ф0 probe; if the cards are
40GB, `Gemma-3-27B-it` and `Qwen3.6-27B` will need `--tensor-parallel-size 2` instead of the TP=1/TP=2 below.

**`--max-model-len`: raise past 16384 for Table C (⚠️ 2026-07-10 revision, OPEN — not yet re-verified on
hardware).** This runbook originally sized `--max-model-len 16384` for both tables under the old caps
(`bouquet_judge_rerun.py`'s judge `max_tokens=8192`; `wiki_eval.py`'s old extractor default 4096 / judge 512).
Table C's caps changed (spec Р3): `wiki_eval.py --max-tokens` is now **20000 for both roles** (matching the
cloud runs, so local rows are comparable) — 16384 no longer has headroom for prompt + a 20000-token
completion and would truncate every call. **Table A is unaffected** (`bouquet_judge_rerun.py`'s judge cap
stays 8192; 16384 remains correct there). For Table C bring-up, size `--max-model-len` to (prompt tokens,
generously ≤2000 for a paragraph-length NER/judge call) + 20000 + safety margin — e.g. **24576 or 32768**;
confirm against `--help`/actual VRAM on the installed vLLM build before running (this specific number is an
**OPEN item for the owner/operator to confirm on real hardware**, not a verified value).

### 1. Qwen3-4B-Instruct-2507 (non-thinking by construction — no `chat_template_kwargs` needed)

```bash
CUDA_VISIBLE_DEVICES=0 python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-4B-Instruct-2507 \
    --port 8000 \
    --dtype bfloat16 \
    --tensor-parallel-size 1 \
    --max-model-len 16384 \
    --max-num-batched-tokens 16384 \
    --max-num-seqs 512 \
    --gpu-memory-utilization 0.90
```
~4B params, bf16 ≈ 8 GB weights — comfortably fits a single A100 with large headroom for KV cache/batching.

### 2. Gemma-3-27B-it (not a reasoning model — "thinking off" is a no-op for this family; not the same
model as TranslateGemma, see below)

```bash
CUDA_VISIBLE_DEVICES=0 python3 -m vllm.entrypoints.openai.api_server \
    --model google/gemma-3-27b-it \
    --port 8000 \
    --dtype bfloat16 \
    --tensor-parallel-size 1 \
    --max-model-len 16384 \
    --max-num-batched-tokens 16384 \
    --max-num-seqs 512 \
    --gpu-memory-utilization 0.90
```
~27B params, bf16 ≈ 54 GB weights — single A100-80GB per the VRAM assumption above (same size class as
TranslateGemma, which translation-eval.md already ran on one GPU). **Not the same checkpoint as
`Infomaniak-AI/vllm-translategemma-27b-it`** (TranslateGemma, Table B's translation system) — this is the
vanilla Gemma 3 27B instruct release, used here purely as a judge/extractor, a distinct row from
TranslateGemma in every table. No `--reasoning-parser` needed — Gemma 3 has no thinking mode.

### 3. Qwen3.6-27B (hybrid thinking model — needs `chat_template_kwargs.enable_thinking=false` per request)

**Check first**: is translation-eval.md's own Qwen3.6-27B server (GPU2-3, TP=2, port 8000) already up for a
concurrent Table B run? If so, reuse it — skip straight to the Ф0 probe below with the SAME `base_url`.
Otherwise:

```bash
CUDA_VISIBLE_DEVICES=0,1 python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3.6-27B \
    --port 8000 \
    --tensor-parallel-size 2 \
    --dtype bfloat16 \
    --reasoning-parser deepseek_r1 \
    --max-model-len 16384 \
    --max-num-batched-tokens 16384 \
    --max-num-seqs 512 \
    --gpu-memory-utilization 0.90
```
`--tensor-parallel-size 2` mirrors translation-eval.md's own Qwen3.6-27B bring-up (same model, larger context
there but the TP sizing reason is model size, not context length, so it carries over). **`--reasoning-parser
deepseek_r1` is a defensive belt-and-suspenders measure, not the primary thinking-off mechanism** — the
per-request `chat_template_kwargs.enable_thinking: false` (already wired into `configs/bouquet_judges.yaml`'s
`qwen3.6-27b` entry and available via `wiki_eval.py --extra-body`) should mean the model never emits `<think>`
tags in the first place; the parser is only there in case the toggle doesn't fully suppress reasoning on this
vLLM build (same **highest-risk ASSUMPTION** translation-eval.md already flags for this exact model/parser
combination — verify the actual parser name via `--help | grep -A2 reasoning-parser` on the installed build).

## Ф0 probe — per model, before any paid-in-GPU-time volume

1. **Server answers**: `curl http://localhost:8000/v1/models` — confirm the model id in the response matches
   what you'll pass as `router_id`/`--model` below (vLLM validates the request's `"model"` field against
   `--served-model-name`, which defaults to the `--model` HF id verbatim).
2. **Thinking-off actually suppresses `<think>` output (Qwen3.6-27B only)** — the one thing this runbook
   cannot verify without a live server:
   ```bash
   curl -s http://localhost:8000/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "Qwen/Qwen3.6-27B",
       "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
       "temperature": 0,
       "max_tokens": 200,
       "chat_template_kwargs": {"enable_thinking": false}
     }' | python3 -m json.tool
   ```
   Check: `choices[0].message.content` contains no `<think>...</think>` block; if the response has a separate
   `reasoning_content` field, it should be empty/absent. If `<think>` leaks anyway, it is **discoverable, not
   silent** — `bouquet_judge_rerun.py`'s judge JSON parser and `wiki_eval.py`'s judge `_parse()` both retry
   once on unparseable JSON, then log to `parse_failures.jsonl` (BOUQUET) / count via `FailureTracker`
   (wiki-eval) rather than crash — but a high failure rate here is the signal to try a different
   `--reasoning-parser` name before spending the full run's budget.
3. **Structured JSON output**: repeat the call above with `"response_format": {"type": "json_object"}` added
   and a prompt asking for a JSON object — confirms the installed vLLM build's guided-decoding backend accepts
   the flag both runners send by default (`bouquet_judge_rerun.py`'s `_JUDGE_RESPONSE_FORMAT`, always sent
   unless a judge sets `supports_structured_output: false`, which none of the 3 new local entries do).

## Table A — BOUQUET local judges

Pilot gate (5 paragraphs × 4 systems × 3 criteria = 60 calls; `--allow-disabled` is required since the 3 new
entries ship `enabled: false`):
```bash
python scripts/bouquet_judge_rerun.py run --judge qwen3-4b-instruct --pilot 5 --allow-disabled
python scripts/bouquet_judge_rerun.py stats --judge qwen3-4b-instruct
```
Check `reports/bouquet/judges/qwen3-4b-instruct/parse_failures.jsonl` is empty (or near-empty — the runner
already retries once on parse failure before logging), and `stats.json`'s per-criterion `mean` values land in
a plausible 1–10 range (not e.g. all `null` from silent judge_unavailable-style failures).

Full run (198 paragraphs × 4 systems × 3 criteria = 2376 calls, matches the cost-estimate baseline already
used elsewhere in `paper-state.md`) + stats:
```bash
python scripts/bouquet_judge_rerun.py run --judge qwen3-4b-instruct --allow-disabled --concurrency 8
python scripts/bouquet_judge_rerun.py stats --judge qwen3-4b-instruct
```
The run is **idempotent/resumable with no flag needed** — see "Resume/restart semantics" below. Repeat both
commands for `gemma-3-27b-it` and `qwen3.6-27b` (same shape, same model currently serving on `:8000`).

**Expected runtime (ASSUMPTION — no local-vLLM latency measurement exists yet in this session):** 2376 calls
at `--concurrency 8`, local single-A100 generation without network round-trip — likely 20–45 minutes per
judge; measure the pilot's wall-clock (printed to stderr) and extrapolate linearly before committing to the
full run if time is tight.

## Table C — grounding runs (sitelink OFF, protocol v3)

**⚠️ Fully revised 2026-07-10** for the wiki-eval experiment-v2 rework (spec
[2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md) Р12) —
new prompt split, new schema, new transport flags, new scoring. Everything below supersedes this section's
earlier (pre-2026-07-10) commands.

**What changed vs. the pre-rework version of this runbook, all automatic (same code path the cloud runs use,
nothing local-specific to configure):**
- **Prompts**: `extract.NER_SYSTEM_PROMPT` (system) + `extract.ner_user(source)` (user) replace the old
  single-string prompt; judge Role+contract now live in `grounding/label_first.py`'s
  `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` (system) with data-only user. No local-runbook action needed — this
  is the same code the cloud runs exercise. See [wiki-eval.md](../stages/wiki-eval.md) "Prompts".
- **Schema**: extractor output is `{surface, lemma}` — no `category` field.
- **Context**: judge sees the full sentence (`extract.sentence_context`), not a fixed character window.
- **Transport**: `wiki_eval.py` no longer reads `OPENROUTER_BASE_URL`/`WIKI_EVAL_PROVIDER` env vars for Table
  C — point it at the local server with the CLI flag **`--base-url http://127.0.0.1:8000/v1`** (localhost
  loopback IP, not `localhost`, avoids any local DNS-resolution surprises — either works against vLLM's
  default bind, but `127.0.0.1` is the more robust habit). `OPENROUTER_API_KEY` still must be set to any
  non-empty string (vLLM ignores its value) — same as the "Env vars" section above.
- **Sampling — vendor-per-model, NOT a uniform `temperature=0.7`.** The owner's 2026-07-10 decision ("отходим
  от единой 0.7 везде", recorded in the spec's Р3 correction note) supersedes this runbook's original
  `temperature=0.7` row for the local trio too — the cloud rows already moved to per-model vendor-recommended
  sampling (spec Р3), and the local trio must match that principle for the two runs to be comparable. Pass
  each model's own vendor-card sampling via `--temperature`/`--top-p`/`--top-k` (all three flags exist on
  `wiki_eval.py run`/`ablate`); do **not** default them all to 0.7.

  **OPEN — exact per-model values not filled here, confirm before running:**

  | model | temperature | top_p | top_k | source |
  |---|---|---|---|---|
  | `Qwen/Qwen3-4B-Instruct-2507` | *(per HF card — confirm before the run)* | *(per HF card)* | *(per HF card)* | Qwen3-4B-Instruct-2507 model card |
  | `google/gemma-3-27b-it` | *(per HF card — confirm before the run)* | *(per HF card)* | *(per HF card)* | Gemma-3-27B-it model card |
  | `Qwen/Qwen3.6-27B` | *(per HF card — confirm before the run)* | *(per HF card)* | *(per HF card)* | Qwen3.6-27B model card |

  This table is deliberately left unfilled rather than guessed — read each model's own HF card (same
  methodology the spec's §4.6 used for the cloud trio: quote the card's own recommended-sampling sentence
  verbatim in the run's commit/report) before the sr004 session, not invented here.
- **`--max-tokens 20000`** (spec Р3, both roles, matches the cloud rows) replaces the old default
  4096/512 caps — pass it explicitly if the CLI default (`DEFAULT_MAX_TOKENS=20000`) ever changes upstream;
  today it's already the default, so `--max-tokens` can be omitted, but see the `--max-model-len` note above
  the bring-up commands — the local vLLM server itself must have room for a 20000-token completion.
- **Per-call gates apply identically to local runs** (spec Р13/Р14/Р15): a `finish_reason=="length"` reply
  halts the run (`LengthOverflowError`), not just tolerated — size `--max-model-len` generously (see above) so
  a local model's own context window isn't what triggers this. The served-provider-pin gate (Р14) is
  irrelevant for `--provider auto` against a local server — it never fires without a pin.

**Pilot gate — 10 articles, same gate set as the cloud pilot (spec §5.2): `finish_reason=length` count = 0,
`n_extraction_parse_failures` < 1% of paragraphs. No dedicated 10-article `gt.jsonl` subset is committed yet**
(only the older 20-article `data/eval/wiki/gt_v2_sub20.jsonl` exists) — derive a fresh 10-article file from
the first 10 titles of the canonical corpus before running the pilot:
```bash
head -10 data/eval/wiki/titles_v2.txt | cut -f1 > /tmp/pilot10_titles.txt
python scripts/wiki_eval.py build-gt --titles /tmp/pilot10_titles.txt --out data/eval/wiki/gt_pilot10.jsonl
```
(this reuses the already-cached `data/eval/wiki/pages/` HTML — free, no network beyond a cache check.)

```bash
python scripts/wiki_eval.py run \
  --gt data/eval/wiki/gt_pilot10.jsonl \
  --config 111 --no-sitelink \
  --model Qwen/Qwen3-4B-Instruct-2507 --provider auto \
  --base-url http://127.0.0.1:8000/v1 \
  --temperature <per-HF-card> --top-p <per-HF-card> --top-k <per-HF-card> \
  --max-usd 50 --max-judge-calls 30000 \
  --article-workers 6 --llm-workers 8 --wikidata-workers 2
```
For `qwen3.6-27b` only, also add `--extra-body '{"chat_template_kwargs": {"enable_thinking": false}}'` — this
merges per-key over the computed defaults (spec §4.1 finding 4), so it composes safely with the
`--temperature`/`--top-p`/`--top-k` flags above.

**Full run** — same command, `--gt data/eval/wiki/gt.jsonl` (100 articles), same flags otherwise. Note the
run dir path this prints (`reports/terminology/wiki-eval/<model-slug>/111/<run_id>/`) — `model_slug()` turns
e.g. `Qwen/Qwen3-4B-Instruct-2507` + `auto` into `Qwen--Qwen3-4B-Instruct-2507--auto`.
```bash
python scripts/wiki_eval.py run \
  --gt data/eval/wiki/gt.jsonl \
  --config 111 --no-sitelink \
  --model Qwen/Qwen3-4B-Instruct-2507 --provider auto \
  --base-url http://127.0.0.1:8000/v1 \
  --temperature <per-HF-card> --top-p <per-HF-card> --top-k <per-HF-card> \
  --max-usd 50 --max-judge-calls 30000 \
  --article-workers 6 --llm-workers 8 --wikidata-workers 2
```

**Report (protocol v3, offline, no LLM calls)** — recomputes `metrics.json` (set-based document-level
`R_doc`/`P_doc`, named/term split) + `report.html` from the persisted `pred.jsonl`. **`--p3`/label-justified
precision is gone** (deleted along with the mention-level protocol, spec Р9) — `cmd_report` always runs v3:
```bash
python scripts/wiki_eval.py report --gt data/eval/wiki/gt.jsonl \
  --pred reports/terminology/wiki-eval/Qwen--Qwen3-4B-Instruct-2507--auto/111/<run_id>
```
(`--tier` defaults to `data/eval/wiki/tier_assignment.json`, the canonical location — no need to pass it
explicitly unless testing against a different tier file.)

**`--max-usd 50` is deliberately generous, not a real dollar budget** — a local vLLM server reports no
`usage.cost`, so `BudgetGuard` falls back to its `gpt-4o-mini`-list-price estimate purely for display/forecast
purposes. The real spend on a local run is **$0** (GPU-hours only); `--max-usd 50` just keeps that
meaningless estimate from ever tripping the guard's stop condition on a free run.

**Expected runtime (ASSUMPTION):** the cloud `gemini-3.1-flash-lite` full 100-article run (`config 111`, same
flags) took ~2.6h wall-clock at `--article-workers 10 --llm-workers 16` (network-latency-bound); a local
server removes the network round-trip but is generation-throughput-bound on a single A100 instead —
plausibly similar or somewhat faster, roughly 1.5–4 hours per model. Measure the pilot's wall-clock first.

## Resume/restart semantics

- **`bouquet_judge_rerun.py run`**: fully idempotent, no flag needed. `load_existing_keys()` reads
  `scores.jsonl` back on every invocation and skips any `(system, id, criterion)` already present — re-running
  the exact same command after a crash/restart just picks up where it left off. `parse_failures.jsonl` is a
  diagnostic log only, never consulted for resume (absence from `scores.jsonl` is the sole resume signal).
- **`wiki_eval.py run`**: use `--resume <run_dir>` to continue a killed/restarted invocation — reuses the run
  dir and `run_id`, skips articles already in `pred.partial.jsonl` (by title, never re-billed), and seeds a
  fresh `BudgetGuard` from `progress.jsonl`'s last recorded `spent`. Without `--resume`, re-running the same
  `--model`/`--provider`/`--config` starts a **new** run dir (`run_id` = a fresh UTC timestamp) — it does NOT
  auto-resume the way the BOUQUET runner does; you must pass the prior run dir explicitly. See
  [wiki-eval.md's checkpointing note](../stages/wiki-eval.md#subtleties) for the full mechanism.

## What to commit after each run, and the commit-message convention

Matches the exact style already used by the cloud judge/grounding commits on this branch
(`git log --oneline`: `ced45c3`, `6a90dec`, `229529a`, `501c394`, ...):

- **After a BOUQUET judge's full run + stats**: `reports/bouquet/judges/<slug>/{scores.jsonl,parse_failures.jsonl,stats.json}`
  + the regenerated `reports/bouquet/judges/summary.md` (combined across every judge with a `stats.json`) +
  flip that judge's `enabled: false` → `true` in `configs/bouquet_judges.yaml`. Commit message:
  `feat(eval): BOUQUET judge run — <judge-slug> (2376 calls)`.
- **After a grounding model's full run + report**: the whole run dir
  `reports/terminology/wiki-eval/<model-slug>/111/<run_id>/{pred.jsonl,meta.json,metrics.json,report.html}`
  (NOT `pred.partial.jsonl`/`progress.jsonl` — both are deleted/transient once the run finishes cleanly).
  Commit message: `feat(eval): grounding run — <model-slug> (config 111, no-sitelink)`.
- **Never delete a prior partial/pilot run's `scores.jsonl` rows** (`.claude/rules/invariants.md` — judge
  scores are irreproducible; a bad pilot's rows are superseded by the full run overwriting the same keys
  in-place via the resumable-append mechanism, never by deleting the file).
- **Race-proof staging** (this working tree has other agents editing `configs/bouquet_judges.yaml` /
  `scripts/bouquet_judge_rerun.py` concurrently, per the overnight-mission coordination doc): `git status`/
  `git diff` immediately before staging, `git add` only the paths this runbook's run actually touched, never
  `git add -A`.
- **Downstream, not this runbook's job**: updating `docs/paper/paper-state.md`'s "Done"/"In flight" bullets,
  `docs/paper/table-a-judges.tex`/`table-c-grounding.tex` cell values — dispatch `docs-keeper` per CLAUDE.md's
  doc-parity rule once real numbers exist.

## Deliverables checklist — what to bring back from sr004

Per model (× 3):

- [ ] `reports/bouquet/judges/<slug>/scores.jsonl` — 2376 rows (198 paragraphs × 4 systems × 3 criteria),
      committed.
- [ ] `reports/bouquet/judges/<slug>/parse_failures.jsonl` — committed even if empty (diagnostic provenance).
- [ ] `reports/bouquet/judges/<slug>/stats.json` — means/tie-rate/Spearman vs MetricX-ref/MetricX-QE/COMET.
- [ ] `reports/bouquet/judges/summary.md` — regenerated, includes the new judge's rows.
- [ ] `reports/terminology/wiki-eval/<model-slug>/111/<run_id>/pred.jsonl` — full per-mention prediction
      records (100 articles).
- [ ] `reports/terminology/wiki-eval/<model-slug>/111/<run_id>/meta.json` — model/provider/spend-split/
      `generation_params`/wall-clock/call-counts self-evidencing the run (spend will read ~0 real cost).
- [ ] `reports/terminology/wiki-eval/<model-slug>/111/<run_id>/calls.jsonl` — per-call observability (spec Р8).
- [ ] `reports/terminology/wiki-eval/<model-slug>/111/<run_id>/metrics.json` + `report.html` — from `report`
      (protocol v3, no `--p3` flag any more).
- [ ] Both Ф0 probe transcripts (server-answers curl + thinking-off curl + structured-output curl) — paste
      into the commit body or a short session note, so a reviewer doesn't have to re-derive whether the
      `chat_template_kwargs` toggle actually worked on the real hardware.
- [ ] Wall-clock numbers for both the pilot and full run per model (printed to stderr by both runners) — feeds
      the next runbook's runtime estimates instead of re-guessing.

## Verified vs. NOT verified in this session

**Verified (code reading + live, GPU-free execution, this session):** both runners' base-URL resolution
already supports `OPENROUTER_BASE_URL` pointing at localhost (no patch needed, confirmed via `_resolve_route`/
`cmd_run` source and a live `uv run python3 -c ...` call); the `extra_body`/`t0_local` patch's request-payload
logic (`build_payload`, `_resolve_route`, `_parse_extra_body`) via 11 new unit tests, all passing, plus the
full pre-existing suite (582 tests total across both files' test modules + the rest of `tests/`) showing no
regression; `data/eval/wiki/gt_v2_sub20.jsonl`'s titles are a genuine subset of `gt.jsonl`'s; the real
`--max-usd`/`--max-judge-calls`/`--article-workers`/`--llm-workers` values used by the 3 already-completed
100-article cloud grounding runs (`gemini-3.1-flash-lite`, `deepseek-v4-flash`, `qwen3.7-plus`), read directly
from their committed `meta.json` files, not guessed.

**NOT verified — no GPU/SSH in this cloud session:** every `vllm serve` invocation in the bring-up section
(VRAM assumption, `--max-model-len` sizing, `--reasoning-parser` name); whether
`chat_template_kwargs.enable_thinking=false` actually suppresses Qwen3.6-27B's `<think>` output on the
sr004-installed vLLM build (the single highest-risk ASSUMPTION, same class of risk translation-eval.md already
flags for the identical model — the Ф0 probe's curl smoke test is exactly the check this session couldn't run
itself); whether vLLM's guided-JSON backend accepts `response_format: {"type": "json_object"}` cleanly on the
installed build; actual wall-clock numbers for any local run (every runtime estimate above is a stated
ASSUMPTION range, not a measurement). Treat every command in this document as a first draft to sanity-check
against `--help` output and the Ф0 probe before spending the full run's GPU-time.
