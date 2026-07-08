# Vendored: gse-translation (branch `artem`)

Read-only snapshot of Danil's translation + refinement + LLM-as-a-judge pipeline,
vendored so cloud sessions (no GitLab access) can read the exact code and data
behind the BOUQUET evaluation tables.

## Provenance

- **Upstream:** `ssh://git@gitlab.frontierai.ru:8022/frontierai/teams/research/history-translation/ru2en-enciclopedia-translation.git`
- **Branch:** `artem`
- **Commit:** `3c1703ab89a8a5a424f2a896c4646ce360bbf116` — "fix(refinement): add text cleaning" (2026-07-07 00:29 +0300)
- **Vendored:** 2026-07-07, selective copy (not a full mirror)
- Upstream `CLAUDE.md` is kept as `_UPSTREAM_CLAUDE.md` so it is not picked up
  as live agent instructions.

## What is included

| Path | Why |
|---|---|
| `scripts/02_translate*.py`, `04_refinement.py` | translation + refinement entry points |
| `scripts/03_translation_scoring.py`, `03_build_judge_reports.py`, `03_judge_review_views.py`, `03_scoring_*.sh` | LLM-as-a-judge scoring pipeline |
| `src/palimpsest/` (minus `factcheck/`) | library code behind the scripts (LLM client, chunking, scoring, refinement) |
| `prompts/02_translate/`, `prompts/03_scoring/`, `prompts/04_refinement/` | all translate / judge (v1, v2, universal) / refinement prompts |
| `configs/` | model registry, translation / refinement / scoring run configs |
| `docs/` | pipeline + stage docs, pilot-evaluation experiment (correlation methodology), specs/plans |
| `data/bouquet/` | BOUQUET inputs + full evaluation outputs for all 4 systems (judge scores, MetricX, COMET) — LFS objects materialized |
| `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example`, `README.md` | environment reproduction |

## What is excluded

- `data/pilot/` (~692 MB — history-volume pilot translations, judge logs and derived review views)
- `viewer/` (LLM-comparator UI), `tests/`, `_legacy/`, `src/palimpsest/factcheck/`, `scripts/pilot/`, `scripts/probes/`, `scripts/deploy_sync.sh`
- No correlation (Spearman) script exists upstream outside docs — correlations were computed outside git (see `docs/experiments/2026-05-13-pilot-evaluation.md` for methodology notes).

## Key facts extracted (for the wiki-judge-eval spec)

- BOUQUET judge = `qwen3_6-27b` (`Qwen/Qwen3.6-27B`, local vLLM, `enable_thinking: true`, temp 0.7, top_k 20) with `prompts_variant: universal` — 3 criteria: accuracy / fluency / style (`prompts/03_scoring/universal/`).
- Refinement (`configs/refinement.yaml`): `editor_model: qwen3_6-27b`, criteria `['accuracy', 'fluency', 'style']`, prompt `prompts/04_refinement/system.md` — i.e. "Translate Gemma Refined" was refined by Qwen3.6-27B, not by TranslateGemma itself.
- Refinement flow: judge report JSONL (`.../universal/reports/<judge>.jsonl`) → `scripts/04_refinement.py` → corrected `translation.json`; the editor fixes every listed issue in one pass, changes nothing else, outputs plain corrected text.
- TranslateGemma served as `Infomaniak-AI/vllm-translategemma-27b-it` (the vLLM repack), temp 0.7.

Do not edit files here; fix things in our own pipeline code instead and record
divergences in the spec.
