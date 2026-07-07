# Palimpsest demo — positioning & goals

Up-link: [docs/README.md](../README.md) · [README.md](../../README.md) · [CLAUDE.md](../../CLAUDE.md)

This is the L2 "why" doc for the demo: what it is, who it is built for, and the quality bar that governs every design and review decision. It does not restate architecture or contracts — those are the single source of truth in [docs/subsystems/webapp.md](../subsystems/webapp.md) and [demo-contracts.md](../superpowers/specs/2026-06-30-demo-contracts.md); this doc links to them.

## What the demo is

Palimpsest is an interactive translation-evaluation web app: a paragraph-level LLM-as-judge over a bilingual document, with a UI built for showing the evaluation loop live, not just reporting a score.

- **Seeded RU→EN document.** A Mesopotamia-pilot document with real judge output across the seeded evaluator criteria — full manifest (paragraph/criteria/term counts) in [e2e-data.md](../testing/e2e-data.md), rebuild provenance in [seed-refresh](../superpowers/plans/2026-07-02-seed-refresh.md).
- **Arbitrary-pair upload.** A user can bring their own source↔translation pair, any language pair, via paste or `.docx`/`.md`/`.txt` file upload, with a paragraph-alignment preview and merge step before the document is created — [custom-pair-upload-design.md](../superpowers/specs/2026-07-02-custom-pair-upload-design.md).
- **Issue cards with accept/dismiss.** Each judge finding is a card (explanation, suggestion, severity) the reviewer can accept (applies the suggested fix and re-scores) or dismiss — [webapp.md](../subsystems/webapp.md#improvement-loop-semantics).
- **Terminology grounding.** RU terms carry two independent Wikidata-backed signals: `difficulty` (is the term itself groundable) and `pairAccuracy` (did the translation render it correctly) — [terminology stage doc](../stages/terminology.md).
- **Precompute on upload.** A background, budget-guarded first pass scores the first 12 paragraphs of an uploaded document so it isn't blank on arrival — [webapp.md §Precompute](../subsystems/webapp.md#precompute).

## Who it is for

- **EMNLP demo-track submission** — the primary audience and the deadline driving scope (~2026-07-10, see [demo-architecture-design.md](../superpowers/specs/2026-06-30-demo-architecture-design.md)).
- **The owner's academic supervisor** — a reviewer who needs to see the evaluation loop work convincingly end to end, not just read about it.
- **Live demo audiences** — conference attendees driving the app themselves or watching a presenter drive it; the upload feature exists specifically so an audience member can bring their own text on stage.

## Quality bar and key accents

- **Honest deltas.** The first score on a paragraph (seed or precompute) never shows a delta — a delta only appears between an old and a new score, on the second evaluation onward. No manufactured "+8.1 from zero" theatrics. See [webapp.md — `aggregatePrev`](../subsystems/webapp.md#improvement-loop-semantics).
- **Budget-guarded real LLM calls.** Every live judge call goes through a hard spend/call cap (`budget.py`, $2 / 200 calls per process) plus a precompute sub-cap, so the app degrades to cached scores rather than running unbounded cost on a public demo — [webapp.md — Precompute](../subsystems/webapp.md#precompute).
- **Evidence-first e2e.** Verification runs a real browser through the full user journey (never DB-seeded via URL), against the manifest in [e2e-data.md](../testing/e2e-data.md), with screenshots as provenance for every claimed state.
- **Dark Tokyo-Night UI.** One design system, `variant-a.css`, governs every screen — see [webapp-ui-design.md](../subsystems/webapp-ui-design.md). New UI extends it; it is never reinvented in parallel.
- **English-only UI.** Frontend copy is English regardless of the language the spec was written in — see [CLAUDE.md Hard Invariants #9](../../CLAUDE.md#hard-invariants).

## Working rules for the demo

Feature work follows the standard 8-step pipeline from the global process (spec → `/verify-spec` → plan → worktree → execute → `/verify-pr` + e2e → finish), applied per `feat/<topic>` branch off `dev-demo`:

1. **Spec** in [docs/superpowers/specs/](../superpowers/specs/), reviewed by `/verify-spec` before planning.
2. **Plan** in [docs/superpowers/plans/](../superpowers/plans/).
3. **Worktree** — isolated `feat/<topic>` branch off `dev-demo`, never `main` (see [CLAUDE.md — Branches & worktrees](../../CLAUDE.md#branches--worktrees)).
4. **Verify** — `/verify-pr` aspect review plus a real-browser e2e run against [e2e-data.md](../testing/e2e-data.md), gated on an independent audit.
5. **Finish** — doc-parity check, HTML report, merge back into `dev-demo`.

See [CLAUDE.md](../../CLAUDE.md) for the full process and the project's Hard Invariants.
