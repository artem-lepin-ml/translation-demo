# Palimpsest demo — documentation index

Up-link: [README.md](../README.md)

| Document | What it covers |
|---|---|
| [docs/goals/demo-positioning.md](goals/demo-positioning.md) | Positioning — what the demo is, who it's for (EMNLP demo-track, supervisor, live audiences), quality bar, working rules |
| [docs/subsystems/webapp.md](subsystems/webapp.md) | Demo eval web app — FastAPI+SQLite backend, React/TipTap frontend, DB schema, API surface, how to run |
| [docs/subsystems/webapp-ui-design.md](subsystems/webapp-ui-design.md) | Frontend visual design system (variant-a) — dark-theme tokens, `va-*` component classes, reference screenshots, the extend-don't-reinvent rule |
| [docs/superpowers/specs/2026-06-30-demo-contracts.md](superpowers/specs/2026-06-30-demo-contracts.md) | Rev-5 contract spec — wire-DTO types, SQLite DDL, REST endpoints (single source of truth for API/data contracts) |
| [docs/superpowers/specs/2026-07-05-translator.md](superpowers/specs/2026-07-05-translator.md) · [score-history-best.md](superpowers/specs/2026-07-05-score-history-best.md) · [export-xlsx.md](superpowers/specs/2026-07-05-export-xlsx.md) · [settings-fixes.md](superpowers/specs/2026-07-05-settings-fixes.md) · [glossary-redesign-impl.md](superpowers/specs/2026-07-05-glossary-redesign-impl.md) · [upload-modal-polish.md](superpowers/specs/2026-07-05-upload-modal-polish.md) | Wave-5 feature specs (translator, revision history/best, xlsx/md export, settings hardening, glossary redesign, upload-modal polish) — deltas rolled up into the contracts spec §7 |
| [docs/reports/html/2026-07-06-wave5.html](reports/html/2026-07-06-wave5.html) | Wave-5 final PR report — 360 radar, findings, e2e evidence |
| [docs/superpowers/specs/2026-07-01-model-registry-design.md](superpowers/specs/2026-07-01-model-registry-design.md) | Model Registry design spec (v2, post `/verify-spec`) — model matrix, params filtering, budget guard |
| [docs/superpowers/plans/2026-07-01-model-registry.md](superpowers/plans/2026-07-01-model-registry.md) | Model Registry implementation plan (task breakdown) |
| [docs/superpowers/specs/2026-07-02-custom-pair-upload-design.md](superpowers/specs/2026-07-02-custom-pair-upload-design.md) | Custom pair upload — design spec (rev-4): API, DDL delta, file-ingest contract, UI flow, precompute |
| [docs/superpowers/plans/2026-07-02-pair-upload.md](superpowers/plans/2026-07-02-pair-upload.md) | Custom pair upload — implementation plan (task breakdown) |
| [docs/superpowers/plans/2026-07-02-audit-fixes.md](superpowers/plans/2026-07-02-audit-fixes.md) | Site-audit fixes + Evaluators redesign — implementation plan |
| [docs/stages/terminology.md](stages/terminology.md) | Terminology module — extract → ground (difficulty) → pair (pairAccuracy) → `Term[]` over live Wikidata; strategies, verdict rules, tournament results |
| [docs/stages/translation-eval.md](stages/translation-eval.md) | sr004 runbook for the wiki-100 LLM-judge + refinement eval (Danil's pipeline as-is) — prereqs, patches, `models.yaml` deltas, vLLM bring-up, Ф0–Ф2 phases |
| [docs/superpowers/specs/2026-07-01-terminology-e2e-design.md](superpowers/specs/2026-07-01-terminology-e2e-design.md) | Terminology e2e design spec + `/verify-spec` rework decisions |
| [docs/superpowers/specs/2026-07-01-terminology-consolidation-design.md](superpowers/specs/2026-07-01-terminology-consolidation-design.md) | Consolidation design — how the three parallel terminology efforts were merged; decisions D1–D8 |
| [docs/superpowers/specs/2026-07-01-terminology-extract-design.md](superpowers/specs/2026-07-01-terminology-extract-design.md) | Extract-stage design — real LLM-NER extractor (lowercase terms) + gazetteer fallback, NerConfig/live-re-extract contract, real-OpenRouter e2e |
| [docs/superpowers/plans/2026-07-01-terminology-extract.md](superpowers/plans/2026-07-01-terminology-extract.md) | Extract-stage implementation plan (TDD tasks) |
| ⚠️ **Removed artifact:** `docs/reports/2026-07-02-ner-model-tournament.html` | NER model tournament (7 models on real OpenRouter + adversarial judge panel; picked `claude-haiku-4.5` as the E1 default) — never committed to any branch in this repo (confirmed via `git log --all --diff-filter=A`, see [docs-keeper-wave5-doc-parity-audit2.md](reports/docs-keeper-wave5-doc-parity-audit2.md)); the tournament's conclusion is preserved as prose in [docs/stages/terminology.md](stages/terminology.md) and [docs/known_issues.md](known_issues.md) |
| ⚠️ **Removed artifact:** `docs/reports/2026-07-01-terminology-consolidation.html` | Consolidated tournament report (G3+P3, unified 99-term golden, audit, browser-e2e screenshots) — never committed to any branch; findings are preserved in [docs/stages/terminology.md](stages/terminology.md) |
| ⚠️ **Removed artifact:** `docs/reports/2026-07-01-terminology.html` | Pre-consolidation report (38-term golden, stale ~30% red figure) — never committed to any branch; superseded by the consolidation above regardless |
| [docs/testing/e2e-data.md](testing/e2e-data.md) | E2E test data manifest — seed data description, canonical user journeys, what is in and out of scope |
| [docs/superpowers/plans/2026-07-01-demo-build.md](superpowers/plans/2026-07-01-demo-build.md) | Build plan — task breakdown and implementation order for the demo |
| [docs/known_issues.md](known_issues.md) | Open limitations & gotchas — terminology descopes (GPU strategies, recall, extraction precision), live-Wikidata cache, webapp cache staleness, bundle size |
| [docs/PROBLEMS.md](PROBLEMS.md) | Systemic/complex pipeline problems log (process step 7 "Fix") — root-cause passes and tournament-picked resolutions, referenced from CLAUDE.md |
