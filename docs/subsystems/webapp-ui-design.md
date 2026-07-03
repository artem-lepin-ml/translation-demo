# Webapp UI — variant-a visual design system

Up-link: [README](../../README.md) · [docs/README.md](../README.md) · subsystem: [webapp.md](webapp.md)

**Variant A is implemented and is the current demo UI.** This doc governs its look. New UI work **extends** it — it does not replace it and does not invent a parallel style. The single source of truth for the actual values is the stylesheet [`frontend/src/demo/variant-a/variant-a.css`](../../frontend/src/demo/variant-a/variant-a.css); this doc is the routed, human-readable map of it.

## Where the design lives

- **Tokens + component classes:** [`frontend/src/demo/variant-a/variant-a.css`](../../frontend/src/demo/variant-a/variant-a.css) (one file, `:root` custom properties + `va-*` classes).
- **Components that consume them:** the `variant-a/` `.tsx` files listed in [webapp.md](webapp.md#frontend-frontendsrcdemovariant-a).
- **Rendered ground truth (open these before proposing any visual change):** [`docs/reports/e2e/shots/`](../reports/e2e/shots/) — 14 canonical shots (cold load, scores tab, accept flow, glossary, settings, ranking, variant B) — plus `shots-fixes/` and `shots-rerun/` for the most recent state.

## Design tokens (`:root` in variant-a.css)

Dark "reader" theme (Tokyo-Night family). Colours are a 3-layer surface stack + one blue accent + three semantic verdict colours.

| Token | Value | Role |
|---|---|---|
| `--va-bg` | `#1a1b26` | Page/root background (deepest layer) |
| `--va-surface` | `#1f2035` | Chrome bar, subtoolbar, inspector panel, `.va-field-input` bg (one layer up) |
| `--va-surface2` | `#24253a` | Card/row bg: evaluator rows, detail card, `.va-table` row hover |
| `--va-border` | `#2d2e4a` | Default hairline border (table cells, section-title underline) |
| `--va-border2` | `#3b3c5c` | Brighter border for inputs/buttons/dividers |
| `--va-text` | `#c0caf5` | Primary text (light lavender) |
| `--va-text-muted` | `#6272a4` | Secondary text: labels, `th`, model tags, timestamps |
| `--va-text-dim` | `#414868` | Dimmest: para numbers, empty-state, masked API key |
| `--va-accent` | `#7aa2f7` | Primary accent blue: active tab, focused input, links, selected row, brand |
| `--va-accent2` | `#bb9af7` | Secondary accent purple: term-chip "on" state |
| `--va-green` | `#3ddc84` | Positive: green verdict dot, accept buttons, score ≥ 8 |
| `--va-yellow` | `#e0af68` | Medium: yellow verdict dot, score band 6–8 |
| `--va-red` | `#f7768e` | Negative: red verdict dot, score < 6, error text |
| `--va-radius` | `8px` | Radius for larger containers (rows, cards, popovers) |
| `--va-radius-sm` | `4px` | Radius for buttons and inputs |
| `--va-font` | `'Inter', system-ui, …` | UI font for all body text and inputs |
| `--va-font-mono` | `'JetBrains Mono', 'Fira Code', monospace` | Model names, base URLs, API keys, param values |

**Per-criterion colours are data, not tokens** — each `Criterion` stores its own colour (e.g. Accuracy `#4d8dff`, visible in Settings); the full set is in the UI spec §13. Do not confuse them with `--va-accent`.

## Component class conventions

All classes are `va-`-prefixed. The reusable building blocks a new feature should compose from:

| Class | Renders |
|---|---|
| `va-tab-content` | Scrollable wrapper for a non-document tab (Glossary/Ranking/Settings); padding `32px 48px` |
| `va-settings-section-title` | Section heading (14px bold, bottom border) — used by both "Evaluators" and "Model Registry" |
| `va-table` | Reusable data table: `th` uppercase/muted with `--va-border2` underline; `td` with `--va-border` bottom + vertical-align top; row hover → `--va-surface2`. Shared by Evaluators, Model Registry, Glossary, Ranking |
| `va-eval-row` / `va-eval-chevron` | Evaluators = `va-table` rows (`va-eval-row`, pointer cursor, `.disabled` → dimmed) + click-to-expand into a nested `<tr>` with `va-evaluator-detail`; the `va-eval-chevron` ▶ rotates 90° when open. Same expand pattern as Model Registry's Test result row; collapsed by default, one row open at a time (accordion) |
| `va-field-label` | 11px uppercase muted label above an input |
| `va-field-input` (`+ va-field-select`) | Standard input: `--va-surface` bg, `--va-border2` border, `--va-radius-sm`, focus → accent border |
| `va-btn-secondary` | Ghost/outline button: transparent bg, `--va-border2` border, muted text, hover → accent border+text. Used for Edit / Remove / Reset / + Add |
| `va-btn-accept` / `va-btn-dismiss` / `va-btn-accept-all` | Semantic action buttons (accept = green, dismiss = neutral) |
| `va-verdict-dot` (`.green/.yellow/.red`) | 10px status circle mapping to the three semantic colours — used in Glossary/Ranking for pass/fail-style status |
| `va-insp-issue-card` / `-header` / `-crit-badge` / `-expl` | Bordered detail card with a coloured pill badge + explanation — the canonical "expandable per-row detail" block |
| `va-score-chip` / `-loading` / `va-score-bar-shimmer` | Async-loading indicators (pulsing `…`, shimmer bar) — reuse for any "in progress" state |
| `va-empty` | Italic dim placeholder ("No issues match the active criteria.") |
| `va-inspector-warning` | Red-tinted failure banner (`rgba(--va-red)` bg, `--va-red` border+text) — the canonical error surface. Used by the inspector's failed-criteria/evaluate-failure banners and reused as-is by `SettingsTab`'s evaluator-editor for a 409 remove-conflict message |

Loading convention: buttons show `…` while a request is in flight (e.g. `{isLoading ? '…' : 'Accept'}` in `InspectorPanel.tsx`).

## Extension rule (doc-parity)

Any new UI element **MUST reuse** existing tokens and classes from `variant-a.css` and match the look in the reference screenshots. Do **not** introduce a new colour, font, radius, or component pattern without updating **both** this doc and `variant-a.css` **in the same commit** (per [CLAUDE.md](../../CLAUDE.md) doc-parity + the "ground before you design" invariant). Prefer composing existing `va-*` classes over inline styles; use inline styles only for one-off layout, matching the pattern already in the neighbouring component.

## Relationship to the UI spec

[`docs/superpowers/specs/2026-06-30-palimpsest-demo-ui-design.md`](../superpowers/specs/2026-06-30-palimpsest-demo-ui-design.md) is the **historical decisions log** (rationale, prior art, layout choices, criterion-colour set §13). This file is the **current living reference** for the as-built styling. Where the two disagree, this file and `variant-a.css` win; the spec's §12 as-built paths are stale (code moved to `frontend/src/demo/variant-a/`, screenshots to `docs/reports/e2e/shots*/`).
