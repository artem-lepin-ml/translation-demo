# Report — P_label (P3\exact) computed for the gpt-5.4 grounding run (maxlag cleared)

## Scope

Conditional task: compute the missing P_label (P3, label-justified precision) for the
finished `openai/gpt-5.4` grounding run (99/100 articles, `--no-sitelink` from the
start, sitelink-clean by construction), which `docs/reports/ml-engineer-grounding-run-gpt54.md`
(commit `5546459`) disclosed as parked on Wikidata `maxlag` (5.3s→10.4s, `wdqs1011`/
`wdqs1014`, ~06:30-07:00Z). Two-branch task: probe `maxlag` first and STOP if still
degraded, else compute and append the number. Shared worktree
(`claude/ner-translation-config-b0ozsc`) — other agents run BOUQUET judges and
doc/paper maintenance concurrently; only this task's own new paths touched.

**Outcome: healthy replicas, P3 computed.** P_label = **0.5362** (3773/7037,
Wilson 95% CI [0.5245, 0.5478]).

## Files changed

- [reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/metrics.99of100.json](../../reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/metrics.99of100.json)
  — updated in place: added `precision.p3_ex` (the headline cell), added
  `meta.p3_label_exists_degraded_count`/`p3_computed_at`/`p3_network_calls`/
  `p3_unique_surfaces_needing_lookup`/`p3_elapsed_s`/`p3_label_cache_path`/`p3_note`.
  Verified `recall`/`precision.p1`/`precision.p2` unchanged before/after the edit
  (diffed programmatically, values byte-identical). The existing stub-based (all-`False`)
  per-`resolved_by`-slice `p3` cells were deliberately **not** recomputed — see Decisions.
- [reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/report.99of100.html](../../reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/report.99of100.html)
  — regenerated via the harness's own `evaluation.report.render_html` against the
  updated metrics dict; the "P3\exact headline" section now renders `0.536` instead of
  being absent.
- [docs/reports/ml-engineer-grounding-run-gpt54.md](ml-engineer-grounding-run-gpt54.md)
  — dated addendum section appended at the end (existing text untouched, per
  instruction): probe evidence, invocation rationale, resilience pattern, scale/cost,
  the result table, caveats.
- `docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay/.wikidata_cache.label_exists.openai--gpt-5.4--auto.jsonl`
  (new, 1600 lines) — the established cache-naming convention ("next to the others"),
  append-only, `_fetch`'s own `_store` (success-only writes).
- This report.

**Not touched**: `reports/bouquet/**`, `docs/paper/`, `scripts/wiki_eval.py`,
`scripts/sitelink_contamination.py`, `src/palimpsest/terminology/wikidata.py`, or any
other file already modified/untracked by a concurrent agent in this worktree (checked
`git status` before staging; only this task's own paths were added).

## Decisions & rationale

- **Probed `maxlag` before touching anything** (task step 1): `wbsearchentities` with
  `maxlag=5` (the harness's own threshold, `wikidata.py:88`) succeeded at `08:18:03Z`
  (0.63s); a stricter `maxlag=1` probe surfaced the actual lag number (4.27s on
  `wdqs1019`, down from the 5.3s→10.4s trend the base report documented ~1.5-2h
  earlier); three more spaced `maxlag=5` calls all succeeded fast (0.27-0.5s). Healthy
  — proceeded to step 2 rather than the parked-disclosure path.
- **Headline-only, not the full `report --p3` recompute.** `scripts/wiki_eval.py report`
  hardcodes `pred_dir / "pred.jsonl"`, which this run never wrote (only
  `pred.partial.jsonl`, 99/100). Rather than materializing a `pred.jsonl` inside the real
  run dir (risking a naming collision with the harness's own eventual 100/100 completion
  output — the ml-engineer report went out of its way to avoid exactly this with the
  `*.99of100.*` naming), I read `pred.partial.jsonl` directly (md5-verified identical to
  the frozen snapshot the existing `metrics.99of100.json` was already built from) and
  reused `metrics.aggregate_corpus`'s own private accounting function
  (`_precision_counts_p3_ex`) directly rather than calling
  `aggregate_corpus(articles, label_exists=...)` in full. The full call also recomputes a
  REAL per-`resolved_by`-slice P3 for every slice, including the huge, tautological
  `exact_label` one (`metrics.py`'s own module docstring: "P3 is tautological on the
  exact_label resolution path... never reported as an unsliced aggregate" — but the
  per-slice code path still queries it) — `scripts/sitelink_contamination.py`'s module
  docstring documents this exact pitfall driving live call counts to ~1.7x the needed
  amount (gemini: 4014 actual vs 2419 estimated) for zero requested benefit, since the
  task's deliverable is specifically "P_label (value, matched/total, binomial 95% CI)",
  i.e. the one headline cell. I judged following that precedent's avoidance strategy
  correct rather than faithfully reproducing `cmd_report --p3`'s full behavior at ~1.7x
  the network cost for numbers nobody asked for.
- **Reused `_resilient_label_exists` verbatim** (commit `4770157`,
  `scripts/sitelink_contamination.py`) rather than patching
  `scripts/wiki_eval.py::_label_exists_fn` (a shared file with concurrent edits from
  other agents, per the base report's own "NOT touched" list) or
  `src/palimpsest/terminology/wikidata.py::_fetch` (already carries one fix from this
  run's own tail, and the base report's "Open questions" explicitly deferred a maxlag
  retry-budget redesign to "someone with more time/less pressure"). Wrapping outside
  `_fetch` — the precedent's own approach — needed no shared-file edit at all: a
  standalone script in the tool scratchpad (ephemeral, matching this repo's own
  `scratchpad/*.py` convention the base report already used for `r_term_tier.py`).
- **Cache placement**: `docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay/.wikidata_cache.label_exists.openai--gpt-5.4--auto.jsonl`
  — the task instructions explicitly said "next to the others", and every existing
  `.wikidata_cache.label_exists.*` file lives in exactly that directory (`deepseek`,
  `gemini-3.1-flash-lite`, `qwen3.7-plus`). Followed literally rather than scoping a new
  location under the run dir itself.
- **Model slug**: `openai--gpt-5.4--auto` — this run has no `meta.json` (never written;
  `cmd_run` only writes it on clean 100/100 completion), so `_model_slug`'s own
  documented fallback (`pred_dir.resolve().parents[1].name`) applies, which is exactly
  the run-dir's own `<model-slug>/<config>/<run_id>/` layout segment already used
  throughout the base report.
- **Wilson CI**, not a plain normal-approximation binomial CI: `eval_harness.wilson_ci`
  is the harness's own convention for every other cell in this report (R_strict, R_span,
  R_doc, P1, P2 all use it) — matching it keeps P_label directly comparable, and is what
  "per the harness convention" in the task instructions means concretely.
- **Did not touch the base report's "NOT done" P3 bullet or "Open questions" P3 entry**
  (instruction: "do not rewrite the existing text") — the addendum supersedes them in
  effect but the original text stays as a historical record of the parked state.

## Run evidence

- Needed-surface count (exact, zero-network, via a collecting stub through the real
  `_precision_counts_p3_ex` accounting): **1603 unique surfaces**.
- Live pass: `08:23:47Z` → `08:35:07Z` (**671.2s**, ≈11.2 min), concurrency 3
  (`ThreadPoolExecutor`, matching `sitelink_contamination.py`'s default), prewarm then a
  single-threaded final accounting pass over an already-warm cache.
- **1771 network calls, 3 failures (0.19%)** — all the same transient cause (`maxlag` on
  `wdqs1016`, 5.52s lagged, mid-pass on surfaces "Греция"/"Сицилия"/"Малую Азию"),
  correctly fell back to conservative `False` (never silently counted as
  label-justified) rather than crashing the whole pass — contrast with the base report's
  aborted attempt (23/23 failures in ~5 min under the earlier, worse degradation).
- New cache file: 1600 lines (1603 unique minus the 3 that never got a successful
  response to cache — `_fetch`'s `_store` is success-only, no negative-caching, exactly
  the base report's own "Open questions" limitation).
- Result: **P_label / P3\exact = 3773/7037 = 0.5362, 95% CI [0.5245, 0.5478]**
  (`underpowered: false`, n well above the 30-count threshold).
- Verification commands run:
  - `python3 -c "..."` diffing `recall`/`p1`/`p2` cells before/after the JSON edit —
    confirmed byte-identical.
  - `grep -o "P3.\{0,80\}"` on the regenerated HTML — confirmed the `0.536` headline
    cell renders.
  - `wc -l` on the new cache file — 1600, matching `1603 - len(failures)`.

## Open questions

- Same as the base report's own "Open questions": the `maxlag` uncaught-`RuntimeError`
  gap in `wikidata.py`'s `_fetch` is still unpatched (this task worked around it, not in
  it — same choice the base report made for the same reason). Article 100 ("Яффа") is
  still ungrounded; out of scope here.
- The per-`resolved_by`-slice `p3` cells in `metrics.99of100.json` remain stub-based
  (all `False`) — if a future task wants those real too, it would need the full
  `aggregate_corpus(..., label_exists=...)` call at the ~1.7x network cost this task
  deliberately avoided; not attempted.

## NOT done (explicit)

- **The per-`resolved_by`-slice P3 cells were not recomputed with the real predicate**
  — only the headline `p3_ex` cell (this task's actual deliverable) was computed for
  real. See Decisions.
- **Article 100 ("Яффа") is still ungrounded** — this task only retried the P3 pass the
  base report parked; grounding the missing article was never in scope here.
- **No edits to shared files** (`scripts/wiki_eval.py`, `scripts/sitelink_contamination.py`,
  `src/palimpsest/terminology/wikidata.py`) — the resilient wrapper was reused via a
  standalone scratchpad script, not by patching any of them.
