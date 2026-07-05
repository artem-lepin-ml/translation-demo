# CONTEXT.md — ubiquitous-language glossary

Up-link: [CLAUDE.md](CLAUDE.md).

This file is the ubiquitous-language source of truth for the demo's domain
vocabulary — the terms an agent must use consistently when talking about the
codebase, and the ones consumed by the `grill-with-docs`, `to-issues`, and
`grilling` skills. Every row below is grounded in an existing repo artifact
(doc or code); nothing here is invented. On conflict with CLAUDE.md, CLAUDE.md
wins (this file only indexes/explains terms it already defines).

## 1. Source / Translation naming (Hard Invariant 11)

User-facing labels are **"Source" / "Translation"** (optionally qualified with
a language, e.g. "Source · Russian"); the underlying code/API identifiers
stay `source_*` / `target_*`. "Original" / "target text" are not valid UI
copy.

| Term | Meaning | Code anchor |
|---|---|---|
| **Source / Translation** (UI label pair) | The two reading-pane columns: left = the untranslated text, right = its rendered translation. Always paired with a language suffix in column headers (`Source · Russian`, `Translation · English`). | [`frontend/src/demo/variant-a/VariantA.tsx:493-494`](frontend/src/demo/variant-a/VariantA.tsx#L493-L494) (`va-col-header` reading-pane headers); also the upload modal's side panels — [`UploadModal.tsx:122-124`](frontend/src/demo/variant-a/upload/UploadModal.tsx#L122-L124) (`label="Source"` / `label="Translation"`) |
| **`source_*` / `target_*`** (identifier convention) | Wire/DB field prefix pairing: `source_lang`/`target_lang`, `source_model`, `source_fragment`/`target_fragment`, `source_surface`/`target_surface`. Frontend TS mirrors it as camelCase (`sourceLang`/`targetLang`) rather than the snake_case DB form. | DDL: [`docs/superpowers/specs/2026-06-30-demo-contracts.md:208`](docs/superpowers/specs/2026-06-30-demo-contracts.md#L208) (`document.source_lang`/`target_lang`), `:228` (`issue.target_fragment`/`source_fragment`), `:234-237` (`term.source_surface`/`target_surface`); frontend camelCase form at [`VariantA.tsx:582-583`](frontend/src/demo/variant-a/VariantA.tsx#L582-L583) (`sourceLang={doc.sourceLang}` / `targetLang={doc.targetLang}`) |

## 2. `va-*` design token system

| Term | Meaning | Code anchor |
|---|---|---|
| **`--va-*` token system** | The variant-A visual design system: `:root` CSS custom properties (surface stack, accent, semantic verdict colours, radii, fonts) plus the `va-*` component classes built on them. Single source of truth for styling — new UI must reuse these tokens/classes, never invent a parallel style (CLAUDE.md § Ground before you design). | [`frontend/src/demo/variant-a/variant-a.css:4-20`](frontend/src/demo/variant-a/variant-a.css#L4-L20) (`:root` block); documented in [`docs/subsystems/webapp-ui-design.md:12-35`](docs/subsystems/webapp-ui-design.md#L12-L35) |
| `--va-bg` | Page/root background, deepest layer (`#1a1b26`, Tokyo-Night base). | [`variant-a.css:4`](frontend/src/demo/variant-a/variant-a.css#L4) |
| `--va-accent` | Primary accent blue — active tab, focused input, links, selected row, brand (`#7aa2f7`). | [`variant-a.css:12`](frontend/src/demo/variant-a/variant-a.css#L12) |
| `--va-green` / `--va-yellow` / `--va-red` | Semantic verdict triad — green/yellow/red pass-warn-fail colouring used across score bands, term difficulty and pair-accuracy verdicts. | [`variant-a.css:14-16`](frontend/src/demo/variant-a/variant-a.css#L14-L16) |

## 3. Evaluator terminology

The demo's Settings tab and API call these "criteria"/"evaluators" interchangeably; the DB table is `criterion`, one row per LLM-as-judge rubric.

| Term | Meaning | Code anchor |
|---|---|---|
| **`criterion` (DB table / evaluator)** | Wire/DB record for one LLM-judge rubric: `id, name, model_name, prompt, scale_min, scale_max, weight, color, enabled`. CRUD via `/api/criteria`; UI calls it "evaluator" ("+ Add evaluator", evaluator rows). Count is **not fixed** — it's whatever rows exist in the DB, editable at runtime. | DDL: [`docs/superpowers/specs/2026-06-30-demo-contracts.md:242-245`](docs/superpowers/specs/2026-06-30-demo-contracts.md#L242-L245); UI: [`docs/subsystems/webapp.md:62`](docs/subsystems/webapp.md#L62) (`SettingsTab.tsx` criterion editor) |
| **Seed default criteria (4)** | The demo's default seeded set, inserted by `seed.py`: `accuracy` (weight 0.30), `fluency` (0.20), `style` (0.15), `terminology` (0.20) — down from an earlier 5th ("Cultural Adaptation"), dropped in wave-4. | [`src/palimpsest/webapp/seed.py:27-34`](src/palimpsest/webapp/seed.py#L27-L34) (`CRITERIA` list + the dropped-criterion comment) |
| `judge_one` / scoring judge | Per-criterion LLM-as-judge call: reads `prompts/scoring/<id>.md`, calls the LLM, parses JSON, returns `{value, summary, issues}`. | [`src/palimpsest/webapp/judge.py`](src/palimpsest/webapp/judge.py); described at [`docs/subsystems/webapp.md:31`](docs/subsystems/webapp.md#L31) |
| **`src/palimpsest/evaluation/` module (6-criterion formula, unused by webapp)** | A separate, standalone weighted-consensus formula with 6 hardcoded criteria (`accuracy, terminology, consistency, fluency, style, culture`) and its own weights. Grepped: not imported anywhere under `src/palimpsest/webapp/` or elsewhere in `src/` — it is not wired into the live demo pipeline; the live evaluator set is the DB `criterion` table above. Flagged here rather than silently presented as "the" criteria list. | [`src/palimpsest/evaluation/criteria.py:18-24`](src/palimpsest/evaluation/criteria.py#L18-L24) (`CRITERIA` tuple + `consensus()`) |

## 4. Pipeline stage names

`docs/pipeline.md` documents two stages via `docs/stages/`; CLAUDE.md's "one stage = one module" convention names `terminology/`, `webapp/`, `evaluation/` as example stage modules. Verified against the actual `src/palimpsest/` tree:

| Term (stage) | Meaning | Code anchor |
|---|---|---|
| **Terminology** | Extract → ground (difficulty) → pair (`pairAccuracy`) → `Term[]`, end-to-end RU→EN term analysis. | Module: [`src/palimpsest/terminology/__init__.py`](src/palimpsest/terminology/__init__.py); doc: [`docs/stages/terminology.md`](docs/stages/terminology.md); indexed at [`docs/pipeline.md:9`](docs/pipeline.md#L9) |
| **Wiki-eval** | E1+E2 evaluation harness that grades the terminology grounder against Wikipedia link annotations (tokenize/wiki_gt/predict/matching/metrics/report submodules). | Module: [`src/palimpsest/terminology/evaluation/`](src/palimpsest/terminology/evaluation/) (e.g. `report.py`, `metrics.py`); doc: [`docs/stages/wiki-eval.md:11`](docs/stages/wiki-eval.md#L11); indexed at [`docs/pipeline.md:10`](docs/pipeline.md#L10) |
| **Webapp** | The demo web app (FastAPI backend + `variant-a` React frontend) that serves pipeline output for interactive review/scoring — CLAUDE.md's third named example stage module. Not a `docs/pipeline.md` row (it's the serving layer, documented separately as a subsystem). | Module: [`src/palimpsest/webapp/`](src/palimpsest/webapp/) (entry point [`app.py`](src/palimpsest/webapp/app.py)); doc: [`docs/subsystems/webapp.md`](docs/subsystems/webapp.md) |
| **`evaluation/` module (present, not a documented pipeline stage)** | Directory exists on disk (`criteria.py`, `judge.py`) but is not referenced by `docs/pipeline.md`, `docs/stages/`, or imported by the webapp (see § 3 above) — an orphaned/legacy module, not a live stage. | [`src/palimpsest/evaluation/`](src/palimpsest/evaluation/) |
