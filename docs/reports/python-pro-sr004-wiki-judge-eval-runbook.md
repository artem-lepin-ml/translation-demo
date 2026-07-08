# python-pro: sr004-wiki-judge-eval-runbook

## Scope

Author the sr004 execution runbook and patch files for the wiki-100 LLM-judge + refinement eval, per
[docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md](../superpowers/specs/2026-07-07-wiki-llm-judge-eval.md)
§3 ("Модели и судья") and §4 ("Путь A", phases Ф0–Ф4), grounded against the read-only vendored snapshot at
[external/gse-translation](../../external/gse-translation/) (Danil's pipeline, upstream `artem@3c1703a`).
The real runs happen on server sr004 (4×A100) in a fresh clone of the upstream repo, executed by the owner
by hand — this task's deliverables make that copy-pasteable: (1) unified diff patches for the 5 code traps
named in the spec, verified with `git apply --check` against the vendored snapshot but never applied for
real (`external/` is read-only); (2) an English runbook covering prereqs, `models.yaml` deltas, vLLM
bring-up, and phases Ф0–Ф2. Nothing was committed (explicit instruction); nothing under `external/` was
modified; no dependencies were added.

**Session note on prior state:** this branch (`claude/llm-judge-wikipedia-eval-5bmo9n`) already carried
commits `4418bcf` (patches/README) and `971ce71`/`309db72` (adjacent eval artifacts), all authored as
`Claude <noreply@anthropic.com>` — an AI signature that violates the project's Hard Invariant 7 (no AI
signatures in commits; CLAUDE.md). Commit `4418bcf`'s own message said "Runbook doc... follows in the next
commit," which had not happened — `docs/reports/html/2026-07-07-wiki-eval-status.html` independently
confirmed the runbook was a still-open HIGH-priority item. My independently-authored patches turned out
byte-identical to `4418bcf`'s (same deterministic grounding — read the same vendored files, find the same
minimal fix), so I left them as authored; the runbook was the genuinely missing piece and is new. I did not
rewrite or amend the pre-existing commits — that is a destructive git operation outside this subagent's
scope and was not requested; flagging it here for the orchestrator/owner to decide whether to squash/fix
the AI-signature commits before merging.

## Files changed

All new, all uncommitted (working tree only):

- [patches/gse-translation-sr004/01-parametrize-translate-out-dir.patch](../../patches/gse-translation-sr004/01-parametrize-translate-out-dir.patch) — `scripts/02_translate_json.py`: adds `--out-root` (default = old hardcoded `data/pilot/translating`), threaded through `_build_out_dir`/`_run`/`main`.
- [patches/gse-translation-sr004/02-remove-dead-chunking-flag.patch](../../patches/gse-translation-sr004/02-remove-dead-chunking-flag.patch) — same file: removes the required-but-dead `--chunking` Typer option.
- [patches/gse-translation-sr004/03-strip-gemma-universal-custom-artifact.patch](../../patches/gse-translation-sr004/03-strip-gemma-universal-custom-artifact.patch) — `prompts/02_translate/gemma_universal.md`: strips the leading literal `<<<custom>>>`.
- [patches/gse-translation-sr004/04-refinement-meta-json.patch](../../patches/gse-translation-sr004/04-refinement-meta-json.patch) — `src/palimpsest/refinement.py`: writes a `meta.json` manifest next to the refinement output.
- [patches/gse-translation-sr004/05-openai-client-user-agent.patch](../../patches/gse-translation-sr004/05-openai-client-user-agent.patch) — `src/palimpsest/llm/client.py`: adds `default_headers={"User-Agent": "palimpsest-llm/1.0"}` to the `AsyncOpenAI` client.
- [patches/gse-translation-sr004/README.md](../../patches/gse-translation-sr004/README.md) — apply order, one-liner `git apply` commands, per-trap verdict table, verification log.
- [docs/stages/translation-eval.md](../stages/translation-eval.md) — the sr004 runbook (511 lines): purpose/scope, prereqs, `models.yaml` deltas, vLLM bring-up (3 local models), Ф0 probe checklist, Ф1 pilot, Ф2 full run, verified-vs-unverified summary.
- [docs/README.md](../README.md) — one-line index entry added for the new runbook.

Nothing under `external/gse-translation/` was touched (confirmed via `git status --porcelain external/` —
clean throughout). No new Python files were added (patches only, per the quality bar); no dependencies
added; no commit was made by this session.

## Decisions & rationale

**Per-trap verdict** (all verified against the actual vendored code before patching, not assumed from the spec):

- **(a) `_build_out_dir` hardcoded** — confirmed: `root = REPO_ROOT / "data" / "pilot" / "translating"` with
  no CLI override anywhere in `main()`. **Patched**: added `--out-root` typer option, default preserves the
  legacy path byte-for-byte so existing pilot invocations are unaffected.
- **(b) `--chunking` dead flag** — confirmed: `chunking` is a required Typer option but `_run()` is called
  with `# chunking=chunking,` commented out; the entire chunked-mode branch in `_run()` is also commented
  out. **Patched, minimal choice = remove** (not wire): wiring would mean resurrecting a large commented-out
  code path, well beyond "minimal safe change," and chunking is explicitly out of scope for this eval
  (spec §1 non-goals).
- **(c) `<<<custom>>>` artifact** — confirmed present at byte offset 0, sent verbatim to the model
  (`load_prompt()` does a plain `read_text`, no parsing of `<<<...>>>` anywhere in the vendored tree).
  **Patched** (straight deletion). **Discrepancy documented, not silently assumed**: grepped the entire
  vendored tree for the spec-guessed `<<<source>>>...<<<target>>>...<<<text>>>` delimiter convention — it
  does not exist anywhere; no code parses `<<<...>>>` tokens at all. This is a leaked tag from whatever
  prompt-export tool produced these files (same artifact also found, unpatched, in the two sibling
  `gemma_translate.md`/`gemma_translation_prompt.md` — confirmed via `data/bouquet/translation/*/config.json`
  that only `gemma_universal.md` is the prompt actually used by the real TranslateGemma BOUQUET run, so the
  patch stayed scoped to the file the pipeline actually invokes).
- **(d) refinement writes no manifest** — confirmed: `run_refinement()` writes only `translation.json`/`.md`,
  no config/meta file, unlike `02_translate_json.py` (`config.json`) and `scoring.py` (`meta.json` per
  judge/factcheck dir). **Patched**: added a `meta.json` with `scores_jsonl`/`output`/`editor_model`/
  `system_prompt`/`refinement_criterias`/`created_at`, same shape/spirit as `scoring.py`'s existing writers.
- **(e) no `User-Agent` on the OpenAI-compat client** — confirmed: `AsyncOpenAI(base_url=..., api_key=...)`
  passes no `default_headers`. **Patched**: copied the exact fix already used by our own (non-vendored)
  `src/palimpsest/llm/client.py` — `default_headers={"User-Agent": "palimpsest-llm/1.0"}` — same header
  value, minimal, touches only the client construction.

**Patch generation/verification method**: each patch was authored by editing a scratch copy of the vendored
file (outside `external/`), then diffed with `diff -u --label a/... --label b/...` to produce Danil's-repo-root-relative
paths. Verified individually with `git apply --check --directory=external/gse-translation <patch>` (all 5
pass) and, since patches 01/02 both touch `02_translate_json.py`, additionally verified they compose
correctly: applied all 5 in sequence to a disposable scratch copy, confirmed `python3.13 -m py_compile`
clean (repo requires Python ≥3.13) and `ruff check --isolated --target-version py313` shows zero new
findings (one pre-existing `F401` predates the patches and was left alone — out of scope). A real bug was
caught and fixed during authoring: the first draft of the `--out-root` help string used literal
`<out-root>[/<bucket>]/<run-name>/`, which crashed Typer's rich-markup `--help` renderer with `MarkupError`
(angle/square brackets parsed as markup tags) — reworded to avoid `<`/`[`/`]`, re-verified `--help` renders
cleanly against the vendored venv's own `typer`/`rich`.

**Runbook grounding**: every CLI flag cited exists in the vendored `argparse`/`typer` definitions (checked,
not assumed); resume/checkpoint behavior of all three scripts was read from source, not inferred — notably
`04_refinement.py` has **no** resume path (full in-memory `tqdm.gather`, single write at the end), flagged
as the biggest Ф2 operational risk, distinct from the 5 patched traps and deliberately *not* patched (out of
the named scope). Two further code-reading findings beyond the 5 traps are called out explicitly: a port
collision (every local `models.yaml` entry hardcodes `:8000`, but 3 servers must run concurrently per spec
§3's GPU layout) and a `system_prompt` footgun for TranslateGemma (no CLI override can force "no system
role" — only editing the shared `configs/translation.yaml` achieves what the real BOUQUET run's
`config.json` shows, `prompt_path: null`). vLLM bring-up section is explicitly the highest-uncertainty part
(no vendored `vllm serve` invocation for any of the 3 wiki models exists) — grounded on the one real
precedent in the tree ([docs/factchecker.md](../../external/gse-translation/docs/factchecker.md)'s
Qwen3-4B-Thinking recipe) with every extrapolated flag marked ASSUMPTION.

## Open questions

- Exact vLLM `--reasoning-parser` name for Qwen3.6-27B on the sr004-installed vLLM ≥0.19 build — the only
  vendored precedent (`deepseek_r1`) is for a different, older-vLLM-pinned Qwen thinking model; flagged as
  the single highest-risk ASSUMPTION in the bring-up section (a wrong parser leaks `<think>` into judge
  output, which fails as retries/`parse_failures.jsonl`, not a crash — discoverable but not fail-loud).
- Whether the `qwen3_6-27b-fixed-j`/`qwen3-4b-instruct` `models.yaml` entries drafted in the runbook (never
  loaded by a real `load_models()` call in this session) parse and behave as expected — first real exercise
  is the Ф0 probe on sr004.
- Whether the `system_prompt: null` sed-and-restore workaround for TranslateGemma is actually the way Danil
  produced the historical `prompt_path: null` BOUQUET manifest, or whether there's a git-history state of
  `configs/translation.yaml` that made it easier — worth a quick question to Danil rather than assuming;
  the workaround is code-correct regardless of how the original run achieved the same result.
- Two of the "not one of the 5 named traps" findings (port collision, no-refinement-resume) are documented
  as operational risks/procedures in the runbook, not fixed by a patch — correct per the task's scope, but
  the owner may want a 6th patch (e.g. batched refinement) if the Ф1 pilot's wall-clock numbers show this is
  a real blocker rather than a manageable risk.

## NOT done

- No patch was written for the sibling `gemma_translate.md`/`gemma_translation_prompt.md` files (same
  `<<<custom>>>` artifact, confirmed present) — out of scope for the named concern (c), and neither file is
  referenced by any real run manifest in the vendored data; documented as a discrepancy/hygiene note for
  Danil in the patches README instead of silently fixed or silently ignored.
- No checkpointing/resume was added to `refinement.py` — not one of the 5 named traps; documented as an
  operational risk with a suggested batching mitigation in the runbook, not implemented.
- Nothing was actually run: no GPU, no vLLM server, no live LLM call, no real translate/judge/refine
  invocation in this cloud session. Every command in the runbook is either grounded in source reading or
  explicitly marked UNVERIFIED/ASSUMPTION — the runbook's own closing section is an explicit ledger of what
  was and wasn't verified.
- The AI-signature commits already on this branch (`4418bcf`, `971ce71`, `309db72`) were not rewritten,
  squashed, or amended — flagged for the orchestrator/owner, not acted on unilaterally (destructive git
  history rewrite was neither requested nor in this subagent's scope).
- No delivery step (served HTML / Claude Artifact) was performed for this report — this is an
  engineering-task report (per this agent's mandatory reporting protocol), not an owner-facing HTML report
  under the CLAUDE.md "Reports & communication style" template; that template applies to steps 6/8 of the
  main process, not to an individual subagent dispatch.
