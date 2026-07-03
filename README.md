# Palimpsest — Translation Evaluation Demo

Interactive evaluation web app for LLM-assisted translation of the Great Soviet Encyclopedia (RU → EN).
Load a bilingual document, get LLM-as-judge highlights with explanations and suggested fixes, accept corrections, re-score — and see the quality gain. Terminology is grounded with two independent signals via Wikidata. Project brief: [CLAUDE.md](CLAUDE.md). Webapp subsystem: [docs/subsystems/webapp.md](docs/subsystems/webapp.md).

## What the demo does

- Renders 16 seed paragraphs (Mesopotamia pilot) with per-criterion score overlays.
- Upload your own original↔translation pair (paste or `.docx`/`.md`/`.txt` file, any language pair) via the top-bar modal — paragraph-alignment preview, background cache warm-up, delete when done.
- Inspector panel: per-paragraph issues (explanation / suggestion / severity) and score breakdown.
- Terminology panel: each RU term carries a **difficulty** dot (Wikidata grounding: confirmed / ambiguous / not found) and a **pair-accuracy** verdict on the RU↔EN pair — two independent signals, not one.
- Accept a suggested fix → target text updates → re-score → aggregate shows ▲delta with `cached` badge.
- Reset button restores seed baseline.
- Settings: 5 evaluator criteria with model · weight · prompt; model registry with masked API keys.
- Ranking view: sort paragraphs by any criterion or aggregate.

## Quickstart

```bash
uv sync
cp .env.example .env                         # OPENROUTER_API_KEY optional — demo works on cached scores
uv run python -m palimpsest.webapp.seed      # populate data/demo.db from data/seed/seed_paragraphs.jsonl
uv run uvicorn palimpsest.webapp.app:app --port 8000
# backend → http://127.0.0.1:8000
cd frontend && npm install && npm run dev
# frontend → http://localhost:5173
```

## Stack

- **Python 3.13**, `uv`, `pyproject.toml`
- **LLM access** — OpenAI-compatible client (`palimpsest.llm.client.LLMClient`); one interface for every endpoint
- **Web — backend** — `FastAPI` + `SQLite` (`data/demo.db`); run `uvicorn palimpsest.webapp.app:app`; module `src/palimpsest/webapp/`
- **Web — frontend** — React + TipTap editor + Vite; lives in `frontend/`
- **PDF → Markdown** — pluggable `PDFParser` interface: `pymupdf4llm` (default, CPU), `docling`, `mineru`
- **Eval** — LLM-as-judge harness (`src/palimpsest/evaluation/`); judge prompt `prompts/judge.md`

## E2E test data

Seed data manifest and canonical user journeys: [docs/testing/e2e-data.md](docs/testing/e2e-data.md).

## Conventions

- **Branches** — active integration line is **`dev-demo`** (off `main`); feature work in `feat/<topic>` off `dev-demo`, merged back. Never commit directly to `main`. The old research pipeline is retired on `old-gse-translating`; archived branches are kept as `git bundle` files in `../worktree-backups/`. See [CLAUDE.md](CLAUDE.md#branches--worktrees).
- **Commits** — [Conventional Commits](https://www.conventionalcommits.org/) in English: `feat(webapp): …`, `fix(scoring): …`, `docs(readme): …`, `exp(eval): …`
- **Data** — this repo carries only the light demo seed under `data/seed/` (no Git-LFS). The heavy source corpora (`data/raw/`, `data/interim/`, `data/pilot/`) stay in the GitLab origin and are not mirrored here. `data/raw/` is immutable.
- **Glossary** — `glossary/main.json` is the single source of truth for RU→EN terminology.
- **Code** — PEP-8 + type hints, `from __future__ import annotations` in library modules. One module = one responsibility.

## Layout

```
configs/              YAML: pipeline.yaml, models.yaml
data/
├── seed/             seed_paragraphs.jsonl — demo seed data (the only heavy data mirrored)
├── processed/        per-chapter pipeline artifacts (placeholder; corpora live in GitLab)
├── external/         external reference data (placeholder)
└── feedback/         collected reviewer feedback (placeholder)
frontend/             React + TipTap frontend (Vite)
glossary/             project-wide RU→EN term store (JSON, versioned)
prompts/              stage-specific prompt templates
src/palimpsest/
├── io/               PDF parsing, paragraph splitting, artifact storage
├── llm/              OpenAI-compatible client
├── pipeline/         stage implementations + runner
├── evaluation/       judge criteria and harness
├── webapp/           FastAPI eval backend (routes, DB, seed)
└── glossary.py       glossary read/write
scripts/              CLI entrypoints (01_parse_pdf.py; pilot/)
```

Run the demo backend with `uvicorn palimpsest.webapp.app:app --port 8000` (see [docs/subsystems/webapp.md](docs/subsystems/webapp.md)).

See [CLAUDE.md](CLAUDE.md) for the full project brief, pipeline stages, and working-with-this-repo guidance.
