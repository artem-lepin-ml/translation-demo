# Provider naming: CloseRouter → OpenRouter (public-facing rename)

Scope: rename every public-facing mention of the real upstream LLM gateway
("CloseRouter" / `CLOSEROUTER_*` / `api.closerouter.dev`) to "OpenRouter" in
code, env-var names, tests, and docs, across two checkouts:

- Phase 1: `translation-demo` worktree at `/Users/a1111/Projects/Work/worktrees/provider-naming`, branch `feat/provider-naming`.
- Phase 2: public repo `glossa-mt` at `/Users/a1111/Projects/Work/glossa-mt`, branch `main`, amending its single "Initial public release" commit.

The real gateway name stays untouched in the exempt directories per the task
brief (`.claude/`, `docs/experiments/`, `docs/reports/`, `docs/research/`,
`docs/superpowers/`, `external/`, `patches/`) — nothing there was edited.

## Phase 1 — translation-demo (`feat/provider-naming`)

### Files changed (11)

| File | What changed |
|---|---|
| `src/palimpsest/llm/client.py` | Prose-only: 3 comments renamed the gateway; the `cost`/`cost_usd` comment was reworded to "some provider routes" since it previously contrasted OpenRouter vs. CloseRouter by name |
| `scripts/wiki_eval.py` | Env vars `CLOSEROUTER_MODEL`/`CLOSEROUTER_PROVIDER` → `OPENROUTER_MODEL`/`OPENROUTER_PROVIDER`; `WIKI_EVAL_PROVIDER` default `"closerouter"` → `"openrouter"`; **folded** the old `closerouter` branch and the old `openrouter` branch (real openrouter.ai, hardcoded `anthropic/claude-haiku-4.5`, no provider pin) of `_resolve_route()` into one `openrouter` branch that keeps the current (former-`closerouter`) behaviour: configurable model/provider, `extra_body={"provider": ...}` pin (`None` on `"auto"`), and now defaults its base URL to `https://openrouter.ai/api/v1` via `OPENROUTER_BASE_URL`. The `openai-direct` fallback branch is untouched. CLI help strings and docstrings updated to match. |
| `scripts/eval_grounding.py` | Same env-var rename; same branch fold (its `elif "openrouter"` branch was already reusing `CLOSEROUTER_MODEL`, i.e. it and the `closerouter` branch differed only in base URL/extra_body — folded into one `openrouter` branch, base URL now `OPENROUTER_BASE_URL` defaulting to `https://openrouter.ai/api/v1`) |
| `scripts/fix_mention_lemmas.py` | Env-var rename + base-URL literal + one prose mention |
| `scripts/probe_providers.py` | Prose (module docstring, WAF comment) + base-URL literal |
| `scripts/rebuild_demo.py` | Prose (module docstring, `_build_judge` docstring, log string) + env-var rename + base-URL literal |
| `docs/known_issues.md` | Two `###` headings renamed (`... on CloseRouter provider-9 ...` → `... on OpenRouter provider-9 ...`; `CloseRouter: provider-9 pin ...` → `OpenRouter: provider-9 pin ...`) |
| `docs/stages/terminology.md` | 2 prose mentions |
| `docs/stages/translation-eval.md` | 3 prose mentions + the known_issues.md anchor link updated to match the renamed heading slug |
| `docs/stages/wiki-eval.md` | Full rewrite of the "Provider" and "Judge wiring" design-decision bullets to describe the folded single `openrouter` branch (env vars, default value, WAF sentence, `cost`/`cost_usd` wording); env-var mentions elsewhere in the doc |
| `docs/testing/e2e-data.md` | 1 prose mention |

### Env-var / default changes (exact)

- `CLOSEROUTER_MODEL` → `OPENROUTER_MODEL` (default unchanged: `google/gemini-3.1-flash-lite`)
- `CLOSEROUTER_PROVIDER` → `OPENROUTER_PROVIDER` (default unchanged: `provider-9`)
- `WIKI_EVAL_PROVIDER` default value `"closerouter"` → `"openrouter"` (the two scripts that read it, `wiki_eval.py`/`eval_grounding.py`); the removed literal `"openrouter"` fallback value is gone because it's now the default, not a distinct branch
- Base URL: the hardcoded literal `https://api.closerouter.dev/v1` is gone everywhere; every call site now reads `os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")` — the real gateway URL is supplied through `.env`'s `OPENROUTER_BASE_URL`, unchanged from before this rename (that variable already existed and already carried the real URL at runtime; only its *hardcoded fallback* changed)

### Deliberate exceptions (not touched, and why)

`docs/known_issues.md:149` and `docs/stages/translation-eval.md:92` still contain
the literal substring `closerouter` — both are markdown links to
`docs/reports/2026-07-07-deepseek-closerouter-smoke.md`, a file under the
exempt `docs/reports/` directory. I did not rename that report file (out of
scope per the brief: "Do not touch those directories"), so the link's `href`
must keep spelling the real filename to resolve. This makes the literal
`git grep -il closerouter -- ... docs/known_issues.md` gate **not**
byte-for-byte empty — see the pasted output below. I judged preserving a
working link to an off-limits artifact over blindly renaming/breaking it;
flagging this rather than silently declaring the gate green.

### Verification gate (pasted output)

```
$ git grep -il closerouter -- src scripts tests docs/stages docs/subsystems docs/testing README.md docs/known_issues.md deploy .env.example
docs/known_issues.md
docs/stages/translation-eval.md
```
Both hits are the single link to the exempt `docs/reports/...closerouter-smoke.md`
file described above — no other file in scope contains the string. Full-repo
recheck excluding all seven exempt directories:
```
$ git grep -il closerouter -- . ':!.claude' ':!docs/experiments' ':!docs/reports' ':!docs/research' ':!docs/superpowers' ':!external' ':!patches'
docs/known_issues.md
docs/stages/translation-eval.md
```
(same two link-only hits).

```
$ for f in scripts/*.py; do .venv/bin/python -m py_compile "$f"; done
(no output — all compiled clean)
```

```
$ .venv/bin/python -m pytest -q --no-header -p no:cacheprovider
674 passed in 6.36s
```
Matches the stated baseline of 674 exactly — no test count regression or gain.

### Commit

`feat/provider-naming` @ **`f0efedd`** (sha as of the last amend that added this report file to the commit — self-referential; check `git log -1` on the branch for the exact final value, since amending this file changes the commit's own hash) — `refactor(llm): name the gateway OpenRouter in code, env vars, tests and docs`. Not pushed.

## Phase 2 — glossa-mt (`main`, amended)

`glossa-mt` is a point-in-time export of an earlier translation-demo state
(single squashed "Initial public release" commit `69924c2`), so most of the
11 closerouter-bearing files were **byte-identical** to translation-demo's
pre-rename originals — confirmed by diffing against `git show 8f080fa:<path>`
before editing (`client.py`, `rebuild_demo.py`, `fix_mention_lemmas.py`,
`probe_providers.py`, `wiki_eval.py` module body, `eval_grounding.py` module
body were all identical modulo a stripped spec/plan docstring line, which the
public release already omits). I applied the exact same fold/rename to those
files. The four docs (`known_issues.md`, `terminology.md`, `wiki-eval.md`,
`e2e-data.md`) had diverged more (public-release doc trims elsewhere in the
same files), so each closerouter-bearing line was located and edited directly
in this checkout rather than copy-pasted from translation-demo's diff.

### Files changed (14)

11 from the closerouter rename (same set as Phase 1, minus
`translation-eval.md` which doesn't exist in this repo, plus
`tests/test_wiki_eval_runner.py` which doesn't exist in translation-demo) +
3 for the EMNLP→EACL venue update:

- `src/palimpsest/llm/client.py`, `scripts/wiki_eval.py`,
  `scripts/eval_grounding.py`, `scripts/fix_mention_lemmas.py`,
  `scripts/probe_providers.py`, `scripts/rebuild_demo.py` — identical edits
  to Phase 1 (verified byte-identical post-edit for the 5 files that were
  byte-identical pre-edit).
- `docs/known_issues.md`, `docs/stages/terminology.md`,
  `docs/stages/wiki-eval.md`, `docs/testing/e2e-data.md` — same prose
  substitutions as Phase 1, applied directly (this repo's
  `docs/known_issues.md` version had already dropped the report-link text
  for the deepseek smoke, so there is no residual `closerouter` link here —
  Phase 2's gate is clean where Phase 1's isn't).
- `tests/test_wiki_eval_runner.py` (glossa-mt-only file): renamed
  `test_resolve_route_defaults_to_closerouter_env_values` →
  `..._openrouter_env_values`; `wiki_eval.CLOSEROUTER_MODEL`/
  `CLOSEROUTER_PROVIDER` → `OPENROUTER_MODEL`/`OPENROUTER_PROVIDER`; 3 prose
  mentions in comments/docstrings. No test *logic* changed — the tests
  exercise the default (`model=None, provider=None`) `_resolve_route()` path,
  which is exactly the folded `openrouter` branch; nothing in this test file
  exercised the now-removed fixed-model `openrouter` fallback branch, so the
  fold required no test rewrite beyond the rename.
- `README.md` — badge `EMNLP%202026-System%20Demonstrations%20(submitted)`
  (alt `EMNLP 2026 (submitted)`) → `EACL%202027-System%20Demonstrations%20(in%20preparation)`
  (alt `EACL 2027 (in preparation)`); "Submitted to the **EMNLP 2026 System
  Demonstrations** track." → "Target venue: **EACL 2027 System
  Demonstrations** (in preparation)."
- `docs/README.md`, `docs/goals/demo-positioning.md` — two further "EMNLP
  demo-track" mentions found by the repo-wide grep, updated to "EACL
  demo-track" for consistency with the badge/paper-section change.

Also deleted per the brief: `.pytest_cache/` and every project `__pycache__/`
(`tests/`, `scripts/`, `src/palimpsest/**`) — all gitignored, so this has no
effect on the diff/commit, done for hygiene as instructed. `.venv/`'s own
site-packages caches were left alone (third-party, gitignored, irrelevant to
the rename).

### Deliberate exception — NOT done, and why

Two `EMNLP` mentions in `docs/api-contracts.md` (lines 282, 297) were **left
unchanged**: *"format modeled after KD-MT, EMNLP 2024"* and *"the exact
formula from KD-MT, EMNLP 2024, will be pinned down..."*. These are citations
of a real third-party paper's actual publication venue and year (KD-MT was
published at EMNLP 2024) — not a reference to this project's own submission
target. Rewriting them to "EACL 2027" would misstate when someone else's
paper was published, which is a factual/citation error, not a venue-tracking
update. This is the one deviation from the literal instruction "grep the
whole README and docs for any other EMNLP and change it the same way" — I
judged the citation's factual accuracy as the higher-priority rule and did
not touch it. Flagging explicitly rather than silently passing the gate.

### Verification (pasted output)

```
$ grep -rli closerouter --exclude-dir=.git .
(no output)
```
Clean — the 11 files that mirror translation-demo's rename, plus the
glossa-mt-only test file, all cleared.

```
$ grep -rn EMNLP --exclude-dir=.git .
docs/api-contracts.md:282:**Terminology-module glossary** (its knowledge store; format modeled after KD-MT, EMNLP 2024 — disambiguation by context, not by type):
docs/api-contracts.md:297:- ... *(The exact formula from KD-MT, EMNLP 2024, will be pinned down when the terminology module is assembled.)*
```
Not empty — see the deliberate-exception note above. Both remaining hits are
the KD-MT citation, deliberately untouched.

```
$ .venv/bin/python -m pytest -q --no-header -p no:cacheprovider   # run from glossa-mt root, using translation-demo's .venv
571 passed in 4.07s
```
No collection errors, no missing-optional-dep skips to report. 571 vs.
translation-demo's 674 is expected — glossa-mt is a trimmed public export
with fewer test modules; it does gain 1 file (`test_wiki_eval_runner.py`,
~40 tests) that translation-demo lacks.

### Commit

Rewrote the single commit in place:
```
$ git add -A && git commit --amend --no-edit
```
New commit: **`54151e0`** "Initial public release" (message unchanged).
`git status` after amend: clean working tree, no untracked files, branch
`main` diverged from `origin/main` by the amend (not pushed, as instructed).

## Open questions

None outstanding for the mechanical rename itself. One judgment call to flag
to the owner: whether the two link-only `closerouter` residues in
translation-demo (`known_issues.md`, `translation-eval.md`, both pointing at
`docs/reports/2026-07-07-deepseek-closerouter-smoke.md`) and the two KD-MT
citation residues in glossa-mt (`docs/api-contracts.md`) are acceptable as
permanent state, or whether the owner wants the exempt-directory report file
itself renamed at some point (which would let the link text go fully clean
too) — I did not do that since it was explicitly out of scope here.

## NOT done (explicit)

- Did not rename or touch anything under `docs/reports/` in either repo
  (out of scope, explicitly listed as exempt) — including the file
  `2026-07-07-deepseek-closerouter-smoke.md` that two links point at.
- Did not touch the two `KD-MT, EMNLP 2024` citations in glossa-mt's
  `docs/api-contracts.md` — factual citation to a real external paper, not
  this project's venue.
- Did not push either branch/commit (translation-demo `feat/provider-naming`,
  glossa-mt `main`) — both instructed "Do NOT push".
- Did not touch `.env.example` in translation-demo — it does not list any
  gateway vars today, and the brief said not to add a new section if so.
- Did not touch `deploy/` in translation-demo — grepped, no hits.
