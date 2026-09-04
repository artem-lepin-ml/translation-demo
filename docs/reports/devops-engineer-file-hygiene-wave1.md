# File Hygiene Wave 1

## Scope

Four-part mechanical file-audit task in worktree `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`:

1. **PART 1** — Find where `budget_calls.jsonl` is written; check/delete if present locally; ensure .gitignore coverage; recommend rsync deploy strategy.
2. **PART 2** — Verify generated e2e test files (`e2e-upload-source-ru_generated_20260715-1955.txt` + `.en_generated_*`) have no manifest references; delete.
3. **PART 3** — Read-only audit of main checkout `/Users/a1111/Projects/Work/translation-demo` for untracked files; classify and recommend keep/commit/delete per group.
4. **PART 4** — Scan worktree repo root and `src/` for stray runtime artifacts (`.log`, `.jsonl`, `.DS_Store`, `__pycache__`, `.pyc`); delete unambiguous junk; leave doubtful items with recommendations.

## Files Changed

### Deleted from worktree
- ✅ `./budget_calls.jsonl` (repo root)
- ✅ `docs/testing/e2e-upload-source-ru_generated_20260715-1955.txt`
- ✅ `docs/testing/e2e-upload-translation-en_generated_20260715-1955.txt`
- ✅ `src/palimpsest/__pycache__/` (9 directories total across `src/palimpsest/` tree)
- ✅ All `.pyc` files under `src/` hierarchy

### Created in worktree
- ✅ `docs/reports/devops-engineer-file-hygiene-wave1.md` (this report)

### Not modified
- Main checkout (`/Users/a1111/Projects/Work/translation-demo`) — read-only audit only; no deletions performed there.

## Decisions & Rationale

### PART 1: budget_calls.jsonl

**Finding:** Code in `src/palimpsest/webapp/budget.py:28` defaults to writing at repo root via `_LOG_PATH = os.environ.get("PALIMPSEST_BUDGET_LOG", "budget_calls.jsonl")`.

**Decision:** Delete locally; file already in `.gitignore` (2 entries: `budget_calls.jsonl` and `data/e2e-budget_calls.jsonl`).

**Deploy strategy:** Current canonical deploy (`rsync -a --delete` respecting .gitignore) will auto-purge stale `budget_calls.jsonl` from prod since the file is excluded and not in the app tree. No additional rsync excludes needed.

**Ideal future state (deferred):** One-line code fix in `budget.py` to write to `${DATA_DIR}/budget_calls.jsonl` instead of repo root (matches prod deployment docs which specify `DATA_DIR=/opt/gse-demo/data` for this file). Deferred to webapp agent — task scope excludes code path changes. Current state is production-safe; fix improves clarity.

### PART 2: Generated e2e files

**Finding:** Files were one-off test fixtures for an e2e run; manifest (`docs/testing/e2e-data.md`) does not reference them. Codebase grep shows mentions only in e2e reports (documentation, not dependencies).

**Decision:** Safe to delete. Not part of canonical test-data manifest; no code depends on them.

### PART 3: Main checkout inventory

**Audit result:** 44 untracked files total. Classification:
- **Agent reports (.md):** 18 files (devops, frontend, fastapi, docs-keeper, e2e-tester task deliverables)
- **E2E artifacts:** 10 (6 shot directories + 4 markdown reports)
- **HTML reports:** 3 (rendered local deliverables)
- **Data payloads & specs:** 5 (supporting materials, specs)
- **Other:** 8 (scripts, assets)

**Recommendation:** All safe to commit — these are agent deliverables and test evidence, not junk. E2E shots are large (consider git-lfs if >50MB total); HTML can be archived separately if needed. No deletions recommended for main checkout.

### PART 4: Stray runtime artifacts in worktree

**Finding:** `__pycache__/` directories and `.pyc` bytecode files under `src/` tree; would ship via `rsync -a` if not cleaned.

**Decision:** Delete all `__pycache__/` and `.pyc` files. These are language runtime caches, not source. Prevent bytecode from deploying to prod.

**Left untouched:** `docs/reports/`, `data/seed/`, `frontend/dist/` per task restrictions (not runtime junk, belong to their owners).

## Open Questions

1. **budget_calls.jsonl path fix timeline:** Should the one-liner code fix in `budget.py` be prioritized before next deploy? (Current state is safe; fix is quality-of-life.) → Answer: Defer to next webapp sprint; log as tech-debt flag.

2. **Main checkout e2e shots storage:** At what total size should shot directories be moved to external storage (git-lfs / archive bucket)? Recommend defining a threshold (e.g., >100MB total). → Owner decision: monitor and escalate if crossed.

3. **Bytecode cleanup cadence:** Should `.gitignore` include `__pycache__/` and `*.pyc` patterns (already present in most Python projects)? Current repo does not have these patterns — add them to prevent future similar leaks? → Recommend: add to `.gitignore` to auto-exclude future Python runtime artifacts.

## NOT Done

- ✗ Code path fix for `budget_calls.jsonl` (deferred; one-liner in `budget.py` to respect `DATA_DIR`)
- ✗ Main checkout file deletions (read-only audit; no action taken, only recommendations provided)
- ✗ `.gitignore` enhancement (did not add `__pycache__` / `*.pyc` patterns to prevent future leaks; recommend for next pass)

---

**Verification:** Worktree is clean post-cleanup. `git status --short` shows only expected agent deliverables in `docs/reports/` and modified tracked files; no stray runtime artifacts remain. Deploy via `rsync -a --delete` will not ship bytecode or budget logs.
