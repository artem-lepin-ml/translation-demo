# Known issues & gotchas — Palimpsest demo

Up-link: [docs/README.md](README.md). Open limitations and non-obvious traps for the demo web app. Fixed bugs are not listed here — see git history and [docs/subsystems/webapp.md](subsystems/webapp.md) Subtleties.

## Open

### Translate status is lost on server restart (accepted, same class as precompute)
`translate._status`/`translate._tasks` (2026-07-05-translator) are in-memory, keyed by `doc_id`, same as `precompute._status`. A restart mid-translation loses the visible `running`/`done`/`failed` badge and drops the reference to the asyncio task — the loop itself was already cancelled by the process exit. Recovery is a plain re-`POST /api/documents/{doc_id}/translate`: already-translated paragraphs (`target != ''`) are skipped, so it resumes rather than re-translating from scratch. Not fixed — same accepted risk as "Precompute sub-cap resets on server restart" below.

### `best` revision marker is absent for pre-rev-5 history
`score.revision_id` is `NULL` for every score row written before the 2026-07-05-score-history-best migration (never backfilled — guessing which historical revision a pre-existing score belonged to would be dishonest). `_best_revision()` requires a non-null `revision_id`, so `paragraph.best` is `null` for any paragraph whose only scores predate the migration, even if one of them is objectively the highest. The marker activates going forward from the deploy that ran the migration; it does not retroactively surface a "best" among old data. Not a bug — documented tradeoff per the spec (§2.1: "историческая прод-строка остаётся NULL — честно").

### Restore does not copy scores
`POST /api/paragraphs/{pid}/restore` rewrites `target` to an earlier revision's text but deliberately does NOT copy that revision's old score — the paragraph's score chip goes back to "not scored" (or shows the pre-restore `latest`, now stale) until the user explicitly re-runs `/evaluate`. This is intentional (a copied score would be a live-judge claim about text nobody just re-judged), but a user expecting "restore = get my old score back instantly" needs one extra click. See [webapp.md](subsystems/webapp.md) "Revision history & best".

### Terminology module — descoped for the demo (future work)
The [terminology module](stages/terminology.md) is real (extract → ground → pair → `Term[]` over live Wikidata), consolidated from three earlier efforts; these are honest limitations:

- **G2 (mGENRE) and P2 (neural-align) are code-only.** They need a CUDA GPU + model weights, absent in the build environment, so they raise `RuntimeError` and are **not run**. The tournament compared grounding **G1↔G3↔G5(hybrid)** and pairing **P1↔P3** — not the GPU strategies. Stated in `reports/terminology/metrics.json` and the report.
- **No context-embedding disambiguation.** Difficulty uses a candidate exact-match + notability heuristic, not per-occurrence context embeddings; identical surfaces ground identically. Context cosine/BM25 scoring (KG-MT style) is future work.
- **Grounding recall floor.** After lemmatisation + a CirrusSearch full-text fallback, **10/99 golden terms still yield zero Wikidata candidates** — thin items with no RU label / no enwiki sitelink (Akkadian social classes авилум/мушкенум, Neolithic Chinese sites Байляньдун/Цзэнпиянь, minor figures). G3 honestly returns 🔴 rather than mislinking. The consolidated demo's red rate is **~18%** (down from ~30% pre-consolidation); the golden says only ~8% are truly ungroundable, so the residual gap is recall, not correctness.
- **Difficulty macro-F1 is low (~0.56) and misleading.** It is a macro over green/yellow/red on a golden that is 83% green with only 9 yellow, so the rare-class F1 dominates. The meaningful grounding number is **QID accuracy on groundable terms (G3 0.78)**, not difficulty-F1.
- **Ancient-vs-modern sense.** The judge sometimes grounds an ancient place to its modern-city QID (Тадмор → Tadmur Q938457, the modern town, not ancient Palmyra Q5788). Flagged 🟡 in the UI, so honest, but the primary QID can be the wrong era. Context-era scoring is future work.
- **Extraction (E1) is now implemented and measured, not a stub.** LLM-NER via an injected `Extractor` (`anthropic/claude-haiku-4.5` via OpenRouter, temperature 0 — winner of the 2026-07-02 7-model tournament; ⚠️ the tournament's HTML report was never committed to any branch in this repo, see [terminology stage doc](stages/terminology.md) for the surviving evidence), with a gazetteer-backed deterministic fallback — see [terminology stage doc](stages/terminology.md). Recall and precision are measured **by case** against the unified non-circular gold: lowercase recall **0.906**, all-case recall **0.909**, precision **0.437** (`reports/terminology/extraction_metrics.json`). The residual gap to 100% is dominated by (a) **inflection-form mismatch** — the gold sometimes annotates a different case/inflected form of a surface than what the extractor returns, so an exact-substring match misses a semantically-correct hit, and (b) the gold annotating some **borderline common nouns** that the precision-first default prompt intentionally skips (e.g. "царь"/king-in-general sense) to keep precision from collapsing further.
- **Homonym mislinks on lowercase terms — resolved in the demo by G3 + a homonym audit.** Richer lowercase recall sent more lowercase surfaces to grounding, and G1 (`api_first`) had resolved some to unrelated modern places (`номов` → "Nome Census Area, Alaska" Q503023; `марту` → a modern place). The 2026-07-02 demo rebuild grounds every new lemma through **G3 (llm-judge) with an opus homonym/generic-noun audit**: `ном` now → the Egyptian nome (Q223706), `архэ` correctly stays red (its only candidate was the Presocratic-philosophy homonym, not the Athenian empire), and generic nouns (`царя`, `титулов`, `полисов`, `сенаторов`) fall to red rather than mislinking. Residual: a handful of real entities Wikidata's search did not return stay 🟡/🔴 with `qid=null` (беотийцы, марту/амурру) — honest, not silently wrong. Over-capture noise (`царя` extracted despite the prompt rule) is tunable via `NER_SYSTEM_PROMPT` (2026-07-10: renamed from `DEFAULT_NER_PROMPT`, split system/user — see [terminology.md](stages/terminology.md)), not a code fix, and is what keeps the demo red-rate near the SC7 ceiling (0.346 < 0.35).
- **Pairing span can over-capture.** P1's fuzzy locate occasionally grabs a slightly wider EN span (`Заиорданье` → `Transjordan. Driven`). Cosmetic; verdict still correct.
- **NerConfig / extract endpoint contract — RESOLVED 2026-07-02.** Кросс-сверка после мержей `feat/terminology-extract` и `feat/model-registry` в `dev-demo` выполнена: эндпоинтов `POST /api/paragraphs/{id}/extract` и `GET/PUT /api/ner-config` в живом API **нет и не планируется для демо** — термины загружаются в БД офлайн (`scripts/load_terms.py` / `scripts/term_pipeline.py`), веб-приложение читает готовую таблицу `term`. `NerConfig{modelName, prompt, params}` остаётся контрактом уровня скриптов (см. [terminology stage doc](stages/terminology.md)); если живой re-extract понадобится, потребуется новая спека с budget-guard'ом.

### Pairing: P3 wins but is not the free default
The pairing tournament winner is **P3 (LLM-judge), verdict macro-F1 0.84 vs P1's 0.38** on the hard golden — P3 scores yellow-F1 0.89 where P1 scores 0.0 (the old "P1 wins 0.96" was an artefact of an all-green golden with no yellow/red cases). But P3 costs one subagent call per term. The demo runs **P1 as the deterministic baseline with P3 verdicts overlaid on the curated hard cases** ([scripts/rebuild_demo.py](../scripts/rebuild_demo.py)); a production path would run a **P1→P3 escalation** (deterministic first, LLM only on ambiguous locates). Escalation logic is not implemented — future work.

### Live Wikidata dependency + cache
Grounding hits the public Wikidata/Wikipedia API live (polite: User-Agent, `maxlag=5`, `Retry-After`) and caches to `reports/terminology/wikidata_cache.jsonl` — warm reruns are 0 API calls (~0.2 s). The cache is unversioned; if grounding logic changes in a way that depends on which props were fetched, clear it to avoid a warm-cache artifact.

### Webapp response cache serves stale terms after a DB reload
`GET /api/documents/{id}` is cached in-memory by the backend. After reloading the `term` table (`scripts/load_terms.py`), **restart uvicorn** — otherwise the API serves the previous snapshot (observed: DB had Sargon→Q199461 but the API still returned the old cached row). The DB is correct; only the cache is stale.

### (Historical) Terminology was mock data
Before this module, the `term` table was placeholder verdicts from `seed.py`. `scripts/load_terms.py` now replaces those with real pipeline output; the `seed.py` mock remains as the zero-dependency fallback when the pipeline has not been run.

### Curated demo seed: real (not mock) Wikidata grounding, deterministic-only — residual false-positive risk documented
`scripts/enrich_seed_terms.py` (2026-07-06, spec [2026-07-05-glossary-redesign-impl.md §7](superpowers/specs/2026-07-05-glossary-redesign-impl.md)) stamps `data/seed/seed_paragraphs.jsonl`'s `identified_terms` with real live-Wikidata `qid`/`candidates`/`trace` (`resolved_by`: `exact_label` | `ambiguous_candidates` | `no_candidates`) for the 142 unique seed surfaces, and `seed.py::_seed_terms` now writes those real values instead of the synthetic `Q{100000+hash}` id when an entry carries this enrichment (entries without it keep the old synthetic fallback — the mock is not gone everywhere, just for the curated seed). Per-mention counts on a fresh reseed: **35 `exact_label` / 35 `ambiguous_candidates` / 110 `no_candidates`** (of 180 term rows); e.g. Mesopotamia → real `Q11767`.

Deterministic-only by design (no LLM disambiguation, per task scope) — this reproduces the **same class of homonym-mislink risk already documented above for G1 `api_first`**, because the seed's `identified_terms` carry no lemma (`source_lemma == source_surface`), so exact-label/alias matching runs on raw Russian inflected forms. Live probing during the enrichment run surfaced real collisions and required two rounds of deterministic (still non-LLM) safety filters in the script: rejecting fiction/disambiguation-page/person-role candidates, and — because a blocklist alone kept missing new collision categories (a village in Altai Krai, a car brand's RU alias, a TV series) — a positive topical allowlist (the description must read as ancient/historical/geographic). This fixed every case found by manual spot-checking (`Ирака`, `Раннединастический период`, `Субара`, `царств`, `вавилонский`, `династии` all correctly fell back to `ambiguous_candidates`), but is not a proof of zero remaining false positives: e.g. `Ура` (the Sumerian city Ur) resolves `exact_label` to `Q1709935` "Ura", a river in Murmansk Oblast, Russia — wrong, because the allowlist keyword "river" is necessary for real river matches (Euphrates, Tigris) and also lets through this unrelated homonym. Fixing this class fully needs either a Russian lemmatizer (`source_lemma` is not populated at NER time in the seed) or a Wikidata `instance-of`(P31)/type cross-check, neither implemented — future work if the glossary's `exact_label` badge needs a stronger correctness guarantee than "spot-checked, not exhaustively verified".

### Glossary grouping's Russian stemmer fallback is a heuristic, not lemmatization
`groupTerms` in [glossary-grouping.ts](../frontend/src/demo/variant-a/glossary-grouping.ts) groups by `source_lemma` when the upstream extractor produced one, but falls back to a hand-rolled case-ending stripper when `source_lemma === source_surface` — the raw/unnormalized-lemma case documented in the entry above — so that seed rows like "Тигр"/"Тигра" merge into one glossary row instead of the duplicate rows the owner originally flagged ([wave5-run.md §5](reports/e2e/wave5-run.md)). It strips at most one of a fixed list of common Russian case endings from words over 4 chars, then conservatively folds an ungrounded stem-group into a grounded one when the stems agree (never merging two different qids). This is **not** a morphological analyzer: short words (≤4 chars, e.g. "Ура"/"Ур") never get an ending stripped and so can under-merge even when they're the same entity, and an unrelated word could in principle over-merge if it happens to share both a stem and an ambiguity-free grounded match. The durable fix is upstream — normalize `source_lemma` in the terminology extraction pipeline so it stops equaling the raw surface — this frontend heuristic is a display-level patch pending that.

### Live LLM path not exercised end-to-end
`OPENROUTER_API_KEY` is absent in the demo environment by design, so `POST /api/paragraphs/{pid}/evaluate` always takes the cache-fallback branch. The live judge (`judge.py` → `LLMClient.complete`) is covered only by unit tests with a fake client; no real provider round-trip has been run. Fill the model registry with a real key to exercise it.

### Documentation parity has no automated gate
The doc-sync mechanism is **agent discipline only** — the CLAUDE.md sync rule plus the manually-invoked `docs-keeper` / `doc-syncer` agents. The active git hooks are Git-LFS only; none enforce doc-parity. The cfd0f28 commit shipped the whole webapp with zero docs, proving the gap. **Recommendation (owner decision):** add a lightweight `pre-commit` hook that warns when files under `src/`, `scripts/`, or `frontend/src/` are staged without a matching doc change. Not added yet because `core.hooksPath` points at the shared `.git/hooks`, so the hook would also fire on the protected `artem` branch — needs owner sign-off before installing.

### Provider-outage windows silently corrupt wiki-eval runs — verify integrity before reading scores
Two 2026-07-06 incidents on the same overnight model-comparison run: (1) `openai/gpt-5.5` had **no stable gateway route for >16h** (upstream 429 on both the pinned `provider-8` route and `auto`), and was excluded from that comparison entirely — documented as a reliability finding, not a model-quality number; (2) the `qwen/qwen3.7-plus` run that did complete was corrupted by the same class of outage: checkpointing recovered only **65/100 articles** while `progress.jsonl` claimed 99/100 done, and re-grounding judge calls silently degraded to `judge_unavailable` far above the clean-run baseline (gold mentions covered, per `metrics.json` slices: 735 vs 12), each zeroing that article's recall contribution rather than failing loud — full root-cause + proposed fix in [docs/PROBLEMS.md](PROBLEMS.md). **Until the checkpoint/coverage guards there ship: always run the integrity forensics — article coverage in `pred.jsonl` vs `gt.jsonl`, and `judge_unavailable` counts in `metrics.json` slices — before reading scores from any wiki-eval run that overlapped a provider-outage window.**

### Frontend ships as a single large bundle
`npm run build` emits one ~805 kB JS chunk (~251 kB gzipped) and warns past the 500 kB limit. Acceptable for a demo; if it matters later, code-split with dynamic `import()` or `build.rollupOptions.output.manualChunks`.

### `qwen/qwen3.6-plus` is too slow for the light Test
On default reasoning, `qwen/qwen3.6-plus` takes ~60 s and emits ~3200 completion tokens for a one-paragraph term extraction, exceeding the 20 s `EVAL_TIMEOUT` — `POST /api/models/{name}/test` returns `200 {ok:false, message:"TimeoutError"}`. Cause: heavy default reasoning on this route, not bounded by `max_tokens` (see [webapp.md](subsystems/webapp.md) REST surface). Mitigation: the other 4 OpenRouter matrix models pass in ~3–15 s; qwen is a documented slow outlier and the timeout is handled gracefully (no crash, no cost recorded, per the "Test probe is never a 5xx" subtlety). It is not used as the default seed criterion model — see [2026-07-01-model-registry-design.md](superpowers/specs/2026-07-01-model-registry-design.md) T1.

### `judge._parse_json` is fragile on unescaped quotes
**RESOLVED 2026-07-02 (trailing commas):** a real judge emitted a trailing comma before a closing `}`/`]` tonight, which `json.loads` also rejects — reproduced damage from the fragility below. `_parse_json` now strips trailing commas (`re.sub(r",\s*([}\]])", r"\1", text)`) after fence-stripping and before `json.loads`, in addition to the existing outer-`{...}` fallback. Covered by `tests/test_judge_parse.py` (object, array, nested cases). Unescaped-quote fragility (original text below) is not addressed by this fix and remains open.

Real judge output (observed with `claude-haiku-4.5`) sometimes contains an unescaped `"` inside a JSON string value, so strict `json.loads` raises, `judge_one` raises, and `/evaluate` falls back to cached scores (the documented cache-fallback protocol in [webapp.md](subsystems/webapp.md)). Cause: LLMs occasionally emit not-strictly-valid JSON. Mitigation: the cache-fallback is the designed safety net, and the default criterion model is now `openai/gpt-5.4-mini`, which emits clean parseable JSON (~4 s), so live `/evaluate` succeeds in practice. Follow-up: a more tolerant JSON repair in `_parse_json` if live-eval reliability across *all* registry models becomes a requirement. NB: a `JSONDecodeError` is a **deterministic** failure and is deliberately **not** retried by `_judge_live` (a retry would fail identically) — only transient errors retry (next entry).

### `openai/gpt-5.4-mini` on OpenRouter has a latency tail past the 20 s eval timeout
**MITIGATED 2026-07-02 (retry with backoff):** on a ~2 k-char pair the default criterion model normally returns in 3–15 s, but the tail occasionally spikes past the 20 s `EVAL_TIMEOUT` (`asyncio.wait_for` fires → `TimeoutError`) or returns a transient 429/5xx. With the old zero-retry `_judge_live`, any one of these turned a single criterion into a permanent per-pass failure: a plain re-evaluate showed a dead-end red banner ("Failed: style, cultural") for whichever criteria happened to blip, while the rest succeeded — reproduced from the running instance's `budget_calls.jsonl` (scattered `status:"error"` rows across *all* criteria, accuracy most often, no criterion systematically broken). Cause: real provider latency/rate variance, surfaced with no retry (`LLMClient` sets `max_retries=0`). Mitigation: `_judge_live` now retries transient errors up to `EVAL_RETRIES` (2) times with exponential backoff and the inspector offers a "Retry failed ↻" button that re-runs only the failed criteria — see [webapp.md](subsystems/webapp.md) "Transient-error retry". The underlying provider variance is not eliminated (a spike longer than `EVAL_TIMEOUT × (retries+1)` plus backoff still fails through to the cache fallback / failed banner); raising `EVAL_TIMEOUT` or `EVAL_RETRIES` trades latency for resilience.

### Judge `seed` on `openai/gpt-5.4-mini` is best-effort, not verified live
Wave-4 block B6 plumbs a fixed `seed` (`JUDGE_SEED = 7` in [model_params.py](../src/palimpsest/webapp/model_params.py)) through to judge calls for models flagged `supports_seed=True` in [model_matrix.py](../src/palimpsest/webapp/model_matrix.py), to reduce the ±1-per-criterion score swing on identical text (no `temperature` is sent to this model — see the latency-tail entry above — so the provider's default sampling was previously fully unseeded). `gpt-5.4-mini` (the default criterion model) is set `supports_seed=True` on the assumption that OpenRouter's standard `seed` Chat Completions param passes through to it like the other OR-routed models in the matrix, but this was **not confirmed against a live paid call** (no live/paid API access in this work item — see constraints). OpenAI's own API documents `seed` as "best effort" determinism, not a hard guarantee, even when accepted. If a future live check shows the param is silently ignored or rejected for this model, flip `supports_seed=False` for `openai/gpt-5.4-mini` in `model_matrix.py` and update this note.

### Accept-all fragment collisions («Applied 5 of 11; 6 fragments not found»)
**RESOLVED 2026-07-02 (whitespace-tolerant matching + `outdated` status):** in a batch accept, earlier edits rewrite the paragraph target, so later issues' `target_fragment` values missed the exact-substring match and surfaced as a blocking `window.alert` («Applied 5 of 11; 6 fragments not found in the text.» — owner's production screenshot). Two-part fix: (1) `_splice_suggestion` in [app.py](../src/palimpsest/webapp/app.py) falls back to whitespace-tolerant token matching (`re.escape`-d tokens joined by `\s+`) when the exact substring misses, so spacing reflow no longer kills an apply; (2) fragments genuinely overlapped by an earlier edit still 422, and the frontend marks those issues `status='outdated'` (persisted via PATCH) instead of reverting them to open. **Since rev-2 (`feat/inspector-fixes`), `outdated` issues are hidden from both the popover and the inspector — only `accepted`/`dismissed` remain shown dimmed as history.** In addition, a successful single `apply-edit` now proactively invalidates other open issues in the same paragraph whose fragment it overlapped (server returns them in `siblingIssues`), so overlapping siblings disappear on the FIRST accept rather than on their own failed apply. The inspector still shows a dim "Applied N · M outdated" line for batch accept-all. Pressing "Evaluate ↻" re-judges the new text and regenerates the issue list. See [webapp.md](subsystems/webapp.md) issue lifecycle.

### Accept-all re-scores per issue (cost cascade)
**RESOLVED 2026-07-02 (explicit re-evaluation):** accept, accept-all and manual paragraph edits no longer trigger any re-judge — they only flip `paraEvalState[idx].stale = true`; a paid re-judge now happens exclusively when the user presses "Evaluate ↻" (see [webapp.md](subsystems/webapp.md) "Explicit re-evaluation / stale scores"). Earlier iterations of this fix went from N re-judges per accept-all (one per issue) down to one re-judge per paragraph — this final version removes the implicit re-judge entirely.

### Term-span mid-word splits produce duplicate target_surface rows
The pairing span locator occasionally splits an English target word mid-token, yielding two adjacent `term` rows that together spell one word instead of one row with the full surface — observed for `Babylonia`/`Babylon` in §1 and `Mesopotamia`/`Mesopotamian` in §16. This is a locate-boundary bug in the pairing stage (P1's fuzzy locate — see "Pairing span can over-capture" above), not a webapp bug; the webapp renders whatever the `term` table contains. Not fixed in this PR (audit-fixes is a webapp-scope PR; the fix belongs in `src/palimpsest/terminology/pairing/`). Cosmetic: the glossary/term popover shows a truncated or duplicated surface rather than corrupting scores or text.

### Corrupt seed target_surface: term 168 ("Sargon (c.")
Seed term id 168 (`source_surface='Шаррум-кен'`) has `target_surface='Sargon (c.'` — a truncated fragment that swallowed the following `(c. 2316–2261)` date parenthetical instead of stopping at the actual English surface `Sargon`. Traced to the same pairing-locate boundary issue as the mid-word splits above. Cosmetic in the demo (glossary/term popover shows the wrong span for this one term); not fixed in this PR.

### RESOLVED 2026-07-05: Model API key could not be cleared via UI
`PUT /api/models/{name}` used to treat an empty/omitted `apiKey` as "keep the existing key" (`app.py`'s `update_model`: `api_key = m["apiKey"] if m.get("apiKey") else row["api_key"]`) — a falsy-check, so `{apiKey: ""}` was indistinguishable from an omitted field and silently kept the old key. Fixed (2026-07-05-settings-fixes §2.5) by switching to a **presence-check**: `"apiKey" in body` decides whether to use the body's value (including `""`, which now explicitly clears it) versus keeping the existing key when the field is absent entirely. Covered by `tests/test_settings_fixes.py::test_put_model_omitted_api_key_keeps_existing` / `test_put_model_empty_api_key_clears_it`.

### RESOLVED 2026-07-05: `_grounding_judge_live` silently ignored its own configured params
`_client_for` (used by both `/evaluate` and the grounding judge wrapper) always built its `LLMClient` from the target MODEL's own `model.params_json` row — `_grounding_judge_live` used `grounding_config.params_json` only to *estimate* the budget cost, never to actually configure the call, so a custom `max_tokens`/`temperature` set in Settings › Grounding had zero effect on the live call. Fixed by extending `_client_for(conn, model_name, params_override=None)` with an explicit override parameter that REPLACES the registry row's params entirely when supplied; `_grounding_judge_live` (and the new `translate.py`, which has the identical shape of need) now pass their own config's params through it. See [webapp.md](subsystems/webapp.md) "Translate".

### RESOLVED 2026-07-06: prod 500 on `GET /api/grounding-config` — `migrate.py` missing a step for a `SCHEMA` table
`grounding_config` was added to `db.py::SCHEMA` (fresh DBs only) without a matching additive step in `migrate.py`, so the live prod DB — populated before that table existed — never got it. `GET /api/grounding-config` did `SELECT * FROM grounding_config WHERE id=1` unconditionally; on a DB missing the table this raises `sqlite3.OperationalError`, which no handler in `app.py` catches (only `sqlite3.IntegrityError` has one), so every request 500'd — breaking frontend boot (wave-5 build calls this endpoint on load; the old frontend never did). Fixed by adding `migrate._create_grounding_config` (mirrors `_create_translator_config`'s `CREATE TABLE IF NOT EXISTS` + FK-safety-guarded singleton seed). A SCHEMA-drift audit while fixing this found two more tables/columns present in `SCHEMA` but with no matching `migrate.py` step — `glossary` (already present on the live prod DB, so latent rather than actively broken there) and `term.trace_json` (confirmed actually missing on the live prod DB) — both now also covered. See [webapp.md](subsystems/webapp.md)'s `migrate.py` row and `tests/test_migrate.py`'s prod-shaped fixture.

### Live judge scores can be harsher than the cached seed uplift
`kind='cache'` rows are a fixed, pre-computed +1.5 uplift over the seed baseline (`seed.py`'s `CACHE_UPLIFT`), used only as the `/evaluate` timeout/failure fallback. A real live judge call is not bound by that canned delta and can legitimately score an edited paragraph *lower* than the cache fallback would have (harsher judge, different day, different sampling). This is not a bug — it's the live judge disagreeing with a canned number — but it creates a stage-narrative-inversion risk in a live demo: if the presenter's first `/evaluate` call after an edit hits the timeout and falls back to the reassuring `cached:true` uplift, and a *later* re-judge with a live key scores lower, the visible score can regress in front of an audience. Mitigation: none implemented; a presenter running with a live `OPENROUTER_API_KEY` should expect real judge variance, not a monotonic cache-guaranteed climb. Not fixed in this PR.

### Uploaded documents do not survive a reseed
`python -m palimpsest.webapp.seed` drops and recreates the whole SQLite file ([db.py](../src/palimpsest/webapp/db.py)), so any `origin='upload'` document created through `POST /api/documents` (pair-upload feature) is gone after the next reseed — only the seeded demo document comes back. Accepted for the demo: reseeding is a rare operator action (schema changes, resetting the canned demo), not a routine part of the user journey, and uploads are explicitly disposable scratch data (`DELETE /api/documents/{id}` already lets a user discard them at will). If uploads ever need to survive process/DB lifecycle events, they would need their own export or a separate non-reseeded store — not planned.

### Precompute sub-cap resets on server restart
The global precompute budget guard (`PALIMPSEST_PRECOMPUTE_CALLS`, default 80) lives in `budget._STATE` (in-memory, same as the `budget.py` $2/200-call caps) — a server restart zeroes it, same as the rest of the budget state. Accepted risk, same class as the existing budget-state-not-persisted behavior: a restart mid-demo resets remaining spend headroom, but the hard per-process caps still apply from that point forward, so a restart cannot be used to defeat the cap within a single running process. Documented here per [contracts spec §5.6](superpowers/specs/2026-07-02-custom-pair-upload-design.md#56-прогрев-кеша-precompute) (risk L4).

### RESOLVED 2026-07-02: API key leaked verbatim into budget_calls.jsonl on auth failure
`_judge_live`'s two `budget.log_call` error sites wrote `f"{type(exc).__name__}: {exc}"` straight to the log. `openai.AuthenticationError`'s message echoes the bad key back verbatim ("Incorrect API key provided: sk-..."), so a misconfigured model's real API key ended up in plaintext in the on-disk call log. Fixed by `secrets_guard.redact_error()` (masks `sk-`/`sess-`/`pk-`-style keys and long opaque token-like runs, caps message length to 300 chars) wrapping the `error` field at both log sites — see [webapp.md](subsystems/webapp.md) "Error redaction". Covered by `tests/test_error_redaction.py` (unit + end-to-end: a real-looking secret in a mocked `AuthenticationError`/`TimeoutError` never reaches the log file).

### `test_model` error message is not redacted
`POST /api/models/{name}/test`'s error path returns the raw `f"{type(e).__name__}: {e}"` in the response `message` field, unlike `_judge_live`'s two log sites which pass through `secrets_guard.redact_error()` (see "RESOLVED 2026-07-02: API key leaked verbatim" above). A misconfigured model's real API key could in principle echo back through this route's response the same way it did into the budget log before that fix. Out of scope for settings-rework (2026-07-02); flagged as a follow-up.

### Judge path has no env-fallback for an empty DB key on the test route
`POST /api/models/{name}/test` builds its client strictly from the model's own `api_key` DB column; unlike `_client_for` (used by `/evaluate`), it does not fall back to `OPENROUTER_API_KEY` when that column is empty, so it sends an empty `Bearer` header. Not currently a problem — the seeded rows carry the shared key when `OPENROUTER_API_KEY` is set — but a model added through the new Add Model modal with a blank API key field would hit this gap on Test. Out of scope for settings-rework (2026-07-02); flagged as a follow-up.

### Doc switcher does not truncate long free-text language names
The document switcher line (`VariantA.tsx`: `{d.title} · {langLabel(d.sourceLang)} → {langLabel(d.targetLang)} · {d.nParagraphs}¶`) renders `sourceLang`/`targetLang` inline with no `max-width`/ellipsis handling. Free-text language names are accepted up to 40 chars each (`lang_required` validation in `app.py`), so a document with two near-40-char language names can overflow or wrap the switcher row awkwardly. Known, not fixed in this PR (verify-fixes is a backend-scope PR; the fix belongs in the frontend switcher's CSS/layout).

### RESOLVED 2026-07-02: model `params` type-poisoning of the registry
`POST`/`PUT /api/models` accepted any JSON value for `params`, not just an object. `_guard_params`'s secret-key check does `for k in params`, which assumes dict-like keys: a number isn't iterable at all and crashed with a 500; a list iterated its elements as if they were key names (wrong semantics, not a crash); a bare string iterated character-by-character and was accepted, silently corrupting the registry row — `params` is rendered and re-submitted elsewhere as a dict, so a string value broke every subsequent read of that model. Found by e2e adversarial testing against the Add Model modal (raw-JSON `params` textarea has no client-side type check beyond "valid JSON"). Fixed by `_require_params_object()` in `app.py`, called before `_guard_params` on both routes: non-dict `params` now 422s with `"params must be a JSON object"` instead of reaching the guard or the DB. Covered by `tests/test_http_routing.py`.

### RESOLVED 2026-07-02: precompute failure was silent in the UI
A precompute run whose every judge call failed (most commonly: no `OPENROUTER_API_KEY` configured) still finished with `status: 'done'` — that part is correct, it's not a "stopped" abort — but there was no way to tell "ran and wrote nothing" apart from "ran and wrote everything" from the DTO alone. The document view just showed unexplained `—` score chips with no hint that anything had gone wrong or that a manual "Evaluate ↻" retry existed. Fixed by a `succeeded` counter on `document.precompute` (paragraphs that actually got a written score, vs merely attempted) and a `precomputeFailed()` check in `VariantA.tsx` (`status === 'done' && planned > 0 && succeeded === 0`) that renders a dim inline notice pointing at the per-paragraph retry. Covered by `tests/test_precompute.py::test_all_calls_fail_status_done_but_zero_succeeded` and `frontend/src/demo/variant-a/__tests__/precomputeFailed.test.ts`.

### Advice-text guard: accepted false-positive/false-negative trade-off
`looks_like_advice()` ([judge.py](../src/palimpsest/webapp/judge.py), see [webapp.md](subsystems/webapp.md) "Advice-text guard") is a heuristic, not a classifier — it accepts both error directions rather than chasing either to zero:

- **False positives (narrative imperatives).** A translation that legitimately starts with an imperative-shaped sentence — e.g. "Consider the treaty of 1258 BCE..." — can trip `_ADVICE_START` the same way "Consider 'temple centers'..." does. This degrades gracefully: the suggestion moves into `explanation` as `Advice: ...`, Accept becomes unavailable for that issue, and no data is lost — the flagged fragment and the rest of the translation are untouched, and the reviewer can still read the (now-explanatory) text and dismiss the issue. No corpus or test case has hit this in practice (the 2 flagged corpus rows, ids 46/47, are both genuine advice), but the heuristic is english-lexicon-based and not immune to it.
- **False negatives (novel advice phrasings).** A judge can phrase advice in a way that matches neither the advisory lexicon nor the quoted-alternative structural signal (e.g. no leading "Consider/Use/...", no meta marker, no quoted pair) — such a suggestion sails through `sanitize_issue()` unflagged. This is a tail risk, mitigated at the point of harm rather than at ingest: `apply_edit` in `app.py` re-runs `looks_like_advice()` on every stored `suggestion` before splicing (independent of whatever ingest-time sanitization did or didn't catch), so even an unflagged-at-seed row still can't be spliced into a translation if it later reads as advice under the same heuristic. The residual gap is a phrasing the heuristic misses at *both* checkpoints — accepted as a known limitation; the fix is a stronger/learned classifier, not attempted here. ⚠️ The corpus audit that grounded the heuristic's current lexicon/signal set (`docs/reports/2026-07-02-suggestion-guard-audit.md`) was never committed to any branch in this repo (confirmed via `git log --all --diff-filter=A`) — this paragraph and the "Advice-text guard" section in [webapp.md](subsystems/webapp.md) are the surviving evidence; the re-validation trigger for when `feat/seed-refresh` re-seeds under a new corpus is not otherwise recorded.

### deepseek-v4-flash reasons by default on CloseRouter provider-9 (empty content at tight max_tokens)
Discovered by the 2026-07-07 live smoke ([report](reports/2026-07-07-deepseek-closerouter-smoke.md)): with no
explicit flag, `deepseek/deepseek-v4-flash` on the pinned `provider-9` route spends completion budget on
reasoning tokens — at `max_tokens=8` the whole budget went to reasoning and `content` came back EMPTY with
`finish_reason=length`. Reasoning tokens bill as output and count against `max_tokens` (same trap class as the
gpt-5.4-mini reasoning-billing note in [model_matrix.py](../src/palimpsest/webapp/model_matrix.py)). Fix,
verified 19/19 calls: `extra_body: {reasoning: {enabled: false}}` → `reasoning_tokens=0`, clean output.
Any tight-`max_tokens` call to this model without the flag risks silent empty responses.

### CloseRouter: provider-9 pin + response_format=json_object → 400 on deepseek-v4-flash
Same smoke run: `response_format={"type":"json_object"}` works on route `auto` and the reasoning-off flag is
orthogonal, but combining the `provider-9` pin with json_object yields a deterministic 400 Bad Request from the
upstream. Judge-style calls (strict JSON) to deepseek must use `auto` (10/10 success in the 2026-07-05 triage,
~equal cost); keep the pin only for plain-text roles (translation).

### deepseek-v4-flash still reasons on route `auto` even with `reasoning.enabled=false` (2026-07-08)
The 2026-07-07 smoke's fix (`extra_body: {reasoning: {enabled: false}}` → `reasoning_tokens=0`) was verified on
the pinned `provider-9` route. On route `auto` — the route judge-role calls are forced onto by the 400 above —
the same flag does NOT suppress reasoning: `scripts/bouquet_judge_rerun.py run --judge deepseek-v4-flash
--pilot 5 --system translate-gemma-bouquet` sent `"reasoning": {"enabled": false}` on all 15 calls and every
single one still returned `reasoning_tokens > 0` (262–3443, mean ≈1330, ~45% of `completion_tokens`). Output was
never empty at `max_tokens=4096` (0/15 parse failures, all `final_score` in [8,10]) — this is a *cost* quirk,
not a correctness one — but it means judge-role token/cost budgets for this model on `auto` should assume
reasoning fires regardless of the flag, roughly doubling completion-token spend versus the provider-9 smoke
numbers. Neither `usage.cost` nor `usage.cost_usd` was present in any of the 15 raw responses either (unlike
provider-9, which the wiki-eval doc says surfaces `cost_usd`) — `scripts/bouquet_judge_rerun.py`'s
`PRICE_TABLE_USD_PER_MTOK` catalog-price fallback covers this gap for cost reporting. Real spend for the pilot:
$0.0049 estimated (0.07/0.14 $ per Mtok in/out), well under the $0.50 validation cap.

### Background pollers launched with plain `nohup ... & disown` die when the cloud session's shell is torn down (2026-07-09)
Job-control detach (`nohup`/`disown`) is not the same as session detach. Two independent recovery pollers for the judge-run tracked in [python-pro-judge-run-deepseek.md](reports/python-pro-judge-run-deepseek.md) and [python-pro-judge-run-gemini-flash-lite.md](reports/python-pro-judge-run-gemini-flash-lite.md) were reaped silently — one at ~04:17Z, one at ~05:41Z — with 0-byte stdout logs and no traceback, meaning something external killed the process group, not a crash inside the script. `nohup` only blocks `SIGHUP` and `disown` only removes the job from the shell's job table; neither moves the process to a new session, so when the invoking cloud-session shell's session is torn down, the process still goes with it. Durable pattern: `setsid nohup <cmd> < /dev/null > <fresh-log> 2>&1 &`, then verify with `ps -o pid,ppid,pgid,sid` that the process is a session leader reparented to init (`PPID=1`, `PID=SID=PGID`). Also give each relaunch attempt a **fresh** log file, so liveness is checkable by the log's mtime rather than by re-reading a stale file, and don't rely on harness task-completion notifications for OS-detached processes — self-verify liveness (process alive + log mtime advancing) periodically instead.

**Amendment (2026-07-09):** `setsid` only protects against tool-call/shell session teardown. It does NOT survive a cloud-container recycle. On 2026-07-09 the whole firecracker microVM was reclaimed and rebooted at 09:13:49Z after an inactivity window; the entire process table was wiped, taking down two independent `setsid`-detached session-leader pollers (PIDs 6778 and 26112, both `PPID=1`) with it, while the disk/scratchpad survived intact. Evidence in [debugger-poller-silence-diagnosis.md](reports/debugger-poller-silence-diagnosis.md): `uptime -s` and `/proc/uptime` (~191s uptime), `PID 1 = /process_api --firecracker-init`, no OOM traces, and all scratchpad files' last writes clustered 08:51:27–46Z, just before the recycle. Conclusion: no local daemon is immortal in a cloud session. Long-running work must be (a) resume-safe on disk — append-only, keyed rows, not in-memory state — and (b) driven by externally re-armed checks (scheduled wake-ups, agent check-ins), never by a background process assumed to keep running unattended.

### RESOLVED 2026-07-10: wiki-eval silent 4k/512-token truncation + ±40-char judge context
Diagnosed by [debugger-wiki-eval-llm-truncation-audit.md](reports/debugger-wiki-eval-llm-truncation-audit.md)
and [code-reviewer-wiki-eval-harness.md](reports/code-reviewer-wiki-eval-harness.md), fixed by the wiki-eval
experiment-v2 rework (spec [2026-07-10-wiki-eval-experiment-v2.md](superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md)):

- **Silent truncation.** Extraction calls ran at a hardcoded `max_tokens=4096` ([client.py](../src/palimpsest/llm/client.py)
  default) and the judge at `max_tokens=512` ([wiki_eval.py](../scripts/wiki_eval.py), pre-rework); `finish_reason`
  was never read anywhere, so a truncated extraction reply silently became `[]` via `parse_surfaces` — a quiet
  recall loss, not a visible error. Fixed (`7e7ddfd`): `max_tokens=20000` for both roles
  (`DEFAULT_MAX_TOKENS`), and every call is gated (`_gate_reply`) on `finish_reason == "length"` (or empty
  content with `reasoning_tokens > 0`) — this is now a hard `LengthOverflowError`, never tolerated (spec Р15).
- **`parse_surfaces` silently returning `[]` on malformed replies is fixed** (`421c99d`): it now raises
  `ExtractionParseError` on a genuinely unparseable reply, distinct from an honest empty `[]`; the runner
  (`7e7ddfd`) catches and counts it per-paragraph (`n_extraction_parse_failures`/`parse_failed_paragraphs` in
  `meta.json`, pilot gate <1% of paragraphs) instead of a downstream metrics artifact silently under-counting.
- **±40-char judge context.** The judge saw a fixed `CONTEXT_PAD=40` character window around the mention
  (e.g. «…Малатья, Мальдия, Милидия, М»), not the sentence. Fixed (`421c99d`): `extract.sentence_context()`
  returns the full sentence(s) overlapping the mention span, via a deterministic stdlib splitter with
  RU-abbreviation/initials guards; `CONTEXT_PAD` is removed from code entirely. See
  [wiki-eval.md](stages/wiki-eval.md) "Prompts".

### `finish_reason=length` is now a hard error, not tolerated (spec Р15, 2026-07-10)
A deliberate policy reversal from the earlier "length → retry as transient" stance: any wiki-eval extractor
or judge call that comes back `finish_reason=="length"` (or empty content with `reasoning_tokens>0`, i.e. the
model spent its whole budget reasoning) now raises `LengthOverflowError`
([wiki_eval.py](../scripts/wiki_eval.py) `_gate_reply`) and **halts the run** with full diagnostics (model,
role, article/paragraph, usage) rather than being silently retried or degraded. Rationale: a length overflow
under the old policy corrupted the affected slice's numbers invisibly (see the RESOLVED entry above); a loud
halt means the operator raises the cap and `--resume`s from the intact checkpoint instead of shipping a
silently-truncated run. Not a bug — an explicit, owner-locked tradeoff (spec Р15): expect wiki-eval runs to
stop mid-flight on a genuine overflow, and treat that as a signal to inspect `calls.jsonl`, not as a crash to
route around.

### `gpt-5.4` leftover-resume completed a run after the model was already excluded (2026-07-10)
A stray `wiki_eval.py run --resume` process (launched before the owner's exclusion decision, spec
2026-07-10-wiki-eval-experiment-v2.md Р1) kept running unattended and finished the run's last article ("Яффа",
100/100, $6.05 total) after `gpt-5.4` had already been dropped from the v2 experiment scope (no run, no Table C
row). Per the invariant that predictions are never deleted, the merged `pred.jsonl`/`meta.json` were committed
as-is and archived (commit `275f8c7`) rather than discarded; the model stays excluded from Table C and from
the v2 experiment. Lesson: a background `--resume` loop started under an old scope must be killed, not just
ignored, once the scope changes — nothing currently guards against a stray resume process outliving an
owner's exclusion decision.

### RESOLVED 2026-07-10: `data/eval/wiki/gt.jsonl` silently drifted to 20/100 articles; `gt_v2.jsonl` was the real reference
Caught during the deepseek backfill pre-flight (see
[ml-engineer-deepseek-backfill.md](reports/ml-engineer-deepseek-backfill.md)): the file the wiki-eval CLI uses
as its `--gt` default, `data/eval/wiki/gt.jsonl`, contained only 20 of the 100 corpus articles, while the full
100-article reference lived in `data/eval/wiki/gt_v2.jsonl`. The v2 file was verified to reproduce the
committed deepseek metrics (4716/7174 = 0.6574) bit-identically; any run that trusted the CLI default after
the drift would silently evaluate on a 20-article subset and produce non-comparable numbers. Root cause (git
forensics, not drift): `gt.jsonl` was never touched after its 2026-07-03 pilot commit — a retired-pilot
fragment left in place after the v2 GT build (`dfd835c`/`b730db3`, 2026-07-05) landed under a different,
explicit `--out` path instead of overwriting the canonical default, and the script's own `DEFAULT_GT` was
never updated to point at it.

**Resolution (2026-07-10 gt-canonicalization, branch `claude/ner-translation-config-b0ozsc`, spec
[2026-07-10-gt-canonicalization.md](superpowers/specs/2026-07-10-gt-canonicalization.md)):**
`gt.jsonl` was overwritten with `gt_v2.jsonl`'s content (100 articles / 7 959 tuples, sha256
`5c6f407ed443bf0283f040eab0f6f560ee9165c7b5ba446944e4b0ba8cdb94c3`), becoming the sole canonical ground truth;
all live docs and script defaults now name only `gt.jsonl`. A coverage guard was added to
`scripts/wiki_eval.py`'s `run`/`ablate`/`report` commands: any prediction title absent from the loaded GT now
fails loudly (naming the mismatch count and both paths) instead of silently under-scoring, closing the
recurrence path. `gt_v2.jsonl` remains on disk as a byte-identical duplicate only until the in-flight deepseek
backfill's driver (which still reads it) lands — deferred deletion, not part of this fix.

### RESOLVED 2026-07-10: ru-wiki IPA-transcription templates linked every phoneme, inflating gold anchors
Ru-wiki's IPA/transcription template (and, separately, a section-nav arrow gadget and a cuneiform
determinative gloss) hyperlinks **every phonetic symbol/glyph to its own article**, e.g. the token
`[nijˈsiːwat` in «Тронное имя фараона» carried a separate `<a>` for each of `n`, `i`, `j`, `ˈ`, `s`, `ː`, `w`,
`a`, `t`. `extract_gt` (`wiki_gt.py`) treated every main-namespace `<a>` as a gold mention, so each glyph's
single-char `find()` aliased it onto whatever host token contained it, piling up to 9 spurious gold tuples on
one token. Root-cause diagnosis:
[debugger-ipa-parser-gold-anchors.md](reports/debugger-ipa-parser-gold-anchors.md). Blast radius: 56 spurious
tuples across 4 of the 100 corpus articles («Тронное имя фараона» 52, «Веды» 2, «Микенская цивилизация» 1,
«Нур-Адад» 1) — none of the 4 is in the 20-article gemini pilot corpus.

**Resolution.** `extract_gt` now drops a single-character anchor whose neighbour in the flattened text is a
letter/digit/combining-mark or bracket (`_is_symbol_fragment`, counted in the new `counters.n_excluded_symbol`,
never in `n_anchors`) — this catches per-glyph IPA/transliteration/nav-arrow links while keeping legit
standalone single-char anchors (a whole whitespace token, e.g. «У», or «V» in «V век»/em-dash Roman-numeral
ranges «X—XII»). `data/eval/wiki/gt.jsonl` was re-derived via an offline post-filter (same predicate, no
network) — 100 articles / **7 903** GT tuples (was 7 959); only the 4 affected articles' records changed byte-
for-byte, the other 96 are untouched. **Gotcha for future corpus additions:** any new ru-wiki article using an
IPA/transcription template will hit the same per-glyph link pattern — the guard handles it automatically, but
a corpus-wide re-derivation after adding articles should still spot-check `n_excluded_symbol` counts for
unexpectedly high per-article piles (Тронное's 52 was the tell before the fix existed).

### WikiHist corpus selection P31 gate does not exclude fictional-universe entities
**Discovered 2026-07-10**, during a full manual review of all 100 corpus articles. 5 articles passed the
automated selection gate (§Corpus in [wiki-eval.md](stages/wiki-eval.md)) despite being out of scope for an
ancient-history corpus: two fictional-universe topics («Гелиополиты» — Marvel's Heliopolitans, «Стигия» —
Conan's Stygia), one modern-geography article («Керченский пролив»), one modern historiographic concept
(«Кесарево безумие»), and one article whose body is roughly 72% post-cutoff content («Яффа»).

**Root cause.** The chronology gate's P31 blacklist covers only `{film, painting, museum}` (see
[wiki-eval.md](stages/wiki-eval.md) §Corpus). It has no entry for fictional-universe entities
(Wikidata P31 values like "comics location" or "fictional location"), and such items frequently carry no
`inception`/`start time`/`point in time` date at all, so they pass the gate's "undated pages kept" rule instead
of being caught by the date cutoff.

**Mitigation applied.** The owner approved replacing all 5 with the next seed-42 walk survivor from the same
section (re-running the selection reproduced the original candidate pools exactly); each replacement was
individually verified ancient via lead-paragraph + P31 inspection before being accepted. Provenance:
[data/eval/wiki/cleanup/replacements_2026-07-10.json](../data/eval/wiki/cleanup/replacements_2026-07-10.json).
This was a one-off manual fix, not a gate change — **the underlying gate gap is still open**: any future corpus
build (new sections, a re-run at a larger N) can reintroduce the same failure mode. Consider extending the P31
blacklist with fictional/comics/mythos-adjacent types, or adding a lightweight "is this a real historical
topic" LLM pre-check before an article enters the candidate pool.

### RESOLVED 2026-07-10: malformed provider response body killed a wiki-eval run

**Symptom.** During the 2026-07-10 wiki-eval deepseek mini-pilot (Phase 3a, run dir
`reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/2026-07-10T08-38-16Z`), an extraction
call on article 3 crashed the entire process with a raw `json.decoder.JSONDecodeError: Expecting value: line
169 column 1 (char 924)`, raised from httpx's `response.json()` inside the `openai` SDK — i.e. OpenRouter/Novita
returned an HTTP response body that was not valid JSON for a chat-completions call. `pred.jsonl`/`meta.json`
were never written (only `calls.jsonl`/`pred.partial.jsonl`/`progress.jsonl` survive); full incident writeup in
[docs/reports/wiki-eval-v2-pilot-2026-07-10.md](reports/wiki-eval-v2-pilot-2026-07-10.md) ("Phase 3a").

**Root cause.** `palimpsest.llm.client.is_transient_error` had no category for a malformed transport-layer
response body — it matched none of the recognized transient exceptions (`TimeoutError`/`APITimeoutError`/
`APIConnectionError`/`RateLimitError`/`InternalServerError`/`APIStatusError` with `status>=500`) — so it was
classified deterministic and **not retried at all**, killing the run on the very first occurrence. Every call
that DID complete around it was clean (0/90 `finish_reason=="length"`, 100% `reasoning_tokens>0`, 100% served
by the pinned provider on the captured calls) — this was an infra/transport reliability blip, not a
prompt/parameter/pin defect.

**Fix.** A safety analysis (before implementing) found that a naive "treat every `json.JSONDecodeError` as
transient" widening would have silently made content-level parse failures retryable too — specifically webapp
`judge_one`'s `_parse_json(result.content)` (`src/palimpsest/webapp/judge.py`), which parses the MODEL's own
reply text and runs entirely inside `_judge_live`'s `is_transient_error`-gated retry loop
(`src/palimpsest/webapp/app.py`). Retrying a genuinely malformed judge answer would contradict the documented
policy that malformed judge output is terminal (`judge_unavailable`, no retry —
[label_first.py](../src/palimpsest/terminology/grounding/label_first.py)).

Resolved instead by disambiguating at the transport boundary: `LLMClient.complete()`
([client.py](../src/palimpsest/llm/client.py)) now wraps ONLY its own transport call
(`self._client.chat.completions.create(**kwargs)`) — `except json.JSONDecodeError as exc: raise
MalformedProviderResponseError(str(exc)) from exc`. `is_transient_error` classifies
`MalformedProviderResponseError` and `openai.APIResponseValidationError` as transient. Because the wrapping
happens only around the transport call and `complete()` already returns before any caller parses
`result.content`, a bare `json.JSONDecodeError` — as raised by `judge_one`'s content parse, or by
`scripts/wiki_eval.py`'s own extraction/judge content parsers — never reaches this classifier and stays
terminal exactly as before; the fix is safe by construction rather than by convention. Covered by
`tests/test_llm_transient.py` (transient: `MalformedProviderResponseError`, `APIResponseValidationError`;
still-terminal regression pin: bare `json.JSONDecodeError`; transport-wrapping: a fake `chat.completions.create`
that raises `json.JSONDecodeError` makes `LLMClient.complete` raise `MalformedProviderResponseError`).

### `data/seed/terminology_gold.jsonl` not reproducible from `merge_goldens.py`

Discovered 2026-07-10 during the de-versioning cleanup Lane B verify (C6): a fresh
`python scripts/merge_goldens.py` run yields only **16 rows**, not the **99 rows** committed
at `data/seed/terminology_gold.jsonl`. Root cause: [merge_goldens.py](../scripts/merge_goldens.py)'s
own docstring claims the three gold sources sit "over the same 16-paragraph pilot corpus", but
[data/seed/seed_paragraphs.jsonl](../data/seed/seed_paragraphs.jsonl) — the seed corpus the merge
keys rows against via `paragraph_id` lookup — has only **15 paragraphs**. The drift predates every
2026-07-10 change (this repo's own de-versioning work never touched `merge_goldens.py`'s logic,
only a filename/comment/`_metrics_v1`→`_metrics` rename in C6); `git log` shows the seed corpus and
the docstring's paragraph count already disagreed at the initial import (`2493ec4`), so this is not
a regression introduced by any recent commit.

**Impact.** The committed 99-row `terminology_gold.jsonl` cannot be regenerated from its own
documented build recipe — anyone who reruns `merge_goldens.py` expecting to reproduce or refresh
the committed file gets a 16-row file instead, silently losing 83 rows.

**Mitigation.** None applied. Fixing the corpus/docstring mismatch is a data-regeneration task, out
of scope for the de-versioning cleanup that found it (naming/identifier cleanup only, no data
regeneration). Needs an owner decision: reconcile the docstring to 15 paragraphs (if 16 was always
wrong), or investigate whether a 16th paragraph existed and was dropped from
`seed_paragraphs.jsonl` at some point (if the committed 99-row gold is the one that's actually
correct and the corpus is missing data).
