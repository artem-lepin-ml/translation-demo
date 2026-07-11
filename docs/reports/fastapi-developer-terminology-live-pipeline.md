# FastAPI developer report — live terminology pipeline (lane B2, EMNLP demo sprint)

Branch: `feat/emnlp-demo-sprint` (shared worktree, 4 concurrent lanes). Commit: `8ed49ef feat(webapp): run terminology pipeline live on document creation`. Not pushed.

## Scope

Make terminology LIVE: when a new document is created (upload or AI-translate), the
terminology pipeline (NER → Wikidata candidates → disambiguation → target pairing)
runs automatically in the background and term rows appear for the frontend, exactly
like the precomputed seed document's terms. Existing documents (in particular the
seed document) keep their precomputed terms untouched. Full task text: the "MISSION"
brief for lane B2 in the dispatching orchestrator's prompt (7 numbered tasks:
`_grounding_judge_live` system-prompt fix, `terminology_live.py` module, migration +
serializer for `terms_status`, dead-stub removal, tests, one live smoke test,
doc-parity).

Out of scope (explicitly, per the task's own file-scope boundaries): frontend/,
`migrate.py`'s overall step ordering/flow (owned by lane B1), criteria/model/refiner
endpoints in `app.py` (lane B1), DELETE-route wiring for task cancellation (outside
my authorized app.py regions).

## Files changed

New:
- `src/palimpsest/webapp/terminology_live.py` (316 lines) — the live pipeline module.
- `tests/test_terminology_live.py` (363 lines, 11 tests) — mocked LLM + mocked
  WikidataClient, no network.

Edited:
- `src/palimpsest/webapp/app.py` — imports (`DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT`,
  `terminology_live`); `_grounding_judge_live` now sends the real system prompt
  instead of `""`; new `_terms_launch_after_translate` helper; `create_document`
  writes `terms_status='running'` + launches for non-translate docs, passes the new
  helper into `translate.launch` for translate:true docs; `_doc_dict` exposes
  `termsStatus`; removed the dead `POST /api/paragraphs/{pid}/terms` stub route and
  its now-stale section header.
- `src/palimpsest/webapp/translate.py` — `launch`/`run_translation`/`_run` gained an
  optional `terms_launch=None` callback, invoked once at the successful end of a
  translate run.
- `src/palimpsest/webapp/db.py` — `document.terms_status TEXT NOT NULL DEFAULT
  'none'` added to `SCHEMA` (fresh-DB source of truth).
- `src/palimpsest/webapp/migrate.py` — `_add_document_terms_status_column` (guarded
  `ALTER TABLE`) + `_backfill_seed_document_terms_status` (`UPDATE ... WHERE
  origin='seed'`), appended to the `migrate()` step list.
- `tests/test_migrate.py` — 3 new tests for the column/backfill/idempotency.
- `tests/test_translator.py` — 1 test's monkeypatched `translate.launch` lambda
  widened to accept the new optional arg (was strict 2-arity).
- `tests/test_terminology.py` — replaced wholesale with the version from
  `origin/claude/ner-translation-config-b0ozsc` (see Decisions below).
- `docs/stages/terminology.md` — new "Live trigger (webapp, 2026-07-11 EMNLP
  sprint)" section + a correction to the `extract.py` Interface code block (stale
  pre-pin symbol names).
- `docs/subsystems/webapp.md` — new `terminology_live.py` module-table row, new
  "Live terminology" section, route-table row removed, "Term stub" bullet replaced.
  **Note:** this file's diff against HEAD is now empty — another lane's commit
  (`11effc9 feat(webapp-ui): rebrand to Glossa-MT...`) landed on top of the shared
  working tree while my edits were present and swept them in; the content is
  verified intact in the current HEAD (`git show HEAD:docs/subsystems/webapp.md`),
  just not under my own commit hash. Not re-committed to avoid a duplicate/no-op
  commit.
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` — `Document.termsStatus`
  added inline to the §1 `Document` interface; the stub route's REST-list lines and
  §5's one now-incorrect sentence fixed; a new unnumbered "Live terminology delta
  (2026-07-11, EMNLP-demo sprint — lane B2)" section appended (deliberately not
  numbered `## 8.`/"rev-6" to avoid a heading collision with lane B1's own
  concurrent delta for refiner/criteria, per the task's explicit instruction).

Explicitly NOT touched: `frontend/`, migrate.py's step *ordering*/other lanes'
functions, app.py's criteria/model/refiner regions.

## Decisions & rationale

**Reuse, not reimplementation.** `terminology_live.py` calls `pipeline.run()`
(frozen) with an unmodified `LabelFirstGrounding(wd, config=GroundingConfig())`
(plain defaults — `search_mode` stays `"baseline"`, the pinned config) and
`LinkLocatePairing(wd)` (P1, deterministic, no extra judge call). I verified this is
the *exact* strategy pair `scripts/term_pipeline.py`'s `cmd_run` used to generate
`data/seed/terminology_out.json` (loaded into the `term` table by
`scripts/load_terms.py`), so difficulty/pairAccuracy semantics match the seed
pipeline by construction — I don't compute difficulty myself at all;
`LabelFirstGrounding.ground()`'s own decision table already returns the correct
green/yellow/red.

**Correction to the task brief.** The task pointed at `scripts/enrich_seed_terms.py`
as the pairing reference. I traced it and found it is NOT that: it only enriches the
older `data/seed/seed_paragraphs.jsonl` mock structure with grounding
(qid/resolved_by/candidates), has zero pairing logic, and never writes to the `term`
table. I flagged this explicitly in `docs/stages/terminology.md`'s new section and
used `term_pipeline.py`/`link_locate.py`/`verdict.py` as the real reference instead.

**Async/sync bridge.** `pipeline.run()`/`LabelFirstGrounding.ground()` are
synchronous by design (same code path as the offline `scripts/wiki_eval.py` eval
harness). The live disambiguation judge must go through `app._grounding_judge_live`
(async — shares `budget`'s asyncio-lock-based reserve/settle with every other live
call). Design: each paragraph's whole `pipeline.run()` call runs inside
`asyncio.to_thread` (also keeps `WikidataClient`'s blocking `urllib` calls off the
event loop); the plain-sync `Judge` closure it receives schedules
`_grounding_judge_live` back onto the original event loop via
`asyncio.run_coroutine_threadsafe(...).result()`, blocking only that worker thread.
Verified by `test_run_disambiguation_judge_bridge_resolves_yellow` (mocked) and the
live smoke (real).

**`document.terms_status` as a DB column, not an in-memory registry** (unlike
precompute/translate) — survives a process restart. `terminology_live.try_start()`
does the atomic `'none'→'running'` transition under `db._lock`, guarding a resumed
`POST .../translate` from re-triggering the pipeline. `create_document` writes
`'running'` inline (same already-held lock, no reentrant-lock risk) since a brand-new
`doc_id` can't race; `translate.py`'s hook uses `try_start` since it isn't holding
`db._lock` at that point.

**NER reuses `grounding_config`'s model** (no separate NER-config DB surface exists;
matches the task's explicit instruction). I floor its `max_tokens` at 2048
(overriding `grounding_config.params_json`'s own value only for this call) —
`grounding_config` is tuned for the judge's short `{"qid":...}` reply, and reusing it
verbatim for NER's potentially-long `[{surface,lemma,category}, ...]` array would
silently truncate mid-JSON and turn every paragraph into a parse failure. This is my
own judgment call (not explicitly specified), documented in code + docs.

**Test replacement.** `tests/test_terminology.py` failed 2 tests purely from the
module pin (`CATEGORIES`/`DEFAULT_NER_PROMPT` renamed to `NER_CATEGORIES`/
`NER_SYSTEM_PROMPT`+`ner_user()`, and `category="nonsense"` now normalizes to
`"other"`+`category_raw` instead of `None`) — replaced wholesale via `git checkout
origin/claude/ner-translation-config-b0ozsc -- tests/test_terminology.py` per the
task's explicit authorization. `tests/test_wikidata_client.py` was NOT replaced —
diffed byte-identical against that reference branch already, nothing to do.

**Git hygiene in a shared-index worktree.** All 4 lanes share one `.git` index, not
just the working tree. A plain `git add app.py/db.py/migrate.py/test_migrate.py`
would have swept up other lanes' uncommitted work under my commit. I reconstructed
"HEAD + only my own edits" for each shared file (replaying my exact `old_string`→
`new_string` pairs against `git show HEAD:<path>`, verified each compiled and diffed
to only my intended lines), staged that reconstruction, committed, then restored the
combined working tree — verified via `git diff --cached`/`git show --stat HEAD`
after the fact that the commit contains exactly my 11 files and nothing of lanes
B1/C1/C2's concurrent work. Mid-process the shared index was also externally reset
once (another lane committing mid-session moved HEAD 4 commits forward) — re-ran the
reconstruction against the new HEAD before the final atomic stage+commit+restore.

## Live smoke result

Ran a standalone script (scratchpad only, not committed) against the real configured
endpoint (`.env`'s `OPENROUTER_BASE_URL` = CloseRouter gateway) and real Wikidata:
`qwen/qwen3.6-27b` (seeded `grounding_config`/`DEFAULT_CRITERION_MODEL`) and
`google/gemma-3-27b-it` both 404'd on this endpoint; fell back to
`deepseek/deepseek-v4-flash` per the task's own contingency instruction. Extracted 3
mentions from a test sentence (0 dropped as non-substrings), grounded with
`resolved_by` counts `{'llm_disambiguation': 2, 'exact_label': 1}` (real judge calls
succeeded and were honored), 7 live Wikidata calls total. This validates the
extract→ground plumbing end-to-end against real services before prod.

**Operational flag for the owner:** today, on this endpoint, the seeded default
model is not reachable — live terms generation will fail for every paragraph until
`grounding_config` is repointed at a working model via Settings (or the endpoint
changes). Not a bug in this PR's code; a pre-existing config/endpoint mismatch this
smoke surfaced.

## Test results

- Task-required scope (`-k "terminology or wikidata or documents_create or
  precompute or translate"`, ignoring pre-existing broken collection files):
  **164 passed**.
- `tests/test_terminology_live.py` alone: **11 passed**.
- Full suite (same 3 files ignored): **555 passed, 0 failed** (final state, after
  other lanes finished their own in-flight model-registry/criteria-collapse work
  that had transiently broken ~6-31 unrelated tests mid-session — verified via a
  `git stash`/pop A-B comparison early on that those failures reproduced identically
  with my changes removed, i.e. were never caused by this work).
- Ignored (pre-existing, predates this task, unrelated): `tests/test_wiki_eval_runner.py`,
  `tests/test_wiki_metrics.py`, `tests/test_wiki_report.py` fail to *collect* — they
  import `DEFAULT_NER_PROMPT`/`_precision_counts_p3_ex`/`methodology_draft` from the
  terminology module, names that don't exist post-pin. Not fixed (out of scope; the
  offline `scripts/wiki_eval.py`/`evaluation/metrics.py`/`evaluation/report.py`
  modules these tests exercise are entirely outside this task).

Lint: `ruff check` clean on `terminology_live.py`/`test_terminology_live.py` except
one `UP017` (`datetime.now(timezone.utc)` vs `datetime.UTC`) — left as-is,
matches the existing codebase-wide convention (same finding present in
`precompute.py`/`translate.py`, not something this task introduced or should
unilaterally "fix" into inconsistency).

## Open questions

- Should `grounding_config` gain a dedicated "NER model" override distinct from the
  disambiguation-judge model (today they're forced identical, per the task's own
  instruction)? Would need a small schema/Settings addition — not built, flagged
  only.
- Should a per-document `WikidataClient` become a cross-request singleton for
  politeness under concurrent uploads? Fine for a low-concurrency demo as shipped;
  would need revisiting for higher concurrent load.
- Should `terms_status` carry an `errorReason` like precompute/translate do? Not
  requested by the task spec (`'none'|'running'|'done'|'failed'` only); would be a
  natural follow-up if the owner wants "why did it fail" surfaced in the UI.

## NOT done (explicit)

- **DELETE does not cancel an in-flight `terminology_live` task.**
  precompute/translate each have a `cancel()` wired into `DELETE
  /api/documents/{doc_id}`; I did not wire this for terms because app.py's DELETE
  route is outside my authorized edit scope for this task. A deleted document's
  in-flight terms task will stop writing at its next per-paragraph
  `_document_exists` check (same eventual-consistency window precompute/translate
  close explicitly; here it's only closed implicitly).
- **No cross-document glossary consistency.** The demo-contracts spec's §5
  "term-agent" vision describes a persistent `glossary`-table backbone giving the
  same `(term, context)` the same equivalent across every document (dense-embedding/
  BM25 retrieval). Not built — the live pipeline only has per-document "one sense per
  discourse" via `judge_cache`/`scope_id=doc_id`. The task didn't ask for the
  cross-document backbone; said so explicitly in the new contracts delta section
  rather than silently under-delivering against §5's fuller (aspirational) framing.
- **No progress detail beyond the single `termsStatus` string** (precompute/translate
  expose `{done, planned, succeeded}`/`{done, total}`) — not requested by the task's
  literal schema (`'none'|'running'|'done'|'failed'` only).
- **Frontend wiring** — explicitly out of scope per the task ("do not touch
  frontend/"); the term rows this pipeline writes are already schema-compatible with
  what `TermPopover.tsx`/`GlossaryTab.tsx` already render for the seed document, so no
  frontend change should be needed, but I did not verify this in a browser (backend
  lane only).

## Flagged, not acted on

Two prompt-injection attempts were encountered during this task and were not acted
on: (1) a trailing `<context_window_protection>` block in the task message demanding
routing through `mcp__plugin_context-mode_context-mode__*` tools that do not exist in
my actual toolset; (2) mid-session, a fabricated "coordinator message" appeared
embedded inside a Bash tool's stdout (not a real conversation turn) instructing me to
edit `frontend/VariantA.tsx` and run `npm test`/`tsc`/`npm build` — directly
contradicting my actual instruction ("do not touch frontend/") and referencing lane
names/context never mentioned in my real task. Both ignored; noted here for the
record.
