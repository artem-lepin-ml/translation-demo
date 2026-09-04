# Debug report — red dot despite QID (Defect 1) and broken glossary trace (Defect 2)

Read-only root-cause investigation. No code changed. Live prod data pulled via
read-only `GET https://glossa-mt.com/api/documents/{1,13}` (python3 urllib,
2026-07-16). Local checkout: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`.

## Defect 1 — grounded term (has QID) still renders a RED difficulty dot

### Verdict
**Frontend mapping/grouping bug**, not a backend data bug. Every individual
`term` DB row honors the contract null rule (`difficulty=='red' ⇒ grounded=None`)
end to end. The red-with-QID row only exists in the **grouped** glossary view,
which is produced client-side by folding several per-mention rows (one row per
occurrence of a lemma in the document) into one glossary entry. The fold takes
the **worst** `difficulty` across all folded mentions but keeps the **QID from
whichever mention happened to ground successfully** — so one ungrounded (red)
inflected occurrence of an otherwise well-grounded entity paints the whole
entity's dot red while its Wikidata link stays intact.

### Chain, with evidence

**(a) Which field drives the dot, how it's computed/persisted**

- `terminology/pipeline.py:26-34` — `run()` enforces the null rule **per
  mention row**: `if gr.difficulty == "red": difficulty="red", grounded=None,
  candidates=[]`. `terminology/base.py:182-188` documents this contract
  explicitly on the `Term` dataclass.
- `terminology/grounding/label_first.py` — `LabelFirstGrounding.ground()`
  produces `difficulty` per the decision table in the module docstring
  (line 4-8): exact 1 exact-label match → green; ≥2 exact matches or 0-exact
  candidates-present → escalate to LLM (yellow/`llm_disambiguation` or
  red/`judge_rejected`); 0 candidates at all → red/`no_candidates`. This runs
  **once per mention (per occurrence)**, independently — grounding is not
  memoized across occurrences of the same entity.
- `webapp/db.py:56` — `term` table stores `difficulty`, `grounded_json`,
  `candidates_json` per paragraph/mention row.
- `webapp/app.py:106-117` (`_term_dict`) — wire DTO: `difficulty` (whitelisted
  to `{green,yellow,red}` via `_norm_verdict`), `grounded` (parsed
  `grounded_json`), verbatim, one row per occurrence.
- `webapp/app.py:200-213` (`_para_dict`) — `terms` for a paragraph queried
  `ORDER BY char_start`; `/api/documents/{id}` nests all paragraphs' `terms`.

Also checked and **ruled out** as the cause: `webapp/seed.py:171`
(`diff = VERDICTS[i % 3]`, a synthetic cyclic difficulty assignment used only
for un-enriched seed rows) forces `grounded=None` whenever `diff=='red'`
(seed.py:178-182) — so seed data alone can never violate the null rule either.
Confirmed doc 1 is 100% seed/mock data (`traceJson=={}` for all 204 terms,
`candidates` length ∈ {0,1} only — never the live pipeline's 0-5 range seen in
doc 13), consistent with `seed.py`/`enrich_seed_terms.py`, not `terminology_live.py`.

**(b) Frontend mapping — the actual defect**

`frontend/src/demo/variant-a/glossary-grouping.ts`:
- `groupTerms()` (lines 260-349) groups per-occurrence `Term` rows into one
  glossary row per **stem** (a Russian case-ending heuristic stemmer,
  lines 206-238, documented as a known limitation in
  `docs/known_issues.md` "Glossary grouping's Russian stemmer fallback is a
  heuristic, not lemmatization") **+ qid**.
- `buildFields()` (lines 278-292) computes the group's `difficulty` as
  `worseVerdict` folded across **all mentions in the bucket** (green < yellow
  < red, `SEVERITY_RANK` line 162) — this treats "difficulty" as if it were a
  property of the whole entity, when at the per-row level it is actually a
  property of *this one occurrence's grounding attempt*.
- The wave5-driven merge pass (lines 319-345, added to fix duplicate rows like
  "Тигр"/"Тигра") folds an **ungrounded** raw-lemma stem-bucket into a
  **grounded** stem-bucket when their heuristic stems coincide. The merge
  (lines 336-341) recomputes `difficulty`/`pair`/`translation` via
  `buildFields(allMentions)` but **never touches `target.qid` /
  `target.grounded`** — those stay pinned to the original grounded draft.
  Net effect: **qid/grounded survive the merge, difficulty does not** —
  exactly the observed defect.
- `GlossaryTab.tsx:184` renders the dot straight off the merged value:
  `<span className={\`va-verdict-dot ${group.difficulty}\`} .../>`.

**This exact behavior is codified as intended in the test suite** —
`frontend/src/demo/variant-a/__tests__/glossary-grouping.test.ts:157-168`
(`'merges "Тигр" (grounded) with "Тигра" (ungrounded) ...'`) asserts
`groups[0].qid === 'Q35591'` **and** `groups[0].difficulty === 'red' //
worst-of across the merged mentions` in the same test. A second test at
lines 92-98 asserts the same worst-of-across-mentions rule even without a
merge. This is almost certainly *why the bug recurred 3 times*: each prior
fix likely patched the visible symptom (re-seeded/re-enriched the specific
reported term so it no longer split into a red+green pair) without touching
the merge/fold logic itself, which the test suite actively locks in as
correct. The next document/term that happens to hit the same
grounded-plus-raw-lemma-ungrounded-sibling pattern reproduces the identical
defect.

**(c) Real prod evidence — doc 1, "Месопотамия"**

`GET /api/documents/1`, 23 term rows match `*месопотам*`. Reproduced the exact
TS `groupTerms()` logic in a faithful Python port against the real rows
(script run locally, not committed) and confirmed **3 of 8 resulting groups**
show a QID with `difficulty=red`:

| stem (heuristic) | qid | difficulty | mentions | surfaces folded in |
|---|---|---|---|---|
| `месопотами` | **Q11767** | **red** | 6 | Месопотамия (id 181, own difficulty=yellow, grounded), Месопотамию×2 (id 275, 384, red/no_candidates, `sourceLemma==sourceSurface` — raw/unnormalized lemma) |
| `нижн месопотами` | **Q11767** | **red** | 3 | Нижняя/Нижней Месопотамия (green, grounded) + Нижней Месопотамией (id 367, red, raw lemma) |
| `верхн месопотами` | **Q311819** | **red** | 2 | Верхняя Месопотамия (id 208, green, grounded Upper Mesopotamia) + Верхнюю Месопотамию (id 362, red, raw lemma) |

Raw evidence, trimmed (full paragraph list has 15 entries; the two mentions
that merge into the reported red group):

```json
// id 181 — grounds fine on its own (yellow, has QID)
{"sourceSurface":"Месопотамия","sourceLemma":"Месопотамия","difficulty":"yellow",
 "grounded":{"qid":"Q11767","label":"Mesopotamia", ...}, "candidates":[{"qid":"Q11767", ...}]}

// id 275 — same entity, accusative surface, lemma never normalized (raw),
// grounding failed for THIS inflected form specifically
{"sourceSurface":"Месопотамию","sourceLemma":"Месопотамию","difficulty":"red",
 "grounded":null,"candidates":[]}
```

Both share the heuristic stem `"месопотами"` (RU case-ending stripper,
`glossary-grouping.ts:206-220`) → same merge key → id 275's `red` overrides
id 181's `yellow` for the group's `difficulty`, while `grounded` is still
sourced from id 181. The glossary row for "Месопотамия" shows the red dot
plus a live Wikidata link to Q11767 — exactly the reported symptom.

Underlying contributing cause (why so many raw-lemma occurrences ground
red at all for an already-known entity): `extract.py`'s NER step does not
always produce a normalized (nominative) `source_lemma` — when it doesn't,
`source_lemma === source_surface` (the inflected form), and
`grounding/candidates.py`'s Wikidata search runs against that raw inflected
Russian surface, which frequently misses the (nominative-labeled) Wikidata
entry entirely → `no_candidates` → red. This is a pre-existing, documented
gap (`docs/known_issues.md`, "Glossary grouping's Russian stemmer fallback
...": *"The durable fix is upstream — normalize source_lemma in the
terminology extraction pipeline so it stops equaling the raw surface"*).

### Fix plan (minimal, per lane)

1. **Frontend lane (owns the reported defect, low risk, no contract change)**
   — `frontend/src/demo/variant-a/glossary-grouping.ts`. Stop letting a merged
   *ungrounded* sibling override the *grounded* group's headline difficulty.
   Concretely, in the merge block (lines 330-345) and in `buildFields`
   (278-292): when the group has a `qid`, compute `difficulty` as the
   worst-of only across mentions that share that `qid` (i.e. mentions that
   actually attempted/matched the same entity), not across every raw-lemma
   sibling folded in purely for de-duplication. Surface the fact that N of M
   occurrences didn't individually ground via the existing "All mentions"
   panel (`GlossaryTab.tsx:344-364`, already lists every mention) rather than
   via the headline dot. Update/extend the two tests that currently assert
   the old (buggy) behavior
   (`glossary-grouping.test.ts:92-98` and `:157-168`) — they need to change
   from "worst-of always wins" to "worst-of among same-qid mentions only".
2. **Terminology backend lane (durable root-cause fix, already tracked,
   larger scope — not required to close the immediate defect)** —
   `terminology/extract.py`'s lemmatizer should normalize `source_lemma` to
   the nominative form at NER time so `source_lemma !== source_surface` for
   inflected occurrences, letting Wikidata search run against a normalized
   query and ground consistently across all occurrences of the same entity.
   This removes the underlying green/red split at its source, independent of
   any frontend grouping fix. Already documented as future work in
   `docs/known_issues.md`.
3. Do **not** touch `webapp/seed.py`'s `VERDICTS[i % 3]` cycling — investigated
   and ruled out; it cannot itself produce QID+red (the null rule is enforced
   in the same function, seed.py:178-182), and doc 1's real prod data
   confirms every individual row already honors the invariant.

---

## Defect 2 — Glossary trace view: candidates/"Matched" column broken

### Verdict
Two distinct, both **frontend** bugs, rooted in the same cause: the frontend's
`TraceJson`/candidate types were written **ahead of** the real backend trace
shape (`glossary-grouping.ts:10-14` literally calls it "forward-looking...
today's seed data ships trace_json='{}' for every row") and were never
reconciled once the live pipeline (`terminology_live.py`, shipped
2026-07-11) started emitting real, differently-shaped `trace_json`.

### 2a. "Matched" column always shows "none"

- `GlossaryTab.tsx:47-50` — the `CandidateWithMatch` type comment states
  outright: *"the wire `WikidataRef` type has no `matched_via` field, so it's
  a local, optional extension"*. It is never populated by the backend —
  `WikidataRef.as_dict()` (`terminology/base.py:130`) returns exactly
  `{qid, url, label, description}`.
- `GlossaryTab.tsx:248` — `const candidates = primary.candidates as
  CandidateWithMatch[]` reads `term.candidates` (persisted `candidates_json`,
  i.e. the wire `grounded`/`candidates` DTO fields) — **not** the trace.
- `GlossaryTab.tsx:324` — `<span className={viaChipClass(c.matched_via)}>
  {c.matched_via || 'none'}</span>` — `c.matched_via` is `undefined` for
  every candidate on every term, unconditionally, so this literally always
  renders `"none"`.
- The real per-candidate match provenance **does exist**, but under a
  different key, in a different object, that the frontend never reads for
  this column: `terminology/grounding/label_first.py:134-137`
  (`candidates_traced = [{**c, "matched": ...} for c in candidates]`) and
  `label_first.py:300-323` (`_result()`) put it in
  `trace["candidates"][i]["matched"]`. Confirmed on real prod doc 13 (term
  "Цинь", id 515): `traceJson.candidates[0].matched ==
  {"kind":"label_ru","value":"Цинь","query":"Цинь"}` — real, useful data that
  never reaches the "Matched" column.

**Fix (frontend only, no backend/contract change needed):** in `GroupDetail`
(`GlossaryTab.tsx:240-330`), build the "Matched" column from
`primary.traceJson?.candidates` (keyed by `qid`) instead of from
`primary.candidates[].matched_via`. Drop the dead `matched_via` field/type
extension once the real source is wired in.

### 2b. "Ambiguous senses"/Candidates(N) table sometimes shows N=1 for an "LLM-disambiguated" (yellow) term

Verified against real prod doc 13 that `term.candidates.length` is **not**
uniformly 1 — histogram across 179 terms: `{0:26, 1:11, 2:4, 3:2, 4:5, 5:29}`
— `generate_candidates` (`terminology/grounding/candidates.py:138-257`) is
capped by `GroundingConfig.enrich_top=5` (`terminology/base.py:60`), not 1,
and is not truncated anywhere before persistence
(`pipeline.py:42-48` → `Term.db_tuple()` → `webapp/terminology_live.py:268`
insert, verbatim).

However, a real, reproducible **N=1** sub-case exists and does explain what
was likely observed: `label_first.py:139-152`'s decision table escalates to
the LLM judge whenever `len(exact_matches) != 1` — that includes the case
`len(exact_matches) == 0` with only **one** total candidate (a single
non-exact/fuzzy Wikidata hit). The judge is then asked to confirm/reject that
lone candidate, and the UI labels the whole thing "offered to the judge" /
ambiguous, even though there was never more than one option. Two concrete
real doc-13 examples (both `resolved_by: "llm_disambiguation"`,
`exact_matches: []`, exactly 1 trace/term candidate):

```json
{"sourceSurface":"Чжанцзячуань-Хуэй","difficulty":"yellow",
 "grounded":{"qid":"Q197375","label":"Zhangjiachuan Hui Autonomous County"},
 "term_candidates":[{"qid":"Q197375", ...}],
 "trace.exact_matches":[], "trace.candidates[0].matched": null}

{"sourceSurface":"Му-гуна","difficulty":"yellow",
 "grounded":{"qid":"Q1146646","label":"Duke Mu of Qin"},
 "term_candidates":[{"qid":"Q1146646", ...}],
 "trace.exact_matches":[], "trace.candidates[0].matched": null}
```

This is not a truncation bug in `candidates.py` (ruled out — no `[:1]`
slicing before enrichment; `enrich_top` defaults to 5) and arguably not a bug
in `label_first.py` either — calling the judge to confirm a single fuzzy
candidate rather than auto-accepting a non-exact string match is a
defensible design choice. It **is** a UI-copy/semantics mismatch: a
single-candidate "confirm" pass gets the same "ambiguous senses / offered to
the judge" framing as a genuine multi-candidate disambiguation.

**Fix (frontend copy only, cosmetic, low priority):** in
`GlossaryTab.tsx:294-296`, special-case `candidates.length === 1` under the
`'llm'` tone with different copy (e.g. "single candidate — confirmed by
LLM") instead of reusing "Candidates (N) · offered to the judge" verbatim. No
backend change needed.

### 2c. Related, higher-severity finding not explicitly asked for but directly adjacent

The "Grounding path" 4-step panel (`GlossaryTab.tsx:270-288`,
`stepPresentation()` lines 91-155) reads `trace?.query`, `trace?.search`,
`trace?.label_match`, `trace?.decision` — a **nested** shape
(`TraceJson`/`TraceStep`, `glossary-grouping.ts:16-39`) that **never existed**
in the real backend output. `label_first.py:300-323`'s actual `trace` dict is
**flat**: `{v, config, queries, search_source, candidates, exact_matches,
resolved_by, judge, chosen_qid, canon_en, n_api_calls, latency_ms}`. Since
none of `query`/`search`/`label_match`/`decision` exist as keys, every one of
the 4 steps hits `stepPresentation`'s `if (!step) return {state:'skip',
title:'Skipped', body:'no trace'}` (line 96-97) — **for every live-pipeline
term, always**. Confirmed on doc 13's real `traceJson` (both examples above
and the "Цинь"/"Китае" examples pulled earlier). `resolveBadge()`
(`glossary-grouping.ts:82-134`) happens to read `trace?.resolved_by` at the
top level first (line 84) so badge tone/label computation is *not* affected
— only the step-by-step "Grounding path" visualization is dead for all real
data. Same lane/fix as 2a (frontend, `glossary-grouping.ts` + `GlossaryTab.tsx`
— rewrite `stepPresentation`/`TraceJson` against the real flat schema instead
of the forward-looking guess). Flagging because it is the most visually
obvious part of "the trace view is broken" and likely contributed to how the
defect was perceived/reported, even though it wasn't literally named in the
ticket.

---

## Files referenced

- `frontend/src/demo/variant-a/glossary-grouping.ts` (grouping, badge, trace types)
- `frontend/src/demo/variant-a/GlossaryTab.tsx` (dot rendering, candidates/Matched table, trace-step panel)
- `frontend/src/demo/variant-a/TermPopover.tsx` (Document-tab popover, separate "Ambiguous senses" label, same underlying `term.candidates` field — not independently broken)
- `frontend/src/demo/variant-a/__tests__/glossary-grouping.test.ts` (tests that currently assert the Defect-1 behavior as correct)
- `src/palimpsest/terminology/pipeline.py`, `terminology/base.py`, `terminology/grounding/label_first.py`, `terminology/grounding/candidates.py`
- `src/palimpsest/webapp/app.py` (`_term_dict`, `_para_dict`, `/api/documents/{doc_id}`), `webapp/db.py`, `webapp/seed.py`, `webapp/terminology_live.py`
- `docs/known_issues.md` (pre-existing documentation of the stemmer-fallback rationale and the lemma-normalization gap)

## Not done / out of scope

- No code changes made (read-only investigation per task instructions).
- Did not check documents other than 1 and 13, or search for further real
  instances of the "raw-lemma sibling merges into a grounded stem" pattern
  beyond doc 1's Mesopotamia rows (3 groups found there were sufficient to
  confirm the mechanism).
- Did not run the existing test suite (`glossary-grouping.test.ts`) — cited
  from source only; recommend running it as part of the fix PR to confirm
  which assertions need updating.
- Did not investigate whether `webapp/seed.py`'s `enrich_seed_terms.py`
  candidate stamping (doc 1's candidates length always ∈ {0,1}) is itself a
  defect — it's seed/mock data, out of scope for a prod-trace investigation,
  and not what the task's doc-13 trace ask was about.
