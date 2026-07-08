# Palimpsest

LLM-assisted translation of the **Great Soviet Encyclopedia** (Russian → English). Seven volumes. Research project at SberAI, with terminology and proofreading support from MGIMO.

## What this delivers

- **Primary** — seven translated volumes, publication-ready draft with annotated spots for expert revision.
- **Secondary** — research paper and public methodology on LLM-assisted academic translation.

## How it works

The pipeline runs the pilot (three chapters of Volume 1) through four stages: PDF parse, chunking, translation, and evaluation. Each stage is independently runnable and produces inspectable artifacts. The pilot is paragraph-aligned: paragraph id = 0-indexed line number in `data/pilot/pilot_original.md`. See [docs/pipeline.md](docs/pipeline.md) for stage detail and current status; the contract is in [references/interfaces_agreement.md](references/interfaces_agreement.md).

For the architecture, stage interfaces, and current status, see [CLAUDE.md](CLAUDE.md). For the full pipeline narrative, see [docs/pipeline.md](docs/pipeline.md).

## Stack

Python 3.13, `uv` for dependency management, `ruff` for lint and format. LLM access is centralized via a single async client (the `palimpsest.llm.client.LLMClient` contract from CLAUDE.md Hard Invariant #6) that dispatches to two SDKs based on the endpoint's `base_url`: the Anthropic SDK (required for Opus extended thinking) for any URL containing `anthropic.com`, `AsyncOpenAI` for everything else (cloud OpenAI, xAI/Grok, GigaChat-compat shim, local vLLM). PDF parsing is pluggable: `pymupdf4llm` is the baseline (CPU, always installed) and `docling` / `magic-pdf` (MinerU) live in optional extras `pilot-docling` / `pilot-mineru`. Data is tracked via Git LFS. See [CLAUDE.md](CLAUDE.md) for full conventions.

## Conventions

[Conventional Commits](https://www.conventionalcommits.org/) in English. Stage code lives as flat modules under [src/palimpsest/](src/palimpsest/) (one stage per module). CLI scripts under [scripts/](scripts/), numbered by pipeline order. Configuration via YAML files in [configs/](configs/). See [CLAUDE.md](CLAUDE.md#conventions) for detail.

## Подробное описание пилота (MUST READ)

- [docs/pilot_interfaces_agreement.md](docs/pilot_interfaces_agreement.md) — актуальная информация по соглашениям, стадиям и расположению файлов для пилота.

## Further reading

- [CLAUDE.md](CLAUDE.md) — technical brief, conventions, hard invariants, routing.
- [docs/pipeline.md](docs/pipeline.md) — full pipeline narrative with per-stage detail.
- [docs/stages/](docs/stages/) — per-stage detail.
- [docs/factchecker.md](docs/factchecker.md) — running Stage 4 against vLLM, troubleshooting.
- [viewer/README.md](viewer/README.md) — paragraph-comparison web UI on top of `data/pilot/evaluation/`.

