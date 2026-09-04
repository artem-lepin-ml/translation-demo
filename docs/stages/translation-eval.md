# Stage — Translation eval on sr004 (wiki-100 LLM-judge + refinement)

Up-link: [docs/pipeline.md](../pipeline.md). Design: [2026-07-07-wiki-llm-judge-eval.md](../superpowers/specs/2026-07-07-wiki-llm-judge-eval.md)
("Path A" — run Danil's pipeline as-is on a fresh clone, §4). Code under test:
[external/gse-translation](../../external/gse-translation/) (read-only vendored snapshot; see
[VENDORED.md](../../external/gse-translation/VENDORED.md)) — the real clone lives on sr004, not here.
Patches: [patches/gse-translation-sr004/](../../patches/gse-translation-sr004/).

**Status of this document: a runbook, not an execution log.** It was authored in a cloud session with no
GPU/SSH access to sr004 — every command below is either (a) verified by reading the vendored source
(argparse/typer definitions, config schemas, code paths) or (b) explicitly marked **UNVERIFIED** because it
was never actually run. Nothing here fabricates a CLI flag that doesn't exist in the vendored scripts.

## Purpose and scope

Execute spec §4 phases Ф0 (probe) through Ф2 (full run) on sr004 (4×A100): stand up the three local vLLM
servers, translate + judge + refine the 100-article wiki corpus (2 553 paragraphs) and the BOUQUET bridge
subset (198 paragraphs) through 4 translation systems, using Danil's pipeline unmodified except for the 5
patches in [patches/gse-translation-sr004/](../../patches/gse-translation-sr004/). Ф3 (QE metrics + BOUQUET
bridge tables) and Ф4 (analysis/report) are out of scope for this document — see spec §4 for their own
checklists once Ф0–Ф2 close out.

**Not in scope / not touched:** anything under `external/gse-translation/` in *this* repo (read-only,
untouched by this session); MetricX/COMET bring-up (Ф3, separate venv, spec §3); factcheck (excluded from
the wiki-eval scope per spec §1 non-goals).

## Prereqs

1. **SSH to sr004** (owner has access) and clone the upstream repo on the `artem` branch:

   ```bash
   git clone ssh://git@gitlab.frontierai.ru:8022/frontierai/teams/research/history-translation/ru2en-enciclopedia-translation.git
   cd ru2en-enciclopedia-translation
   git checkout artem
   git log -1 --format='%H %s'   # sanity: should show 3c1703a... or later on artem
   ```

   If `git log -1` shows a commit past `3c1703ab89a8a5a424f2a896c4646ce360bbf116`, diff the touched files
   against [external/gse-translation](../../external/gse-translation/) in this repo before trusting the
   patches below verbatim — re-verify with `git apply --check` (README's own advice).

2. **Environment** (`pyproject.toml`: `requires-python = ">=3.13"`):

   ```bash
   uv sync --extra dev            # base deps + pytest/ruff
   # vLLM lives in a SEPARATE extra and, per spec §3, needs version isolation
   # per model (TranslateGemma recipe 0.14.1+, Qwen3.6 ≥0.19) — `uv sync --extra vllm`
   # only pins vllm>=0.6, far looser than either constraint. See "vLLM bring-up" below
   # for why this likely means two separate venvs, not one `--extra vllm` install.
   cp .env.example .env
   ```

   Fill `.env` (`OPENROUTER_API_KEY=...`; `VLLM_API_KEY` already defaults to `EMPTY` in
   `.env.example` — vLLM's own OpenAI-compat server ignores the key value unless started with
   `--api-key`). **Never print or log `OPENROUTER_API_KEY`** (repo invariant,
   [.claude/rules/invariants.md](../../.claude/rules/invariants.md)). `OPENROUTER_BASE_URL` stays unset
   unless you need to route through a proxy — see `.env.example`'s own comment.

3. **Apply the 5 patches** (traps confirmed against the vendored snapshot — see
   [patches/gse-translation-sr004/README.md](../../patches/gse-translation-sr004/README.md) for the
   per-patch verdict table):

   ```bash
   cd ru2en-enciclopedia-translation   # Danil's repo root, NOT this repo
   for p in /path/to/translation-demo/patches/gse-translation-sr004/*.patch; do
     git apply --check "$p" && git apply "$p" || { echo "FAILED: $p"; break; }
   done
   ```

4. **Copy the corpus** (built and audited in this repo — see
   [python-pro-wiki-corpus-cleanliness-check.md](../reports/python-pro-wiki-corpus-cleanliness-check.md)):

   ```bash
   mkdir -p data/wiki
   cp /path/to/translation-demo/data/eval/wiki/wiki_original.json  data/wiki/wiki_original.json
   cp /path/to/translation-demo/data/eval/wiki/pilot_articles.json data/wiki/pilot_articles.json   # reference
   cp /path/to/translation-demo/data/eval/wiki/wiki_index.json     data/wiki/wiki_index.json        # reference
   ```

   `wiki_original.json` is the only file the pipeline actually reads (flat JSON array of 2 553 RU paragraph
   strings, same schema as `data/bouquet/bouquet_original.json`). `pilot_articles.json`
   (`{articles, paragraph_indices, smoke_indices}`, 274 global indices for the 10-article pilot) and
   `wiki_index.json` (per-paragraph `{i, title, section, par_idx, n_tokens}`) are sidecars for the Ф1 slicing
   step and the eventual per-article analysis (Ф4) — Danil's scripts never read them directly.

## `models.yaml` deltas

Add these entries to `configs/models.yaml` on sr004 (do not remove the existing entries — Ф0's BOUQUET
parity smoke reuses the verbatim `qwen3_6-27b` key as-is).

**deepseek — copied VERBATIM from the 2026-07-07 OpenRouter smoke**
([report](../reports/2026-07-07-deepseek-gateway-smoke.md); both traps are also recorded in
[known_issues.md](../known_issues.md#deepseek-v4-flash-reasons-by-default-on-openrouter-provider-9-empty-content-at-tight-max_tokens)):

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

**`${OPENROUTER_BASE_URL}` is report shorthand, not literal YAML syntax** — YAML has no env-var
interpolation and `ModelConfig.base_url: str` takes it verbatim. Set the literal string
`base_url: https://openrouter.ai/api/v1` (this is what makes `LLMConfig.from_model_config` treat the entry
as `or_style=True`, per [client.py](../../external/gse-translation/src/palimpsest/llm/client.py)); the
`OPENROUTER_BASE_URL` env var then transparently overrides it at runtime if set, exactly like every other
OR-routed entry already in `models.yaml`. Every field above (temperature/max_tokens/extra_body) is unchanged
from the report.

**Fixed-J primary judge — new entry, `qwen3_6-27b` VERBATIM alongside it for the pilot-mechanics role**
(spec §3, decision: primary judge is deterministic + non-thinking; Danil's verbatim thinking config is kept
for the pilot-mechanics check and the probe-2 test-retest run):

```yaml
# Danil's verbatim entry — KEEP as-is, used for pilot-mechanics (spec §3 role 1) and test-retest probe:
  qwen3_6-27b:
    name: Qwen/Qwen3.6-27B
    base_url: http://localhost:8000/v1
    api_key_env: VLLM_API_KEY
    temperature: 0.7
    max_tokens: 20000
    extra_body:
      top_k: 20
      chat_template_kwargs:
        enable_thinking: True

# NEW — fixed-J primary judge (spec §3 role 2): same model, deterministic, thinking off.
  qwen3_6-27b-fixed-j:
    name: Qwen/Qwen3.6-27B
    base_url: http://localhost:8000/v1     # ASSUMPTION: see port-collision note below
    api_key_env: VLLM_API_KEY
    temperature: 0
    max_tokens: 20000
    extra_body:
      top_k: 20
      chat_template_kwargs:
        enable_thinking: False
```

Both keys point at the *same* running vLLM server (Qwen3.6-27B is served once, kept up continuously per
spec §3's GPU layout) — `temperature`/`enable_thinking` are per-request sampling params the OpenAI-compat
client sends on every call, not server-side flags, so one server instance correctly serves both model keys.

**Qwen3-4B-Instruct-2507 — new entry, decision В5 (non-thinking, small local system)**. Not present in the
vendored `models.yaml` at all (only `qwen3-4b-thinking`, a *different* model —
`Qwen/Qwen3-4B-Thinking-2507`, used by the excluded factcheck stage). **ASSUMPTION** (ground: the Qwen3
non-thinking sampling recipe already used elsewhere in this same `models.yaml` for `qwen3.6-plus`
— `temperature: 0.7, top_p: 0.8` — and the model-card convention `top_k=20, min_p=0` noted in
[config.py](../../external/gse-translation/src/palimpsest/config.py)'s own comment; verify against the
actual `Qwen/Qwen3-4B-Instruct-2507` model card on sr004 before the Ф0 smoke):

```yaml
  qwen3-4b-instruct:
    name: Qwen/Qwen3-4B-Instruct-2507
    base_url: http://localhost:8000/v1     # ASSUMPTION: see port-collision note below
    api_key_env: VLLM_API_KEY
    temperature: 0.7
    top_p: 0.8
    top_k: 20
    min_p: 0
    max_tokens: 16000
```

**Port collision — must fix before any concurrent bring-up.** Every local entry in the vendored
`models.yaml` (`translate_gemma-27b`, `qwen3_6-27b`, `qwen3-4b-thinking`) hardcodes
`base_url: http://localhost:8000/v1`. Spec §3's GPU layout needs TranslateGemma (GPU0), Qwen3-4B (GPU1) and
Qwen3.6-27B (TP=2, GPU2-3) **served simultaneously** for parts of Ф1 (full TG+deepseek cycle plus a
Qwen3.6/Qwen-4B smoke) and for Ф0's "all servers answer" probe — three servers can't share one port.
Assign distinct ports when starting each `vllm serve` (see next section) and update each entry's `base_url`
to match (e.g. TG→`:8001`, Qwen-4B→`:8002`, Qwen3.6-27B→`:8000`) — **exact assignment is sr004's call, not
fixed here.** This is the same "config drift" spec §0 already flags for `models.yaml` in general
("порт 7000 vs 8000... провенанс всегда по `config.json` прогона") — treat the yaml as a live, hand-edited
file per bring-up, and trust each run's own `config.json`/`meta.json` for what was *actually* used, not the
yaml snapshot in this doc or in git history.

## vLLM bring-up (3 local models, 4×A100)

**ASSUMPTION-heavy section** — the vendored repo ships no `vllm serve` invocation for any of the three wiki
systems. The one real, grounded precedent in the vendored tree is
[docs/factchecker.md](../../external/gse-translation/docs/factchecker.md)'s smoke-test recipe for
`Qwen/Qwen3-4B-Thinking-2507` (a *different*, thinking, Qwen3-4B variant — used for the out-of-scope
factcheck stage, not for wiki-eval translation):

```bash
python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-4B-Thinking-2507 \
    --reasoning-parser deepseek_r1 \
    --dtype bfloat16 \
    --data-parallel-size 1 \
    --max-num-batched-tokens 32768 \
    --max-model-len 32768 \
    --max-num-seqs 1024 \
    --gpu-memory-utilization 0.90
```

Adapted per model below — every flag not directly traceable to this precedent or to spec §3 is marked
ASSUMPTION; verify with `--help` on the actual installed vLLM build before the Ф0 probe.

**TranslateGemma** (`Infomaniak-AI/vllm-translategemma-27b-it`, GPU0, temp 0.7 in `models.yaml`, "2K context
repack" per spec §4 Ф0):

```bash
CUDA_VISIBLE_DEVICES=0 python3 -m vllm.entrypoints.openai.api_server \
    --model Infomaniak-AI/vllm-translategemma-27b-it \
    --port 8001 \
    --dtype bfloat16 \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.90        # ASSUMPTION: value copied from the factcheck precedent
```

ASSUMPTION: `--max-model-len 2048` from the spec's "2K context repack" wording — this is the repack's
documented context ceiling, not a value read from vendored code (no serving config for TG exists in the
vendored tree). Spec §3 also notes TG needs **vLLM ≥0.14.1** specifically (a narrower/older pin than Qwen3.6's
≥0.19) — likely because the Infomaniak repack's model code was only merged into vLLM in that range; verify
the repack's own README/model card on sr004 and pick the venv/vLLM build accordingly. No `--reasoning-parser`
needed — TranslateGemma is not a reasoning model.

**Qwen3-4B-Instruct-2507** (GPU1, non-thinking per decision В5):

```bash
CUDA_VISIBLE_DEVICES=1 python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-4B-Instruct-2507 \
    --port 8002 \
    --dtype bfloat16 \
    --max-num-batched-tokens 32768 \
    --max-model-len 32768 \
    --max-num-seqs 1024 \
    --gpu-memory-utilization 0.90
```

Same shape as the factcheck precedent minus `--reasoning-parser` (Instruct-2507 is the non-thinking
variant — no `<think>` tags to parse, matching decision В5's "не-thinking, стабильный vLLM").
`--max-num-batched-tokens`/`--max-model-len`/`--max-num-seqs`/`--gpu-memory-utilization` are copied from the
one real precedent (ASSUMPTION they transfer to this smaller non-thinking sibling — re-check against
available VRAM once GPU1 is confirmed idle).

**Qwen3.6-27B** (TP=2, GPU2-3, kept up continuously — judge, editor, AND one of the 4 translation systems;
`enable_thinking` toggled per-request via `chat_template_kwargs`, not a server flag):

```bash
CUDA_VISIBLE_DEVICES=2,3 python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3.6-27B \
    --port 8000 \
    --tensor-parallel-size 2 \
    --dtype bfloat16 \
    --reasoning-parser deepseek_r1 \        # ASSUMPTION — see note below
    --max-num-batched-tokens 32768 \
    --max-model-len 32768 \
    --max-num-seqs 1024 \
    --gpu-memory-utilization 0.90
```

`--tensor-parallel-size 2` is grounded in spec §3 ("TP=2, GPU2-3"). `--reasoning-parser` is critical per
spec §0's own risk note — **"`<think>`-защиты в коде нет — полагается на reasoning-parser vLLM-сервера"**
(no `<think>` stripping in Danil's code at all; it's entirely the server's job) — but the vendored tree gives
no evidence for which parser name is right for Qwen3.6 specifically (`deepseek_r1` is the factcheck
precedent's choice for a *different* Qwen thinking model on an older vLLM). Spec §3 requires **vLLM ≥0.19**
for this model; check `python3 -m vllm.entrypoints.openai.api_server --help | grep -A2 reasoning-parser`
on the actual installed build for a dedicated `qwen3`-family parser name before trusting `deepseek_r1` here —
this is the single highest-risk ASSUMPTION in this section, because a wrong/missing parser silently leaks
`<think>...</think>` into judge output and Danil's JSON parser will treat it as a parse failure (retry, then
`parse_failures.jsonl`), not a crash — so a bad parser choice is discoverable but not fail-loud.

## Ф0 — probe (day 1, before paid volume)

1. **All three servers answer**: `curl http://localhost:<port>/v1/models` for each of the three ports above.
2. **OpenRouter reachable** with the patched client (patch 05): a throwaway single call through
   `deepseek-v4-flash-translate` — confirm no 403 (the WAF watchpoint from the smoke report) and that
   `reasoning_tokens=0` (confirms the `reasoning.enabled: false` flag from the models.yaml delta is honored
   on THIS route/session — the smoke report's finding was session-scoped, not guaranteed permanent).
3. **BOUQUET parity smoke** (spec §4 Ф0): translate 3 BOUQUET paragraphs through your sr004 stack and
   compare against the vendored ground truth at
   `data/bouquet/translation/{translate-gemma-bouquet,qwen-27b-bouquet}/translation.json` +
   `data/bouquet/evaluation/*/universal/*/accuracy_scores.jsonl`. Tolerance: **not** exact-match (temp 0.7
   sampling means non-deterministic output) — parity means same JSON schema, `final_score` in the plausible
   1–10 range, judge JSON parses on the first attempt. Concretely:

   ```bash
   # first 3 paragraphs of the vendored bouquet_original.json, same schema as wiki_original.json
   python3 -c "import json; d=json.load(open('data/bouquet/bouquet_original.json'))[:3]; json.dump(d, open('/tmp/bouquet3.json','w'), ensure_ascii=False)"
   uv run python scripts/02_translate_json.py \
     --run-name parity-smoke --bucket local --model translate_gemma-27b \
     --user-prompt 02_translate/gemma_universal.md \
     --input /tmp/bouquet3.json --out-root data/wiki/translating --max-concurrency 3
   # then score the 3 rows against qwen3_6-27b-fixed-j via a throwaway scoring config
   # (base_dir + original_json/translation_json pointed at the 3-row files, judges: [qwen3_6-27b-fixed-j])
   ```

   UNVERIFIED — this is the recipe, not a run; no GPU in this session.

## Ф1 — pilot (day 1: 10 articles, 274 paragraphs)

**Slicing the pilot input.** `02_translate_json.py` has **no subset/index-filter CLI flag** (confirmed by
reading its full argparse surface — see patches README) — the only way to translate fewer than all 2 553
paragraphs is to feed it a smaller `--input` file. Build the 274-paragraph pilot slice from the sidecar's
`paragraph_indices` (order-preserving, so local pilot id `k` maps back to global wiki id
`paragraph_indices[k]` — keep that mapping, it is needed for the per-article Ф4 analysis and for the
Ф2 reuse discussion below):

```bash
python3 -c "
import json
wiki = json.load(open('data/wiki/wiki_original.json'))
pilot = json.load(open('data/wiki/pilot_articles.json'))
idx = pilot['paragraph_indices']
sliced = [wiki[i] for i in idx]
json.dump(sliced, open('data/wiki/wiki_pilot_original.json', 'w'), ensure_ascii=False, indent=2)
json.dump(idx, open('data/wiki/wiki_pilot_global_ids.json', 'w'))   # local id k -> global wiki id
print(len(sliced), 'paragraphs sliced')
"
```

UNVERIFIED (data-prep one-liner, not run — no local copy of `pilot_articles.json`'s exact bytes was
cross-checked against a live wiki_original.json in this session beyond the `len()==274`/`==2553` check
already reported in the corpus-cleanliness report).

**TranslateGemma needs no system role — and the CLI cannot force that on its own.** Confirmed by reading
`main()`: `system_prompt_rel = system_prompt or cfg.system_prompt` — an *omitted* `--system-prompt` always
falls back to `configs/translation.yaml`'s shared `system_prompt:` value (currently `02_draft/system.md`,
non-null), and an *explicit* `--system-prompt ""` is equally falsy and falls back the same way (empty string
`or` acts like `None`). Loading an empty **file** doesn't help either — `system_prompt = ""` (not `None`)
still gets sent as an empty-content system message, which is not the same as omitting the role entirely
(compare `_complete_openai`: `if system is not None: messages.insert(...)`). The only way to reproduce the
real `translate-gemma-bouquet/config.json`'s `"prompt_path": null` is to make `cfg.system_prompt` itself
`None` at call time — i.e. edit `configs/translation.yaml` for the duration of the TG run:

```bash
git stash -- configs/translation.yaml 2>/dev/null   # in case of uncommitted local edits already
sed -i 's/^system_prompt: .*/system_prompt: null/' configs/translation.yaml
uv run python scripts/02_translate_json.py \
  --run-name translate_gemma-27b-pilot --bucket wiki --model translate_gemma-27b \
  --user-prompt 02_translate/gemma_universal.md \
  --input data/wiki/wiki_pilot_original.json --out-root data/wiki/translating \
  --max-concurrency 32
git checkout -- configs/translation.yaml             # restore the shared default before the Qwen run
```

UNVERIFIED. This is a real code-reading finding, not copied from the spec — flag it to Danil as a genuine
usability gap (no per-invocation override to unset a shared config default) separate from the 5 patched
traps, since it's a workflow footgun rather than one of the 5 named concerns.

**deepseek** (translate; note deepseek's Ф1 role differs from TG's — see the Ф2 reuse discussion below for
why deepseek should likely translate the FULL 2 553-paragraph corpus once, here, rather than the 274-slice):

```bash
uv run python scripts/02_translate_json.py \
  --run-name deepseek-v4-flash --bucket wiki --model deepseek-v4-flash-translate \
  --system-prompt 02_translate/system_universal.md --user-prompt 02_translate/user.md \
  --input data/wiki/wiki_original.json --out-root data/wiki/translating \
  --max-concurrency 8   # ASSUMPTION — OpenRouter concurrency, spec §5/§7: "семафор 4-8"
```

**Qwen3.6-27B and Qwen3-4B — 5-paragraph mechanics smoke only** (spec §4 Ф1: not the full pilot cycle):

```bash
head -c 100000 data/wiki/wiki_pilot_original.json > /dev/null   # sanity only
python3 -c "import json; d=json.load(open('data/wiki/wiki_pilot_original.json'))[:5]; json.dump(d, open('/tmp/smoke5.json','w'), ensure_ascii=False)"
uv run python scripts/02_translate_json.py --run-name qwen3_6-27b-smoke5 --bucket wiki --model qwen3_6-27b \
  --system-prompt 02_translate/system_universal.md --user-prompt 02_translate/user.md \
  --input /tmp/smoke5.json --out-root data/wiki/translating --max-concurrency 5
uv run python scripts/02_translate_json.py --run-name qwen3-4b-smoke5 --bucket wiki --model qwen3-4b-instruct \
  --system-prompt 02_translate/system_universal.md --user-prompt 02_translate/user.md \
  --input /tmp/smoke5.json --out-root data/wiki/translating --max-concurrency 5
```

**Judge** (fixed-J primary, `qwen3_6-27b-fixed-j`) — a `configs/scoring/wiki-pilot.yaml` in the shape already
used by `configs/scoring/qwen3.6-27b-bouquet.yaml`:

```yaml
base_dir: data/wiki
original_json: data/wiki/wiki_pilot_original.json
translation_json: data/wiki/translating/wiki/translate_gemma-27b-pilot/translation.json
prompts_variant: universal
max_concurrency: 64        # ASSUMPTION — Danil's BOUQUET pass used 360 against his own local server; scale
                            # down for a pilot-sized smoke test, tune up once Ф0 confirms server throughput.
judges:
  - model: qwen3_6-27b-fixed-j
runs:
  - wiki/translate_gemma-27b-pilot
```

```bash
uv run python scripts/03_translation_scoring.py --config configs/scoring/wiki-pilot.yaml
```

Repeat with a `translate-gemma-bouquet`-shaped config per system (`deepseek-v4-flash`, and — for the
5-paragraph smokes — a `--max-paragraphs 5` override) to exercise judge parse-rate across all 4 systems.
`run_scoring` writes `evaluation/<run>/universal/reports/<judge>.jsonl` automatically (via
`build_judge_reports`, called at the end of `run_scoring` — no separate script needed; the standalone
`scripts/03_build_judge_reports.py` is a hardcoded-to-`data/pilot` backfill utility, not part of this flow).

**Refinement** (patch 04 adds `meta.json` next to the output):

```bash
uv run python scripts/04_refinement.py \
  data/wiki/evaluation/translate_gemma-27b-pilot/universal/reports/qwen3_6-27b-fixed-j.jsonl \
  data/wiki/translating/wiki/translate_gemma-27b-pilot-refined/translation.json
```

**Re-judge** the refined output: same scoring config shape, `translation_json` pointed at the `-refined`
output, `runs: [wiki/translate_gemma-27b-pilot-refined]` (note: `-refined` needs its own
`translate-gemma-bouquet-refined`-style bucket/run naming — `evaluation_run_dir` drops the bucket and keys
purely on `run_name`, so keep refined-run names globally unique, e.g. suffix `-refined` as Danil's own
BOUQUET runs do).

**Go/no-go checklist** (spec §4 Ф1, unchanged from the spec — re-listed here as the actual gate to check
against the artifacts above, not re-derived):

- `wiki_original.json` schema accepted end-to-end (translate → judge → refine ran without a code error).
- Judge parse-rate ≥98% (count non-null rows in each `*_scores.jsonl` against total paragraphs scored;
  `parse_failures.jsonl` gives the raw denominator of retries).
- Zero `<think>` leakage in translations (0 expected — TranslateGemma/deepseek aren't reasoning models
  in this config; Qwen3.6/Qwen-4B smokes are the actual test of the vLLM `--reasoning-parser` bring-up).
- Refinement no-op rate: fraction of `refined == initial` among paragraphs where `identified_issues` was
  non-empty (a suspiciously high rate would mean the editor is rubber-stamping, not fixing).
- QE-input validity — deferred to Ф3 (not yet run here).
- Paragraph-id round-trip: 0 losses between `wiki_pilot_original.json` (274) → `translation.json` (274) →
  `reports/<judge>.jsonl` (274) → refined `translation.json` (274).
- Wall-clock/paragraph per phase (translate/judge/refine), captured from each `config.json`'s
  `created_at` deltas and stderr progress logs — feeds the Ф2 extrapolation.
- deepseek $/paragraph ≤1.5× the smoke-report estimate ($0.0012/paragraph translate,
  ~$0.00044/paragraph/criterion judge from the 2026-07-07 smoke).

## Ф2 — full run (night 1 – day 2): 2 553 × 4 systems

**Checkpointing/resume, verified per script (not assumed):**

| Script | Resume mechanism | Verified against |
|---|---|---|
| `02_translate_json.py` | `progress.jsonl` — one fsynced JSONL line per completed paragraph (`{"type":"paragraph","id":…,"translation":…}`); `ProgressLog.load()` pre-fills `done_paragraphs` on the next invocation of the **same `--run-name`/`--bucket`/`--out-root`**, so a killed/restarted run only pays for the paragraphs not yet in the log. | [translate_json.py](../../external/gse-translation/src/palimpsest/translate_json.py) `ProgressLog`, `translate_per_paragraph` |
| `03_translation_scoring.py` | Per-criterion `load_existing_ids()` skip — re-running the same `--config` only scores ids missing from each `<criterion>_scores.jsonl`. `--force` deletes all existing jsonl for the configured runs first (fresh re-score). | [scoring.py](../../external/gse-translation/src/palimpsest/scoring.py) `load_existing_ids`, `_score_run_for_judge`; CLI flag in `03_translation_scoring.py` |
| `04_refinement.py` | **None.** `run_refinement` reads the whole `scores_jsonl` into an in-memory task list (`tqdm.gather`) and writes the entire output file **once**, at the end. A crash mid-run loses every completed refinement in that invocation — there is no partial-write/append path to resume from. Patch 04 adds a `meta.json` manifest for provenance, **not** a checkpoint. | [refinement.py](../../external/gse-translation/src/palimpsest/refinement.py) `run_refinement` (full read, top-level `asyncio` gather, single `output.write_text` at the end) |

**Refinement's lack of resume is the single biggest operational risk for Ф2** — with ~10k paragraph-level
refine calls expected (table below), a late-stage crash on a long `tqdm.gather` re-pays for every already-completed
call. Not one of the 5 named patch traps (spec scope is fixing 5 specific concerns, not adding checkpointing
to Danil's code), so **not patched** here — mitigate operationally instead: run refinement in smaller batches
(e.g. one `scores_jsonl`/`output` pair per article or per N-paragraph chunk, splitting the input JSONL and
concatenating outputs by hand) rather than one 2 553-paragraph call per system, so a crash only loses one
batch. UNVERIFIED as a recommendation — not exercised in this session.

**Reusing Ф1 pilot results in Ф2 (spec §4 decision В4: "не пересчитываются").** This only cleanly works at
the **scoring** layer, which has real id-keyed resume (table above) — pointing Ф2's scoring config at the
full corpus and NOT passing `--force` naturally skips the pilot's 274 already-scored ids. At the
**translation** layer there is no such thing (no subset flag, confirmed above), so a pilot slice translated
into its own small run dir (`wiki/translate_gemma-27b-pilot`) is **not** automatically picked up by a later
full-corpus run under a different `--run-name`/`--input`. Two honest options, not mutually exclusive:

1. **For deepseek (the only paid system): skip the pilot/full split entirely** — translate the full 2 553-paragraph
   `wiki_original.json` once, during Ф1, under the run name Ф2 will also use (`deepseek-v4-flash`, shown
   above). Ф1's pilot analysis then just runs judge/refine on the 274-paragraph `paragraph_subset` of that
   already-complete translation (see the `paragraph_subset` mechanism in
   [scoring_subsets.py](../../external/gse-translation/src/palimpsest/scoring_subsets.py) — a
   `{"name", "paragraph_ids"}` JSON at `<base_dir>/scoring_subsets/<name>.json`, directly usable with the
   `wiki_pilot_global_ids.json` list generated above), and Ф2 for deepseek is then just "score/refine the
   remaining ~2 279 paragraphs" (which the id-keyed resume above handles for free, no extra config).
   Sidesteps the reuse problem for the one system where recomputation would actually cost money — this is
   the recommended approach.
2. **For the local ($0) systems (TG, Qwen3.6, Qwen-4B):** re-translating the pilot's 274 paragraphs a second
   time during Ф2 costs GPU-minutes, not dollars — acceptable to just accept the small recomputation rather
   than engineer a splice. If wall-clock is tight, `progress.jsonl` **can** be spliced by hand before starting
   Ф2's full run (its schema is a flat per-line `{"type":"paragraph","id":<int>,"translation":<str>}`, parsed
   purely by `id` regardless of provenance — confirmed by reading `ProgressLog.load()`): write the pilot
   run's 274 records into the full run's (not-yet-existing) `progress.jsonl` with `id` remapped from local
   pilot index `k` to the global index `wiki_pilot_global_ids.json[k]`, **before** the first Ф2 invocation for
   that `--run-name`. UNVERIFIED — a plausible mechanism grounded in the actual resume code, not exercised.

**Expected call counts** (mechanical arithmetic from the corpus size and pipeline shape, cross-checked
against spec §7's own budget table):

| Phase | Formula | Count |
|---|---|---|
| Translate | 2 553 paragraphs × 4 systems (no chunking, 1 call/paragraph — trap (b) confirms chunked mode is dead code, not a real second path) | **10 212** |
| Judge, per pass | 2 553 × 4 systems × 3 criteria (accuracy/fluency/style, universal variant) | **30 636** |
| Judge, translate→judge→refine→**re-judge** (2 passes, spec §4 Ф1) | 2 × 30 636 | **61 272** (matches spec §7's "~61к judge-вызовов") |
| Refinement | 1 call per paragraph with ≥1 issue; **0 calls** for issue-free paragraphs (`_build_edit_message` returns `""`, `refine_one` short-circuits to `return json_line['translated']` before any LLM call) | upper bound **10 212**; spec §7 estimates **~10к** (near-upper-bound issue rate) — actual rate is a Ф1 pilot output, not assumed here |

Local models (TG, Qwen3.6, Qwen-4B) cost $0 in API terms (GPU-hours only); deepseek is the only line item
against the $15 cap (spec §7 decision В6) — its translate+judge+refine share of the above table should track
the smoke report's $0.0012/paragraph (translate) and ~$0.00044/paragraph/criterion (judge) rates, scaled to
2 553 paragraphs, well under the ≈$2–4 line item spec §7 already budgets for wiki+BOUQUET combined.

## What was and wasn't verified in this session

**Verified (code reading + `git apply --check`, no GPU):** all 5 patch traps against the actual vendored
files (see patches README); every CLI flag cited above exists in the vendored `argparse`/`typer`
definitions (`02_translate_json.py`, `03_translation_scoring.py`, `04_refinement.py` — no flag invented);
the resume/checkpoint behavior of all three scripts (source read, not run); the `paragraph_subset`
mechanism's exact file schema; the `ScoringConfig.original_json`/`translation_json` direct-JSON code path
that lets scoring skip the `.md`-based pilot pathway entirely; the port-collision and shared-`system_prompt`
footguns (both discovered by reading `main()`/`_run()`, not copied from the spec).

**NOT verified — no GPU/SSH in this cloud session:** every vLLM `serve` invocation (bring-up section is the
single highest-uncertainty part of this document — flagged ASSUMPTION throughout); actual wall-clock/cost
numbers for wiki-scale runs; whether `Qwen/Qwen3.6-27B`'s `chat_template_kwargs.enable_thinking` toggle
behaves identically at temp 0 vs Danil's temp 0.7 verbatim config (this is explicitly something Ф1/probes
are supposed to *measure*, not assume — spec §9); the `qwen3-4b-instruct` and `qwen3_6-27b-fixed-j` yaml
entries added above (never loaded by `load_models()` in a real process); the `system_prompt: null` sed
workaround for TranslateGemma end-to-end. Treat every code block in this document as a first draft to
sanity-check against `--help` output and a `--max-paragraphs 1`-scale dry run before spending the Ф1 budget.
