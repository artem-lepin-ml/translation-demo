# sr004 patches for `gse-translation` (Danil's repo, branch `artem`)

Unified diffs against the code vendored at
[external/gse-translation](../../external/gse-translation/) (upstream commit
`3c1703ab89a8a5a424f2a896c4646ce360bbf116`). Paths inside each patch are
relative to **Danil's repo root** (`a/scripts/...`, `b/src/...`), not to this
repo — apply them inside a fresh clone of
`ru2en-enciclopedia-translation@artem` on sr004, per
[docs/stages/translation-eval.md](../../docs/stages/translation-eval.md).

Fixes the 5 code traps from
[docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md](../../docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md)
§0/§9. Every patch was verified with `git apply --check` against the vendored
snapshot in this repo (see each patch's own verification note below) — never
applied for real here, since `external/` is read-only.

## Apply order

Independent of each other (no two patches touch overlapping hunks), so any
order works, but apply in numeric order for a clean, boring log:

```bash
cd /path/to/ru2en-enciclopedia-translation   # Danil's repo, branch artem, on sr004
git checkout artem
git apply /path/to/translation-demo/patches/gse-translation-sr004/01-parametrize-translate-out-dir.patch
git apply /path/to/translation-demo/patches/gse-translation-sr004/02-remove-dead-chunking-flag.patch
git apply /path/to/translation-demo/patches/gse-translation-sr004/03-strip-gemma-universal-custom-artifact.patch
git apply /path/to/translation-demo/patches/gse-translation-sr004/04-refinement-meta-json.patch
git apply /path/to/translation-demo/patches/gse-translation-sr004/05-openai-client-user-agent.patch
```

Or in one shot:

```bash
cd /path/to/ru2en-enciclopedia-translation
for p in /path/to/translation-demo/patches/gse-translation-sr004/*.patch; do
  git apply --check "$p" && git apply "$p"
done
```

`--check` first is cheap insurance: Danil's `artem` branch may have moved past
`3c1703a` by the time you run this on sr004. If a `--check` fails, diff the
live file against `external/gse-translation/<path>` in this repo to see what
changed upstream, then hand-port the same edit.

## Patches

| # | File touched (Danil's repo) | Concern | Verdict |
|---|---|---|---|
| [01-parametrize-translate-out-dir.patch](01-parametrize-translate-out-dir.patch) | `scripts/02_translate_json.py` | spec §0/§9 trap (2): `_build_out_dir` hardcoded `data/pilot/translating` | **Patched** — confirmed by reading the vendored file: no CLI flag existed to redirect output. Adds `--out-root` (default = old hardcoded path, so existing pilot invocations are unaffected byte-for-byte); wiki runs pass `--out-root data/wiki/translating`. |
| [02-remove-dead-chunking-flag.patch](02-remove-dead-chunking-flag.patch) | `scripts/02_translate_json.py` | spec §0/§9 trap (1): `--chunking` accepted but dead | **Patched, minimal choice = remove.** Confirmed: `chunking` is a required Typer option but `_run()` is called with `# chunking=chunking,` commented out — the value is parsed and then dropped, never reaches chunked-mode logic (which is itself fully commented out in this file, lines ~86-119). Wiring it would mean resurrecting the entire commented-out `translate_chunked` branch — a much larger, riskier change than the spec's "prefer the minimal safe change" calls for, and out of scope (spec §1 non-goals: chunking is out of scope for this eval). Removing the flag means callers stop being forced to pass a bogus `--chunking` path for a per-paragraph-only run. |
| [03-strip-gemma-universal-custom-artifact.patch](03-strip-gemma-universal-custom-artifact.patch) | `prompts/02_translate/gemma_universal.md` | spec §0/§9 trap (3): stray `<<<custom>>>` literal | **Patched, with a discrepancy note.** The literal string `<<<custom>>>` is confirmed at byte offset 0 of the file, sent verbatim to the model as part of the user message (`load_prompt()` in `src/palimpsest/translate_json.py` does a plain `read_text`, no stripping/parsing of `<<<...>>>` anywhere in the codebase). **Discrepancy:** grepped the entire vendored tree for a `<<<source>>>...<<<target>>>...<<<text>>>`-style delimiter convention (the pattern named in the task brief) — it does not exist anywhere in `external/gse-translation/`. No code parses `<<<...>>>` tokens at all. This is not a delimiter protocol Danil's code implements; `<<<custom>>>` looks like a leaked tag from whatever prompt-authoring tool exported these three `gemma_*.md` files (it appears verbatim at the start of `gemma_translate.md` and `gemma_translation_prompt.md` too — see "Not patched" below). The fix is a straight deletion of the leaked prefix, not a reconciliation with some other delimiter scheme. Confirmed via `data/bouquet/translation/translate-gemma-bouquet/config.json` that `gemma_universal.md` (not the other two `gemma_*.md` files) is the prompt actually used for the real TranslateGemma BOUQUET run (`prompt_path: null`, `user_prompt_path: "02_translate/gemma_universal.md"` — no system role, matches spec §0). |
| [04-refinement-meta-json.patch](04-refinement-meta-json.patch) | `src/palimpsest/refinement.py` | spec §0/§9 trap (4): refinement writes no manifest | **Patched.** Confirmed `run_refinement()` in `src/palimpsest/refinement.py` writes only `translation.json`/`translation.md` — no config/meta file, unlike `scripts/02_translate_json.py` (`config.json` via `write_run_artifacts`) and `src/palimpsest/scoring.py` (`meta.json` per judge/factcheck dir, `judge`/`variant`/`paragraph_subset`/`prompts`/`totals`). Adds a `meta.json` next to the refinement output with `scores_jsonl` (which judge report drove this pass), `output`, `editor_model`, `system_prompt`, `refinement_criterias`, `created_at` — same shape/spirit as the existing `meta.json` writers, so a refined run directory is self-describing without cross-referencing `configs/refinement.yaml` by hand. |
| [05-openai-client-user-agent.patch](05-openai-client-user-agent.patch) | `src/palimpsest/llm/client.py` | spec §0/§9 trap (5): no `User-Agent` on the OpenAI-compat client | **Patched.** Confirmed `AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)` in `LLMClient.__init__` passes no `default_headers`. Our own client (`src/palimpsest/llm/client.py` in *this* repo, not vendored) hits the identical CloseRouter WAF issue and works around it with `default_headers={"User-Agent": "palimpsest-llm/1.0"}` — this patch copies that exact fix (same header value, so CloseRouter/WAF logs can't distinguish which codebase made the call). Minimal: touches only the `AsyncOpenAI(...)` construction, no other client behavior changes. Per the 2026-07-07 deepseek CloseRouter smoke test, no 403 was observed *without* this patch in that session, but the fix is held ready per the spec (§0 Ф-1: "watchpoint... patch-заготовка (default_headers) держится наготове для sr004") since WAF behavior is not guaranteed stable across sessions/IPs. |

### Not patched (same artifact found, out of scope for the named concern)

`prompts/02_translate/gemma_translate.md` and
`prompts/02_translate/gemma_translation_prompt.md` also start with the same
literal `<<<custom>>>` artifact. Concern (c) in the task brief and spec §0
name `gemma_universal.md` specifically, and it is the only one of the three
actually referenced by a real run manifest
(`data/bouquet/translation/translate-gemma-bouquet/config.json`) — the other
two appear to be superseded/unused variants (translation.yaml's own default
`system_prompt`/`user_prompt` point at `02_draft/system.md` /
`02_draft/user.md`, and no `configs/*.yaml` or `data/*/translation/*/config.json`
in the vendored snapshot references either file). Left untouched to keep the
patch scoped to what the wiki-eval run actually invokes; worth flagging to
Danil as a general prompt-repo hygiene note, not a wiki-eval blocker.

## Verification performed (this session, cloud, no GPU)

- `git apply --check --directory=external/gse-translation <patch>` — **all 5
  pass**, run from this repo's root against the read-only vendored snapshot.
- Combined apply (all 5, in order) into a disposable scratch copy outside
  `external/`: reconstructs a syntactically valid file set
  (`python3.13 -m py_compile` clean on all three touched `.py` files — the repo
  requires Python ≥3.13, which this sandbox's system `python3.13` provides).
- `ruff check --isolated --target-version py313` on the three patched `.py`
  files: 0 new findings. One pre-existing `F401` (`palimpsest.paths.PROMPTS`
  imported but unused) in `scripts/02_translate_json.py` predates these
  patches (present in the unpatched vendored file too) and is left alone —
  out of scope for the named traps, and not introduced by this patch set.
- `--help` smoke test on the patched `02_translate_json.py` via the vendored
  `.venv`'s own `typer`/`click`/`rich`: caught and fixed a real bug during
  authoring — the first draft's `--out-root` help string used
  `<out-root>[/<bucket>]/<run-name>/` literal angle/square brackets, which
  `rich`'s markup renderer (used by Typer for `--help`) tried to parse as
  markup tags and crashed with `MarkupError`. Reworded to avoid `<`/`[`/`]` in
  the help string; re-verified `--help` renders cleanly.
- **Not run:** no actual LLM call, no real translate/refine/score invocation
  (no GPU, no vLLM server, no API key in this session) — that verification is
  sr004's job, covered by the Ф0 probe checklist in the runbook.
