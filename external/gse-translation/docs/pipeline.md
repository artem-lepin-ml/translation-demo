# Pipeline

Up-link: [CLAUDE.md](../CLAUDE.md). Stage details: [docs/stages/](stages/). Interface contract: [references/interfaces_agreement.md](../references/interfaces_agreement.md).

## Scope

Pilot: 3 chapters of Volume 1 of the Great Soviet Encyclopedia, parsed into a single `data/pilot/pilot_original.md`. One line per paragraph, paragraph id = 0-indexed line number.

Production volumes are out of scope until the pilot lands. Paths in this doc refer to pilot artifacts only.

## Stage 00 — Parse (external, fixed)

Source: `data/raw/vol01_source.pdf` → `data/pilot/pilot_original.md`.

External step. Output is committed to the repo. Not re-run by current scripts. The legacy parser (Artem) lives at [_legacy/scripts/00_parse_pdf.py](../_legacy/scripts/00_parse_pdf.py); the pilot parser comparison is at [_legacy/docs/pilot_parsers.md](../_legacy/docs/pilot_parsers.md).

Status: **done** for the pilot. No new code expected here in pilot scope.

## Stage 01 — Chunking

Distribution of paragraph ids into LLM calls. Output: `data/pilot/chunking/translation/<chunk_name>.json` and `data/pilot/chunking/evaluation/<NN>_<chapter_slug>.json`. List-of-lists format, see the agreement.

Status: **manual** for the pilot — no script. The five strategies (`whole_chapter`, `by_subchapter`, `paragraph_by_paragraph`, `by_k_paragraphs`, `smart_llm_split`) are implemented by hand-editing JSON.

## Stage 02 — Translate

Implementation: [src/palimpsest/translate.py](../src/palimpsest/translate.py). CLI driver: [scripts/02_translate.py](../scripts/02_translate.py). Detail: [stages/02_translate.md](stages/02_translate.md).

Reads `data/pilot/pilot_original.md` and `data/pilot/chunking/translation/<chunk_name>.json`. Writes `data/pilot/translating/<bucket>/<run_name>/translation.md` (line-aligned with the source) and `config.json` (reproducible run record). `<bucket>` ∈ `{small, large, local}` selected via `--bucket` CLI flag.

Status: **aligned**. Driver writes bucketed line-aligned output, `progress.jsonl` enables crash-safe resume, partial-success path via `failures.jsonl` and `failure_debug/` exists for chunked strategies.

## Stage 03 — Scoring

Per-paragraph evaluation by N judge models in parallel: N одно-criterion вызовов на judge на paragraph (5 критериев: accuracy, terminology, cultural, fluency, style; consistency убран в `_legacy/`). Factcheck выключен по умолчанию; включается явным `factcheck: {enabled: true}` в конфиге.

| Critic | Backend | Score |
|---|---|---|
| accuracy | `prompts/03_scoring/v1/accuracy.md` | int 1–10 (`null` = sentinel skip / persistent parse failure) |
| terminology | `prompts/03_scoring/v1/terminology.md` | int 1–10 |
| cultural | `prompts/03_scoring/v1/cultural.md` | int 1–10 |
| fluency | `prompts/03_scoring/v1/fluency.md` | int 1–10 |
| style | `prompts/03_scoring/v1/style.md` | int 1–10 |
| factcheck | Two-sided atomic-fact overlap, see [factchecker.md](factchecker.md) | float 0–1 (F1) — опционально |

Implementation: [src/palimpsest/scoring.py](../src/palimpsest/scoring.py) (config-driven dispatcher) + [src/palimpsest/factcheck/](../src/palimpsest/factcheck/) (atomic-fact overlap). CLI driver: [scripts/03_translation_scoring.py](../scripts/03_translation_scoring.py). Detail: [stages/03_scoring.md](stages/03_scoring.md).

Config sketch (минимальный, без factcheck):

```yaml
base_dir: data/pilot
prompts_variant: v1
max_concurrency: 64
judges:
  - model: gpt-5.5-low
# paragraph_subset: complex_150   # опционально
runs:
  - large/qwen_par_by_par
```

Output contract: `data/pilot/evaluation/<run_name>/v1/<judge>/<criterion>_scores.jsonl` (raw per-judge) + derived `data/pilot/evaluation/<run_name>/v1/comparison.jsonl` (judges side-by-side) + `data/pilot/evaluation/<run_name>/v1/reports/<judge>.jsonl` (full llm_report per judge). Factcheck вне variant'а: `<run_name>/factcheck/factcheck_scores.jsonl`. `merged_scores.jsonl` и top-level `scores.json` удалены. See [pilot_interfaces_agreement.md](pilot_interfaces_agreement.md) for the JSON schemas.

Status: **refactor 2026-05-14** (paragraph subsets + variant subpath в output + comparison/reports арtefacts + consistency → `_legacy/` + factcheck off by default). Single judge `gpt-5.5-low` in 01-06 configs; other judges pluggable later.

## Existing pilot run

`data/pilot/evaluation/qwen_pilot/` holds 6 critic JSONLs from an earlier run. Factcheck JSONL for that run is missing.

## Reviewing results — Translation Comparison Viewer

A small web UI on top of `data/pilot/evaluation/` lets the expert browse paragraphs side by side and inspect per-criterion judge scores + summaries. Backend is FastAPI (reads `comparison.jsonl` + `reports/<judge>.jsonl`); frontend is a fork of [PAIR-code/llm-comparator](https://github.com/PAIR-code/llm-comparator). See [viewer/README.md](../viewer/README.md) for run / build / deploy and [docs/superpowers/specs/2026-05-15-translation-viewer-design.md](superpowers/specs/2026-05-15-translation-viewer-design.md) for design.
