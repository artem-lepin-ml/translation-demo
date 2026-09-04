# e2e-tester report: T8 — custom judge criterion (mega-campaign)

## Scope

Ran scenario T8 of the approved e2e mega-campaign (`docs/superpowers/specs/2026-07-17-e2e-mega-campaign.md`)
against live prod https://glossa-mt.com. Goal: verify the article's "add any
arbitrary criteria" claim end-to-end — UI path for adding a judge criterion,
weight renormalization, live evaluate with 4 criteria, hand-verified aggregate
arithmetic, disable/delete lifecycle, full cleanup with byte-restore proof.
Session: named playwright-cli session `t8`, ephemeral DB clone via `glossa_sid`
cookie `2943cf60-599f-4a03-939d-a86db535cc1d` (no `X-Golden-Session` used).

## Files changed

None in the app repo (read-only investigation + live prod interaction). Artifacts
written:
- `docs/reports/e2e/campaign/t8-custom-criterion.md` — Russian owner-facing report (main deliverable)
- `docs/reports/e2e/campaign/t8-payload.txt` — GENERATED upload payload (anachronism pair)
- `docs/reports/e2e/campaign/t8-criteria-baseline.json` — GET /api/criteria before any change
- `docs/reports/e2e/campaign/t8-criteria-after-delete.json` — GET after criterion delete
- `docs/reports/e2e/campaign/t8-criteria-restored-summary.txt` — GET after weight restore
- `docs/reports/e2e/shots/campaign/t8/*.png` — 17 screenshots

## Decisions & rationale

- **Owner-decision item 2 fallback not triggered.** The campaign spec's pre-approved
  fallback (API+UI verification if "Add criterion" button is absent) turned out
  unnecessary — the button (`+ Add judge`) exists and is fully wired to
  `POST/PUT/DELETE /api/criteria`. I used the UI path throughout, matching the
  spirit of "make existing things work" — no API-only shortcuts needed for CRUD.
- **Did not delete accuracy/fluency/style** to test the 409-on-history-exists
  guard, per `.claude/rules/invariants.md` ("never delete LLM predictions").
  Verified that code path by reading `app.py::delete_criterion` instead of a live
  call; documented honestly as "verified via code, not live run."
- **Root-caused the critical bug via local code reproduction**, not just
  observation: read `judge.py::_scoring_prompt()`, confirmed
  `prompts/scoring/{criterion_id}.md` only contains `accuracy.md`/`fluency.md`/`style.md`,
  and reproduced the exact `FileNotFoundError` locally with the real criterion id
  from the live POST response. This is the strongest possible evidence short of
  server logs (which I don't have access to) — chose it over speculating from the
  `failedCriterionIds` field alone.
- **Corrected a mid-run false claim.** I initially told the user "zero error
  signal" for the failure before checking the Inspector panel screenshot closely;
  a red "Failed: crit-… / Retry failed" banner is actually present there. I
  explicitly walked this back in the transcript and in the report (finding #2 vs
  my initial wrong assumption) rather than let a stale claim stand — this matters
  because the Iron Law forbids uncorrected inaccurate claims.
- **Attributed the double-DELETE finding to a known recurring pattern** already
  in my cross-project memory (`translation-demo-bugs.md`) rather than treating it
  as new — noted it's now the 6th observed occurrence, and noted the delete of
  the T8 document itself did NOT double-fire (nondeterministic repro, worth
  flagging honestly rather than overclaiming 100% reproducibility).

## Open questions

- Whether `prompts/scoring/{criterion_id}.md` should be auto-generated from the
  UI-submitted `prompt` field at criterion-creation time, or whether the intended
  design was always "custom criteria are UI-only decoration, judge prompts are
  developer-authored files" — this is a product decision, not something I can
  resolve from the code alone. Flagged as CRITICAL either way since the current
  UI actively invites users to type a rubric that is silently discarded.
- Whether the process-global `precompute_calls` budget counter (finding #5) is a
  known/accepted tradeoff for the demo's cost-control design, or an oversight —
  the mega-campaign's concurrent multi-session load exposed it, but a single real
  user session might never hit it.

## NOT done (explicit)

- Live 409-on-delete-with-history test (rationale above — invariant conflict).
- Live evaluate with intentionally unnormalized weights summing >1.0 (I
  renormalized to 1.0 before the first evaluate call; closed by reading
  `aggregate.py`'s division-by-`den` formula instead, not a live measurement).
- Any write access to server logs / process internals beyond what `curl`+API and
  local source reading could establish — no SSH access was used or needed for
  this scenario (unlike some prior campaign runs in memory).
- Did not attempt to fix the root-cause bug — out of scope for e2e-tester; this
  is a finding for the fastapi-developer/backend lane to pick up.
