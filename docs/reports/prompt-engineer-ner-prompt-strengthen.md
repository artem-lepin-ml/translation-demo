# prompt-engineer — strengthen NER prompt for oblique cases and multiword geo names

Date: 2026-07-10. Branch: `claude/ner-translation-config-b0ozsc`. Commit: `6039325`.

## Scope

Mechanical application task, dispatched by the orchestrator with the exact new
`NER_SYSTEM_PROMPT` text pre-authored (verbatim, no rewording/improvement
authorized). Source: pilot miss-review
(`docs/reports/wiki-eval-v2-pilot-ner-vs-disambig.md` §D + 64-case review)
found two systematic NER gaps, owner-confirmed as real prompt defects:

1. Names in oblique grammatical cases get skipped, especially when another
   case form of the same entity was already extracted nearby, and in
   coordinated lists (e.g. «пережило Ассирию и Урарту» → only Урарту
   extracted).
2. Multiword geographic names («Армянское нагорье», «Малая Азия») get
   skipped, likely misread as standalone adjective + generic noun.

Task = (1) replace the prompt verbatim in code, (2) doc-parity in the same
commit, (3) run tests, commit, push. No spec/plan/verify-spec steps run for
this task — it is scoped as a mechanical, fully pre-specified application by
the calling orchestrator, not a new Scenario A/B cycle.

## Files changed

| File | Change |
|---|---|
| [src/palimpsest/terminology/extract.py](../../src/palimpsest/terminology/extract.py) | `NER_SYSTEM_PROMPT` replaced verbatim (lines ~36–124): new `place` category examples (multiword geo names), adjective-in-name carve-out in "What NOT to extract", three new rules under "Rules" (grammatical case never a skip reason; extract every name in coordinated lists; don't skip a repeat entity in a different case form), dedup rule reworded to clarify different case forms are different surfaces, "Good example" → "Good examples" (plural) with one new invented few-shot example (Darius/Iranian plateau/Lydia-Caria-Lycia). |
| [docs/paper/sections/appendix-prompt-ner.tex](../paper/sections/appendix-prompt-ner.tex) | Figure body synced verbatim to the new prompt (same diffs as above); LaTeX wrapper, literate-mapping comment, `\caption`/`\label` left untouched — caption text doesn't reference example count so needed no edit. |
| [docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md) | §3.1: did NOT rewrite the historical prompt snapshot (by design — it documents what the pilot actually ran); inserted the exact bracketed `[AMENDED 2026-07-10, ...]` note above the fenced block, pointing to code as SSOT and flagging a comparability break for future runs vs. the 2026-07-10 pilot. |

## Decisions & rationale

- **Verbatim byte-check.** After the first `Edit` call I introduced a
  self-inflicted typo (`religious` → `религиозные` in the `religion` category
  line) while retyping the block. Caught it on re-read, fixed it, then did a
  full `diff` of the imported `NER_SYSTEM_PROMPT` string against a
  scratch-file copy of the exact BEGIN/END spec text — result `IDENTICAL`.
  This check is why the deliverable can be trusted as truly verbatim rather
  than "verbatim modulo memory."
- **Spec file kept as a historical snapshot, not rewritten.** The task
  instructions were explicit: "do NOT rewrite the spec's prompt text; insert
  a short bracketed amendment note directly above it." Rationale (inferred
  from the note's own wording): the spec documents what the pilot actually
  ran; rewriting it in place would make the spec silently lie about pilot
  provenance. Code remains the single source of truth per the amendment
  note and per this repo's SSOT convention (CLAUDE.md § Documentation).
- **Grep-and-report, update only true copies.** Searched for
  `source-criticism historian`, `NER_SYSTEM_PROMPT`, `докерамический`,
  `One record per UNIQUE surface`, `Good example` repo-wide. Found 16 hits;
  classified each:
  - True copies needing sync: the two doc files above (already fixed).
  - Symbol references only (not prompt-body copies), left untouched:
    `docs/stages/terminology.md`, `docs/stages/wiki-eval.md`,
    `docs/known_issues.md`, `docs/runbooks/sr004-local-eval-runbook.md`,
    `scripts/wiki_eval.py`, `scripts/term_pipeline.py`,
    `tests/test_wiki_eval_runner.py`, `tests/test_terminology.py`.
  - Historical/dated report artifacts documenting the *old* prompt's
    behavior (frozen evidence of the bug being fixed, must not be
    retroactively edited): `docs/reports/html/wiki-eval-v2-ner-miss-review.html`,
    `docs/reports/prompt-engineer-ner-miss-review-term-class.md`,
    `docs/reports/python-pro-ner-translation-config.md`,
    `docs/reports/docs-keeper-wiki-eval-v3-doc-parity.md`,
    `docs/reports/python-pro-wiki-eval-runner-rework.md`.
  - README.md: no match, nothing to do.
  - Webapp seeds: no match under any `seed*` path, nothing to do.
- **Untracked file left alone.** `docs/reports/html/wiki-eval-v2-ner-miss-review.html`
  was already untracked in the working tree before this task started (not
  created or touched by this task) — per the shared-index caution in the
  task brief, it was not staged.
- **Commit scope.** Staged only the 3 changed files explicitly; one
  Conventional Commit, English, no AI signature/co-author trailer per Hard
  Invariant 7.

## Open questions

- None outstanding for this mechanical task — the prompt text, doc-parity
  targets, and commit/push instructions were all fully specified by the
  dispatching orchestrator.

## NOT done (explicit)

- No `/verify-spec`, `/verify-pr`, or `e2e-tester` run — out of scope for a
  mechanical, pre-specified prompt-text application; this is not a new
  Scenario A/B cycle and the calling orchestrator did not request those
  steps.
- No live LLM re-run of the new prompt against the pilot corpus to confirm
  the fix actually resolves the two miss classes — the task was explicitly
  "apply verbatim," not "evaluate." Owner/orchestrator should schedule a
  fresh wiki-eval pilot run against the amended prompt if empirical
  confirmation is wanted (the spec's `[AMENDED ...]` note already flags this
  comparability gap).
- No PR opened — task brief asked only for commit + push to the existing
  cloud-session branch `claude/ner-translation-config-b0ozsc`, not for PR
  creation.
