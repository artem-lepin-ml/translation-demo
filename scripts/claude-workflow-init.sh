#!/usr/bin/env bash
#
# claude-workflow-init.sh — transfer the .claude/ workflow architecture into any
# target repo. Manifest-driven (reads .claude/portable-manifest.json), no network,
# pure file ops + python3. A clone of THIS repo installs the workflow into any
# target: `scripts/claude-workflow-init.sh --from . /path/to/target`.
#
# Layers (see the manifest for the authoritative lists):
#   core          copied/updated verbatim on every run (never clobbers user edits)
#   roster        agents; first install, or --update-roster; honours .removed
#   project-local scaffolded once if absent, never overwritten
#
# Flags:
#   --from <src>       source repo (default: the repo containing this script)
#   --dry-run          print the full plan, touch nothing
#   --update-roster    add source agents missing from the target roster
#
# Deletion tracking: a target-side .claude/agents/.removed list (one agent
# basename per line) names agents the target dropped; they are never re-added.
#
set -eu

# ---- resolve script dir / default source -----------------------------------
SCRIPT_PATH=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")
DEFAULT_SRC=$(cd "$SCRIPT_DIR/.." && pwd)

SRC="$DEFAULT_SRC"
DRY=0
UPDATE_ROSTER=0
TARGET=""

usage() {
    sed -n '2,25p' "$SCRIPT_PATH" | sed 's/^#\{0,1\} \{0,1\}//'
    exit "${1:-0}"
}

# ---- arg parse -------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --from) SRC=$2; shift 2 ;;
        --from=*) SRC=${1#--from=}; shift ;;
        --dry-run) DRY=1; shift ;;
        --update-roster) UPDATE_ROSTER=1; shift ;;
        -h|--help) usage 0 ;;
        --) shift; break ;;
        -*) echo "unknown flag: $1" >&2; usage 1 ;;
        *) if [ -z "$TARGET" ]; then TARGET=$1; shift; else echo "unexpected arg: $1" >&2; usage 1; fi ;;
    esac
done
[ $# -gt 0 ] && [ -z "$TARGET" ] && TARGET=$1

if [ -z "$TARGET" ]; then echo "error: target repo path required" >&2; usage 1; fi

SRC=$(cd "$SRC" && pwd)
if [ ! -f "$SRC/.claude/portable-manifest.json" ]; then
    echo "error: no .claude/portable-manifest.json under source: $SRC" >&2
    exit 1
fi
mkdir -p "$TARGET"
TARGET=$(cd "$TARGET" && pwd)

# ---- hand off to python for manifest-driven plan/execute -------------------
python3 - "$SRC" "$TARGET" "$DRY" "$UPDATE_ROSTER" <<'PY'
import datetime, glob, json, os, shutil, subprocess, sys

SRC, TARGET, DRY_S, ROSTER_S = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
DRY = DRY_S == "1"
UPDATE_ROSTER = ROSTER_S == "1"

MANIFEST = json.load(open(os.path.join(SRC, ".claude", "portable-manifest.json")))

installed, scaffolded, collisions, roster_removed_hits = [], [], [], []
noops = 0
settings_changed = False
gitignore_added = []
version_action = "kept"

def spath(rel): return os.path.join(SRC, rel)
def tpath(rel): return os.path.join(TARGET, rel)

def read_bytes(p):
    with open(p, "rb") as f: return f.read()

def identical(a, b):
    try: return read_bytes(a) == read_bytes(b)
    except OSError: return False

def ensure_parent(p):
    d = os.path.dirname(p)
    if d and not os.path.isdir(d) and not DRY:
        os.makedirs(d, exist_ok=True)

def copy_managed(rel, add_missing=True):
    """No-clobber copy. Returns one of: install/noop/collision/absent."""
    global noops
    s, d = spath(rel), tpath(rel)
    if not os.path.exists(s):
        return "absent"                        # optional source (e.g. spec-rubrics.md)
    if os.path.exists(d):
        if identical(s, d):
            noops += 1
            return "noop"
        collisions.append(rel)
        print(f"  ! SKIP  collision (target modified): {rel}")
        return "collision"
    if not add_missing:
        return "absent"
    ensure_parent(d)
    if DRY:
        print(f"  + install  {rel}")
    else:
        shutil.copy2(s, d)
    installed.append(rel)
    return "install"

def walk_rel(rel_dir):
    base = spath(rel_dir)
    if not os.path.isdir(base):
        return
    for root, _dirs, files in os.walk(base):
        for fn in sorted(files):
            abs_f = os.path.join(root, fn)
            yield os.path.relpath(abs_f, SRC)

# ---- 0. state --------------------------------------------------------------
version_rel = MANIFEST["workflow_version_file"]
first_install = not os.path.exists(tpath(version_rel))

def source_sha():
    try:
        return subprocess.check_output(
            ["git", "-C", SRC, "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "sha-unknown"

print(f"claude-workflow-init  [{'DRY-RUN' if DRY else 'INSTALL'}]")
print(f"  source : {SRC}  (sha {source_sha()[:12]})")
print(f"  target : {TARGET}")
print(f"  mode   : {'first-install' if first_install else 'update'}"
      f"{'  +update-roster' if UPDATE_ROSTER else ''}")
print()

# ---- 1. core ---------------------------------------------------------------
print("core (verbatim, no-clobber):")
core = MANIFEST["layers"]["core"]
for rel_dir in core["dirs"]:
    for rel in walk_rel(rel_dir):
        copy_managed(rel, add_missing=True)
for rel in core["files"]:
    copy_managed(rel, add_missing=True)

# ---- 2. roster -------------------------------------------------------------
roster = MANIFEST["layers"]["roster"]
add_roster = first_install or UPDATE_ROSTER
print(f"\nroster (agents) [{'install' if add_roster else 'audit-only'}]:")

removed = set()
rem_file = tpath(roster["removed_list"])
if os.path.exists(rem_file):
    for line in open(rem_file):
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        removed.add(name)
        removed.add(name[:-3] if name.endswith(".md") else name + ".md")

for rel_dir in roster["dirs"]:
    for rel in walk_rel(rel_dir):
        base = os.path.basename(rel)
        if base == os.path.basename(roster["removed_list"]):
            continue
        if base in removed or base[:-3] in removed:
            roster_removed_hits.append(base)
            print(f"  . skip (in .removed): {rel}")
            continue
        copy_managed(rel, add_missing=add_roster)

# ---- 3. project-local (scaffold once, never overwrite) ---------------------
print("\nproject-local (scaffold once, never overwrite):")
for e in MANIFEST["layers"]["project_local"]["entries"]:
    rel, kind = e["path"], e["type"]
    d = tpath(rel)
    if os.path.exists(d):
        print(f"  = keep (present): {rel}")
        continue
    ensure_parent(d)
    if DRY:
        print(f"  + scaffold ({kind}): {rel}")
    else:
        if kind == "empty":
            open(d, "w").close()
        elif kind == "copy":
            shutil.copy2(spath(e["from"]), d)
        elif kind == "stub":
            with open(d, "w") as f: f.write(e["stub"])
        else:
            raise SystemExit(f"unknown project_local type: {kind}")
        print(f"  + scaffold ({kind}): {rel}")
    scaffolded.append(rel)

# ---- 4. settings.json deep-merge -------------------------------------------
def load_json(p):
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return {}

def merge_settings():
    global settings_changed
    sm = MANIFEST["settings_merge"]
    frag_src = load_json(spath(sm["source"]))
    frag = {k: frag_src[k] for k in sm["take_keys"] if k in frag_src}
    tp = tpath(sm["target"])
    tgt = load_json(tp)
    before = json.dumps(tgt, indent=2, ensure_ascii=False, sort_keys=False)

    if "permissions" in frag:
        tperm = tgt.get("permissions", {})
        for key in ("allow", "deny", "ask"):
            merged = list(tperm.get(key, []))
            for item in frag["permissions"].get(key, []):
                if item not in merged:
                    merged.append(item)
            if merged:
                tperm[key] = merged
        tgt["permissions"] = tperm

    if "hooks" in frag:
        thooks = tgt.get("hooks", {})
        for event, groups in frag["hooks"].items():
            existing = list(thooks.get(event, []))
            seen = set()
            for g in existing:
                m = g.get("matcher", None)
                for h in g.get("hooks", []):
                    seen.add((m, h.get("command")))
            for g in groups:
                m = g.get("matcher", None)
                for h in g.get("hooks", []):
                    k = (m, h.get("command"))
                    if k in seen:
                        continue
                    seen.add(k)
                    ng = {}
                    if "matcher" in g:
                        ng["matcher"] = g["matcher"]
                    ng["hooks"] = [h]
                    existing.append(ng)
            thooks[event] = existing
        tgt["hooks"] = thooks

    after = json.dumps(tgt, indent=2, ensure_ascii=False, sort_keys=False)
    if after == before and os.path.exists(tp):
        return
    settings_changed = True
    if DRY:
        print(f"\nsettings.json: would deep-merge hooks+permissions into {sm['target']}")
    else:
        ensure_parent(tp)
        with open(tp, "w") as f: f.write(after + "\n")
        print(f"\nsettings.json: deep-merged hooks+permissions -> {sm['target']}")

merge_settings()

# ---- 5. .gitignore entries -------------------------------------------------
def ensure_gitignore():
    lines = MANIFEST["gitignore"]
    header = "# --- claude-workflow (managed) ---"
    p = tpath(".gitignore")
    current = open(p).read() if os.path.exists(p) else ""
    present = set(l.rstrip("\n") for l in current.splitlines())
    to_add = [l for l in lines if l not in present]
    if not to_add:
        return
    block = ""
    if current and not current.endswith("\n"):
        block += "\n"
    if header not in present:
        block += header + "\n"
    block += "\n".join(to_add) + "\n"
    gitignore_added.extend(to_add)
    if DRY:
        print(f".gitignore: would append {len(to_add)} entr(y/ies)")
    else:
        with open(p, "a") as f: f.write(block)
        print(f".gitignore: appended {len(to_add)} entr(y/ies)")

ensure_gitignore()

# ---- 6. WORKFLOW_VERSION ---------------------------------------------------
def write_version():
    global version_action
    p = tpath(version_rel)
    sha = source_sha()
    if os.path.exists(p):
        cur_sha = None
        for line in open(p):
            if line.startswith("source_sha="):
                cur_sha = line.split("=", 1)[1].strip()
        if cur_sha == sha:
            return                              # unchanged -> keep (idempotent)
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = (f"source_sha={sha}\n"
               f"source_date={date}\n"
               f"manifest_version={MANIFEST.get('manifest_version')}\n"
               f"installer=claude-workflow-init.sh\n")
    version_action = "written"
    if DRY:
        print(f"WORKFLOW_VERSION: would write (sha {sha[:12]})")
    else:
        ensure_parent(p)
        with open(p, "w") as f: f.write(content)
        print(f"WORKFLOW_VERSION: wrote {version_rel} (sha {sha[:12]})")

write_version()

# ---- 7. summary ------------------------------------------------------------
print("\n" + "-" * 60)
print("summary:")
print(f"  installed (core/roster) : {len(installed)}")
print(f"  scaffolded (project)    : {len(scaffolded)}")
print(f"  unchanged (no-op)       : {noops}")
print(f"  collisions (skipped)    : {len(collisions)}")
for c in collisions:
    print(f"      - {c}")
if roster_removed_hits:
    print(f"  roster .removed honored : {len(roster_removed_hits)} -> {', '.join(sorted(set(roster_removed_hits)))}")
print(f"  settings.json           : {'changed' if settings_changed else 'unchanged'}")
print(f"  .gitignore added        : {len(gitignore_added)}")
print(f"  WORKFLOW_VERSION        : {version_action}")

# ---- 8. static self-check (spec acceptance subset) -------------------------
if DRY:
    print("\n(dry-run: self-check skipped)")
    sys.exit(0)

def check_no_superpowers_refs():
    bad = []
    for root, _dirs, files in os.walk(tpath(".claude")):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(root, fn)
            try:
                for i, line in enumerate(open(fp, encoding="utf-8", errors="ignore"), 1):
                    if "superpowers:" in line:
                        composite = f"{fp}:{i}:{line}"
                        if "VENDORED" not in composite:
                            bad.append(f"{os.path.relpath(fp, TARGET)}:{i}")
            except OSError:
                pass
    return bad

def check_agents():
    agents = glob.glob(tpath(".claude/agents/*.md"))
    count_ok = len(agents) <= 25
    vendored_ok = True
    for a in agents:
        txt = open(a, encoding="utf-8", errors="ignore").read()
        if "vendored from" in txt and "source:" not in txt:
            vendored_ok = False
    return len(agents), count_ok and vendored_ok

bad_refs = check_no_superpowers_refs()
n_agents, agents_ok = check_agents()

results = [
    ("T-P0.1  docs/reports exists",
     os.path.isdir(tpath("docs/reports"))),
    ("T-P0.2  superpowers/brainstorming/SKILL.md exists",
     os.path.isfile(tpath(".claude/skills/superpowers/brainstorming/SKILL.md"))),
    ("T-P0.3  no bare 'superpowers:' refs in .claude/*.md",
     len(bad_refs) == 0),
    (f"T-P2    agents<=25 ({n_agents}) & vendored carry source:",
     agents_ok),
]

print("\nself-check (static acceptance subset):")
all_pass = True
for name, ok in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    all_pass = all_pass and ok
if bad_refs:
    for r in bad_refs:
        print(f"        offending ref: {r}")

print("\nRESULT:", "ALL PASS" if all_pass else "FAILURES PRESENT")
sys.exit(0 if all_pass else 1)
PY
