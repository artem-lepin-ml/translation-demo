# Canonical review aspects catalog + mechanics rules

Single source of truth. Used by the `/verify-spec` (step 2) and `/verify-pr` (step 6) skills.
The project adaptation lives in `<repo>/docs/superpowers/review-aspects.md`.

## Catalog

| # | Aspect | Applies (a hint, not a prescription) |
|---|---|---|
| 1 | Goal & constraints tracing: goal as a verifiable state; non-goals; no goal parts without tasks; no constraints without a check; no actions outside the result | always (strongly recommended in any set) |
| 2 | Product layer: who gets the value, actors/roles, features/epics, link to scenarios | user-facing changes |
| 3 | System layer: C4 elements, boundaries/owners, contracts, ADRs, capability duplication | ≥2 modules or a new contract |
| 4 | Engineering layer: abstractions, mixed responsibilities, standards, side effects, error policy, observability | executable code present |
| 5 | Data/storage: migrations/backfill, schema-existence proof, backup/rollback, races/idempotency | schema/seed/migrations change |
| 6 | Interface: screens/screen_id, specifications, stable test ids, UI contracts, browser proof floor | touches the frontend |
| 7 | User documentation: doc-parity, freshness, the L4 convention, single source of truth | always |
| 8 | Operations layer: branches/PR/CI, beta gate, secrets, operational evidence | always before merge |
| + | Project-specific custom aspects | per project analysis |

Mandatory rules for typical custom aspects:
- **Legacy:** find and report candidates with evidence; cleanup ONLY after the owner's explicit confirmation, never autonomously (except cases separately allowed by the owner's "AUTONOMOUS OVERRIDE" rule).
- **R&D / business vision:** technology hypotheses, approach comparison, alignment with the product direction — not just "vision compliance".

## Findings format (uniform for all aspect agents)

`{aspect, severity: CRITICAL|HIGH|MEDIUM|LOW, confidence: 0..1, evidence: quote with path/line, fix: concrete proposal}`

A bare "all good" is not accepted: an empty result = an explicit "no findings on these specific checked items".

Severity scale: CRITICAL — invariant/goal violation, blocks the base scenario; HIGH — requirements conflict, unverifiable criterion, security/data hole; MEDIUM — terminology drift, uncovered edge case, underspecification; LOW — style, minor redundancy.

## Mechanics rules (both skills)

1. Every aspect agent starts with a FRESH context: the task is self-contained (spec/diff path, the aspect's questions/checks, the findings format). The agent has no session history.
2. One subagent = one aspect = one task = one report.
3. Aspect selection is the orchestrator's call: by the spec/PR content, minimum 3 for a spec (/verify-spec), minimum 5 for final testing (/verify-pr). Chosen and consciously skipped aspects are recorded in the report, one line with a reason each.
4. Aggregation (the orchestrator itself or a `model: opus` subagent, effort high): dedup across aspects (a match from different aspects raises confidence); final severity = MAX, not average; agent contradictions → a separate "agents disagree" section. With >8 launched aspects — clusters: (A) product/UX (2, 6 + product customs), (B) architecture/data (3, 4, 5), (C) goal/quality/operations (1, 7, 8); each cluster is folded by a Sonnet-high aggregator, the final summary by the orchestrator/Opus.
5. Plan rework (mandatory step): after aggregation the orchestrator amends the spec/plan — closes the holes, moves decisions into the text, logs forks to the D-journal.
6. Gate: unresolved CRITICAL/HIGH → step 7 (Fix) / spec rework; only MEDIUM/LOW → proceed.

## Generating the project file `docs/superpowers/review-aspects.md`

1. Context gathering by 2–3 parallel subagents (Haiku/Sonnet): docs/ (README, subsystems, features), the project CLAUDE.md, specs and reports from the last ~14 days, `graphify-out/GRAPH_REPORT.md` (if present), dialog memory (if available).
2. Select the applicable aspects from the catalog + generate project-specific custom ones.
3. For each aspect write: (a) when it applies; (b) questions for SPEC review; (c) checks for final PR testing; (d) a link to the severity scale.
4. Regeneration is careful: sections marked `<!-- custom -->` (the owner's manual edits) are carried over unchanged; only the canonical part is regenerated.
5. The file is committed to the project repo. The file language follows the project docs language (Russian).
