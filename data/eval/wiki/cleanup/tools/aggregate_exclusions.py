#!/usr/bin/env python3
# Provenance: written 2026-07-10 to close out the 10-wave gold-cleanup campaign.
# What it does: aggregates all wave removal flags + both override files into ONE
# DRAFT anchor-exclusions file, reconciled against the CURRENT gt.jsonl by tuple
# identity (never by index -- commit 4c77b7c re-derived gt.jsonl after an IPA
# parser fix and shifted tuple indices in 4 articles).
#
# Updated 2026-07-10 (same day, later): the owner-approved 5-article corpus swap
# (see REPLACEMENTS_PATH) re-sorts gt.jsonl alphabetically, which moves 74/100
# article positions -- not just the 5 replaced ones. Reconciliation against
# "current gt.jsonl" was therefore switched from positional (current_records[i-1])
# to title-keyed (current_by_title[titles[i-1]]); the 5 replaced articles'
# flags are exempt (their title no longer exists in current gt.jsonl at all) and
# go to the new ``moot_article_replaced`` bucket instead.
#
# Updated 2026-07-10 (same day, later still): merged in the independent
# anchor-relevance audit of the 5 replacement articles themselves
# (removals-replacements/R01-R05.json + manifest_replacements.json +
# overrides_replacements.json). These titles are NEW in gt.jsonl -- there is no
# prefix-gold indirection for them, so ``n`` indexes CURRENT gt_tuples directly.
# Merged in as provenance="replacement-audit" (or "replacement-audit-override"
# for orchestrator restores), article_no "R01".."R05".
#
# Updated 2026-07-10 (same day, later still): the owner APPROVED the 750-entry
# exclusion list. Output renamed from anchor_exclusions_draft.json to
# anchor_exclusions.json (git mv) and the ``note`` field switched from
# DRAFT/pending-approval wording to an APPROVED note -- this script is the
# note's single source of truth, so a rerun (e.g. after a future gt.jsonl
# change) regenerates the same approved wording, not a reverted draft one.
"""Aggregate the wave1-10 LLM gold-cleanup flags into the approved anchor
exclusions file.

Every removal file (`removals-wave*/NNN.json`) and both override files
(`overrides_wave1.json`, `overrides_wave2.json`) number their anchors against
the PRE-parser-fix gt.jsonl (``n = tuple_index + 1`` in that version). This
script resolves each ``n`` to a stable identity --
``(token_index, anchor_text, qid, span_len)`` -- in the pre-fix gold, then
reconciles that identity against the CURRENT gt.jsonl, keyed by the article's
TITLE (never by list position -- gt.jsonl is kept sorted by title, so any
title-set change reorders most of the file; position is not a stable article
identifier). An identity still present there becomes a "live" exclusion; an
identity that vanished for a still-present article (only possible in the 4
articles the IPA fix touched) is reported separately as
``dropped_by_parser_fix``; an identity whose whole article was replaced by the
2026-07-10 manual corpus swap (REPLACED_ARTICLES) is reported separately as
``moot_article_replaced`` -- none of these require action.

gt.jsonl itself is never read for writing -- this script only ever WRITES
``data/eval/wiki/anchor_exclusions.json``. The owner approved this exclusion
list 2026-07-10; exclusions are applied at scoring time only, gt.jsonl stays
raw.

Hard-error conditions (the script refuses to guess):
  * a removal/override ``n`` outside the pre-fix article's tuple range
  * a removal file entry in ``remove`` with no matching ``reasons`` key
  * an override ``anchor`` field that does not match the resolved anchor_text
  * an override ``restore``/``add_removals`` referencing an (article, n) pair
    that is not (respectively: is already) in the base flagged set
  * a flagged identity missing from current gt.jsonl in an article OTHER than
    the 4 known IPA-fix articles (017, 051, 057, 081) or REPLACED_ARTICLES
  * article 081's known-live survivors (n=1, 68, 77) failing to land as live
  * REPLACED_ARTICLES disagreeing with REPLACEMENTS_PATH about which manifest
    titles were replaced, in either direction
  * manifest_replacements.json's titles disagreeing with REPLACEMENTS_PATH's
    replacement_title set, in either direction
  * a removals-replacements/R0N.json ``n`` outside the current article's tuple
    range, or a ``remove`` entry with no matching ``reasons`` key
  * a manifest_replacements.json ``n_anchors`` not matching len(gt_tuples) of
    the same title in current gt.jsonl
  * an overrides_replacements.json ``restore``/``add_removals`` ``anchor``
    field that does not match the resolved anchor_text, or that references an
    (article, n) pair that is not (respectively: is already) flagged
  * a replacement-audit flag whose identity collides with an existing
    (wave-based) exclusion

Run:
  cd /home/user/translation-demo && PYTHONPATH=src python3 \\
      data/eval/wiki/cleanup/tools/aggregate_exclusions.py --prefix-gold <path>

``--prefix-gold`` is gt.jsonl as of 4c77b7c~1, e.g.:
  git show 4c77b7c~1:data/eval/wiki/gt.jsonl > /tmp/.../gt_prefix.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path("/home/user/translation-demo")
CLEANUP_DIR = ROOT / "data/eval/wiki/cleanup"
GT_PATH = ROOT / "data/eval/wiki/gt.jsonl"
MANIFEST_PATH = CLEANUP_DIR / "manifest.json"
OVERRIDES_WAVE1_PATH = CLEANUP_DIR / "overrides_wave1.json"
OVERRIDES_WAVE2_PATH = CLEANUP_DIR / "overrides_wave2.json"
REPLACEMENTS_PATH = CLEANUP_DIR / "replacements_2026-07-10.json"
REMOVALS_REPLACEMENTS_DIR = CLEANUP_DIR / "removals-replacements"
MANIFEST_REPLACEMENTS_PATH = REMOVALS_REPLACEMENTS_DIR / "manifest_replacements.json"
OVERRIDES_REPLACEMENTS_PATH = CLEANUP_DIR / "overrides_replacements.json"
OUT_PATH = ROOT / "data/eval/wiki/anchor_exclusions.json"

# manifest order == article numbering 001..100; entry i (1-based) -> file NNN.json
WAVE_DIRS: list[tuple[str, range]] = [
    ("removals-wave1", range(1, 11)),
    ("removals-wave2-4", range(11, 41)),
    ("removals-wave5-7", range(41, 71)),
    ("removals-wave8-10", range(71, 101)),
]

# The IPA parser fix (4c77b7c) dropped 56 single-char tuples from exactly these
# 4 articles (79->27, 198->196, 500->499, 38->37) -- a "dropped" identity
# anywhere else is a data-integrity bug, not an expected outcome.
PARSER_FIX_ARTICLES = {"017", "051", "057", "081"}
PARSER_FIX_COMMIT = "4c77b7c"

# The owner-approved 2026-07-10 manual corpus swap (see REPLACEMENTS_PATH)
# replaced these 5 manifest articles' titles wholesale (not just individual
# anchors) -- their flags can never resolve as live/dropped against current
# gt.jsonl because the article itself is gone; cross-validated against
# REPLACEMENTS_PATH at runtime (see main()).
REPLACED_ARTICLES = {"023", "041", "042", "076", "100"}
REPLACEMENT_NOTE = "article replaced 2026-07-10, exclusion moot"

Identity = tuple[int, str, str, int]

# ── Cross-wave consistency rules (task step 6), hardcoded per the spec ──────
CROSS_WAVE_RULES: list[dict[str, Any]] = [
    {
        "article": "004",
        # matches any inflection of the two-word phrase "исторический источник"
        # (историческим источником, историческому источнику, ...)
        "pattern": re.compile(r"^истор\w*\s+источник\w*$", re.IGNORECASE),
        "reason": "cross-wave: align with 030 (generic historiographic phrase)",
    },
    {
        "article": "094",
        # the sole remaining un-flagged "пиньинь" transliteration-tag anchor in
        # the whole corpus (all its siblings were caught by wave/override
        # flags); added per orchestrator context review of the sweep candidate.
        "pattern": re.compile(r"^пиньинь$"),
        "reason": (
            "transliteration template tag (orchestrator context review of "
            "sweep candidate; aligns with the 006 пиньинь ruling)"
        ),
    },
]
PINYIN_ANCHOR_TEXT = "пиньинь"
PINYIN_SWEEP_RULE = "piniyin-tag-vs-standalone (needs context review)"

# ── Regex sweep (task step 7), simple + documented, KEEP-bias downstream ────
SWEEP_REGEXES: list[tuple[str, re.Pattern[str]]] = [
    ("bare-number", re.compile(r"^\d{1,4}$")),  # e.g. "374"
    # optional year markers; bare-number is checked first above so a plain
    # digit string never double-counts here
    ("year", re.compile(r"^\d{1,4}( (год[ау]?|гг\.?))?( ?(до )?н\. ?э\.)?$")),  # e.g. "395 года", "606 году н. э."
    ("catalog-code", re.compile(r"^[A-ZА-Я]{1,4}[- ]?\d+[A-Za-zА-Яа-я]*$")),  # e.g. "KV35", "TT320"
    ("scripture-abbrev", re.compile(r"^\d?\s?[А-Я][а-я]{1,4}\.\s?\d+([:.,]\d+([-–]\d+)?)?$")),  # e.g. "Быт. 10:6", "3Цар. 16:31"
]

OPEN_QUESTIONS_EXTRA: list[dict[str, str]] = [
    {
        "question": (
            "modern political institutions kept with KEEP-bias in 072 (Согдиана) / "
            "073 (Сокровища Сеусо) — e.g. anchors referencing Орбан / ЕС / Soviet-era "
            "oblasts if present; owner to rule"
        )
    },
    {
        "question": (
            "089 «золото» removed as generic material while электрум/лазурит kept as "
            "specialized — confirm the generic-vs-specialized material line"
        )
    },
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def art3(i: int) -> str:
    return f"{i:03d}"


def git_rev(path: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", str(path)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    rev = result.stdout.strip()
    if not rev:
        raise SystemExit(f"HARD ERROR: `git log` returned no revision for {path}")
    return rev


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix-gold", required=True, type=Path,
        help="gt.jsonl as of 4c77b7c~1 (pre IPA-parser-fix numbering)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["articles"]
    prefix_records = load_jsonl(args.prefix_gold)
    current_records = load_jsonl(GT_PATH)
    overrides_wave1 = json.loads(OVERRIDES_WAVE1_PATH.read_text(encoding="utf-8"))
    overrides_wave2 = json.loads(OVERRIDES_WAVE2_PATH.read_text(encoding="utf-8"))
    replacements = json.loads(REPLACEMENTS_PATH.read_text(encoding="utf-8"))
    manifest_replacements = json.loads(MANIFEST_REPLACEMENTS_PATH.read_text(encoding="utf-8"))["articles"]
    overrides_replacements = json.loads(OVERRIDES_REPLACEMENTS_PATH.read_text(encoding="utf-8"))

    if not (len(manifest) == len(prefix_records) == len(current_records) == 100):
        raise SystemExit(
            f"HARD ERROR: expected 100 articles everywhere, got "
            f"manifest={len(manifest)} prefix={len(prefix_records)} current={len(current_records)}"
        )

    # cross-validate the hardcoded REPLACED_ARTICLES against the durable
    # replacements record, in both directions
    replaced_flagged_titles = {r["flagged_title"] for r in replacements}
    new_title_by_old_title = {r["flagged_title"]: r["replacement_title"] for r in replacements}
    if len(replaced_flagged_titles) != len(REPLACED_ARTICLES):
        raise SystemExit(
            f"HARD ERROR: REPLACED_ARTICLES has {len(REPLACED_ARTICLES)} entries but "
            f"{REPLACEMENTS_PATH.name} lists {len(replaced_flagged_titles)} flagged titles"
        )

    # cross-validate manifest_replacements.json's titles against REPLACEMENTS_PATH's
    # replacement_title set, in both directions
    replacement_new_titles = {r["replacement_title"] for r in replacements}
    manifest_replacement_titles = {e["title"] for e in manifest_replacements}
    if manifest_replacement_titles != replacement_new_titles:
        raise SystemExit(
            f"HARD ERROR: {MANIFEST_REPLACEMENTS_PATH.name} titles disagree with "
            f"{REPLACEMENTS_PATH.name} replacement_title set: "
            f"{manifest_replacement_titles} vs {replacement_new_titles}"
        )

    # current gt.jsonl is kept sorted by title, not by manifest position -- any
    # title-set change (like the 2026-07-10 swap) reorders most of the file, so
    # reconciliation below is keyed by TITLE, never by list index
    current_by_title: dict[str, dict[str, Any]] = {rec["title"]: rec for rec in current_records}
    if len(current_by_title) != 100:
        raise SystemExit("HARD ERROR: duplicate titles in current gt.jsonl")

    # ── sanity gate: manifest n_anchors must equal len(pre-fix gt_tuples), in order;
    # current-gold presence is checked by TITLE and must agree with REPLACED_ARTICLES ──
    for i, entry in enumerate(manifest, start=1):
        pre = prefix_records[i - 1]
        art = art3(i)
        if pre["title"] != entry["title"]:
            raise SystemExit(
                f"HARD ERROR: article {art} title mismatch: "
                f"manifest={entry['title']!r} prefix-gold={pre['title']!r}"
            )
        if len(pre["gt_tuples"]) != entry["n_anchors"]:
            raise SystemExit(
                f"HARD ERROR: article {art} ({entry['title']}) anchor-count mismatch: "
                f"manifest n_anchors={entry['n_anchors']} pre-fix gt_tuples={len(pre['gt_tuples'])}"
            )
        is_replaced = art in REPLACED_ARTICLES
        if is_replaced != (entry["title"] in replaced_flagged_titles):
            raise SystemExit(
                f"HARD ERROR: article {art} ({entry['title']!r}) REPLACED_ARTICLES "
                f"membership ({is_replaced}) disagrees with {REPLACEMENTS_PATH.name} "
                f"({entry['title'] in replaced_flagged_titles})"
            )
        if is_replaced:
            if entry["title"] in current_by_title:
                raise SystemExit(
                    f"HARD ERROR: article {art} ({entry['title']!r}) is in REPLACED_ARTICLES "
                    f"but its title is still present in current gt.jsonl"
                )
        else:
            if entry["title"] not in current_by_title:
                raise SystemExit(
                    f"HARD ERROR: article {art} ({entry['title']!r}) title missing from "
                    f"current gt.jsonl and it is not in REPLACED_ARTICLES"
                )

    titles = [e["title"] for e in manifest]
    prefix_tuples: list[list[list[Any]]] = [rec["gt_tuples"] for rec in prefix_records]

    def current_tuples_for(i: int) -> list[list[Any]] | None:
        """gt_tuples for manifest article i in the CURRENT gold, keyed by title;
        None if that article's title was replaced (see REPLACED_ARTICLES)."""
        rec = current_by_title.get(titles[i - 1])
        return rec["gt_tuples"] if rec is not None else None

    def article_qid_for(i: int) -> str:
        """qid to report for manifest article i: the CURRENT qid if the article
        is still live, else its own PRE-fix qid (the article is gone; report
        its original identity for audit continuity)."""
        rec = current_by_title.get(titles[i - 1])
        return rec["qid"] if rec is not None else prefix_records[i - 1]["qid"]

    # duplicate-tuple detection in the PRE-fix gold (informational -- see step 5;
    # empirically all 6 groups live in article 081, whose duplicated single-char
    # IPA tuples were later dropped wholesale by the parser fix)
    prefix_identity_counts: list[Counter[Identity]] = [
        Counter(tuple(t) for t in tuples) for tuples in prefix_tuples
    ]
    # None for the 5 REPLACED_ARTICLES (no current tuples to count)
    current_identity_counts: list[Counter[Identity] | None] = [
        Counter(tuple(t) for t in cur) if (cur := current_tuples_for(i)) is not None else None
        for i in range(1, 101)
    ]

    def resolve(i: int, n: int) -> Identity:
        tuples = prefix_tuples[i - 1]
        if not (1 <= n <= len(tuples)):
            raise SystemExit(
                f"HARD ERROR: article {art3(i)} n={n} out of range "
                f"(pre-fix gt_tuples has {len(tuples)} entries)"
            )
        idx, surf, qid, slen = tuples[n - 1]
        return (idx, surf, qid, slen)

    # ── step 1+2: load removal files, resolve identities into the base flag set ──
    # key: (article_i, n) -> flag record
    flags: dict[tuple[int, int], dict[str, Any]] = {}
    wave_flag_counts: dict[str, int] = {}

    for dirname, article_range in WAVE_DIRS:
        dir_count = 0
        for i in article_range:
            fp = CLEANUP_DIR / dirname / f"{art3(i)}.json"
            if not fp.exists():
                raise SystemExit(f"HARD ERROR: missing removal file {fp}")
            obj = json.loads(fp.read_text(encoding="utf-8"))
            remove = obj.get("remove", [])
            reasons = obj.get("reasons", {})
            for n in remove:
                reason = reasons.get(str(n))
                if reason is None:
                    raise SystemExit(f"HARD ERROR: {fp} n={n} has no matching 'reasons' entry")
                identity = resolve(i, n)
                flags[(i, n)] = {"identity": identity, "reason": reason, "provenance": "wave"}
                dir_count += 1
        wave_flag_counts[dirname] = dir_count

    # ── step 3: overrides — restores drop flags, add_removals add new ones ──
    restored: list[dict[str, Any]] = []
    for r in overrides_wave1.get("restore", []):
        i, n = int(r["article"]), int(r["n"])
        key = (i, n)
        if key not in flags:
            raise SystemExit(
                f"HARD ERROR: overrides_wave1.restore article={r['article']} n={n} "
                f"is not in the base flagged set -- nothing to restore"
            )
        idx, surf, qid, slen = flags[key]["identity"]
        if r.get("anchor") is not None and r["anchor"] != surf:
            raise SystemExit(
                f"HARD ERROR: overrides_wave1.restore article={r['article']} n={n} anchor "
                f"mismatch: override says {r['anchor']!r}, resolved anchor_text={surf!r}"
            )
        del flags[key]
        restored.append({
            "article_no": art3(i), "title": titles[i - 1], "article_qid": article_qid_for(i),
            "token_index": idx, "span_len": slen, "anchor_text": surf, "qid": qid,
            "reason": r["reason"],
        })

    override_add_counts = {"override-wave1": 0, "override-wave2": 0}
    for override_obj, provenance in (
        (overrides_wave1, "override-wave1"),
        (overrides_wave2, "override-wave2"),
    ):
        for a in override_obj.get("add_removals", []):
            i, n = int(a["article"]), int(a["n"])
            key = (i, n)
            idx, surf, qid, slen = resolve(i, n)
            if a["anchor"] != surf:
                raise SystemExit(
                    f"HARD ERROR: {provenance} add_removals article={a['article']} n={n} anchor "
                    f"mismatch: override says {a['anchor']!r}, resolved anchor_text={surf!r}"
                )
            if key in flags:
                raise SystemExit(
                    f"HARD ERROR: {provenance} add_removals article={a['article']} n={n} is "
                    f"already flagged via provenance={flags[key]['provenance']!r} -- unexpected "
                    f"duplicate add"
                )
            flags[key] = {"identity": (idx, surf, qid, slen), "reason": a["reason"], "provenance": provenance}
            override_add_counts[provenance] += 1

    # ── step 6a: cross-wave adds (article 004 "исторический источник", article
    # 094 "пиньинь" -- see CROSS_WAVE_RULES) ──
    cross_wave_add_count = 0
    for rule in CROSS_WAVE_RULES:
        ci = int(rule["article"])
        for n0, t in enumerate(prefix_tuples[ci - 1], start=1):
            idx, surf, qid, slen = t
            if rule["pattern"].match(surf) and (ci, n0) not in flags:
                flags[(ci, n0)] = {"identity": (idx, surf, qid, slen), "reason": rule["reason"], "provenance": "cross-wave"}
                cross_wave_add_count += 1

    # ── step 4: reconcile every flag against CURRENT gold by identity, keyed by
    # article TITLE; REPLACED_ARTICLES flags cannot be reconciled (their article
    # is gone) and go to moot_article_replaced regardless of prefix/current state ──
    exclusions: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    moot_article_replaced: list[dict[str, Any]] = []
    duplicate_identity_cases: list[dict[str, Any]] = []

    for (i, n), rec in flags.items():
        identity = rec["identity"]
        idx, surf, qid, slen = identity
        art = art3(i)
        base = {
            "article_no": art, "title": titles[i - 1], "article_qid": article_qid_for(i),
            "token_index": idx, "span_len": slen, "anchor_text": surf, "qid": qid,
        }
        if prefix_identity_counts[i - 1][identity] > 1:
            duplicate_identity_cases.append({**base, "n_prefix": n})

        if art in REPLACED_ARTICLES:
            moot_article_replaced.append({
                **base, "reason": rec["reason"], "provenance": rec["provenance"],
                "note": REPLACEMENT_NOTE,
            })
            continue

        cur_counts = current_identity_counts[i - 1]
        assert cur_counts is not None, f"article {art} has no current tuples but is not REPLACED_ARTICLES"
        if cur_counts[identity] > 0:
            exclusions.append({**base, "reason": rec["reason"], "provenance": rec["provenance"]})
        else:
            if art not in PARSER_FIX_ARTICLES:
                raise SystemExit(
                    f"HARD ERROR: article {art} n={n} identity {identity} is absent from "
                    f"current gt.jsonl but the article is not one of the known IPA-fix articles "
                    f"{sorted(PARSER_FIX_ARTICLES)} -- investigate before treating as dropped"
                )
            dropped.append({
                **base, "reason": rec["reason"],
                "note": f"tuple no longer exists in current gt.jsonl (IPA fix {PARSER_FIX_COMMIT})",
            })

    # known-live survivors in the mostly-dropped article 081 (n=1, 68, 77) must
    # have resolved as live exclusions, not gotten swept into dropped_by_parser_fix
    live_keys = {(e["article_no"], e["token_index"], e["anchor_text"], e["qid"], e["span_len"]) for e in exclusions}
    for n in (1, 68, 77):
        idx, surf, qid, slen = resolve(81, n)
        if ("081", idx, surf, qid, slen) not in live_keys:
            raise SystemExit(f"HARD ERROR: expected article 081 n={n} ({surf!r}) to survive as a live exclusion")

    # ── replacement-audit merge: 5 new articles (R01..R05) that joined the gold
    # corpus in the 2026-07-10 swap, independently audited against CURRENT
    # gt.jsonl -- no prefix-gold indirection, ``n`` indexes current gt_tuples
    # directly (see MANIFEST_REPLACEMENTS_PATH / removals-replacements/*.json) ──
    replacement_flags: dict[tuple[str, int], dict[str, Any]] = {}
    for ridx, entry in enumerate(manifest_replacements, start=1):
        r_no = f"R{ridx:02d}"
        title = entry["title"]
        rec = current_by_title.get(title)
        if rec is None:
            raise SystemExit(
                f"HARD ERROR: replacement article {r_no} ({title!r}) title not found in "
                f"current gt.jsonl"
            )
        tuples = rec["gt_tuples"]
        if len(tuples) != entry["n_anchors"]:
            raise SystemExit(
                f"HARD ERROR: replacement article {r_no} ({title!r}) anchor-count mismatch: "
                f"manifest n_anchors={entry['n_anchors']} current gt_tuples={len(tuples)}"
            )
        fp = REMOVALS_REPLACEMENTS_DIR / f"{r_no}.json"
        if not fp.exists():
            raise SystemExit(f"HARD ERROR: missing removal file {fp}")
        obj = json.loads(fp.read_text(encoding="utf-8"))
        remove = obj.get("remove", [])
        reasons = obj.get("reasons", {})
        for n in remove:
            reason = reasons.get(str(n))
            if reason is None:
                raise SystemExit(f"HARD ERROR: {fp} n={n} has no matching 'reasons' entry")
            if not (1 <= n <= len(tuples)):
                raise SystemExit(
                    f"HARD ERROR: replacement article {r_no} n={n} out of range "
                    f"(current gt_tuples has {len(tuples)} entries)"
                )
            idxv, surf, qid, slen = tuples[n - 1]
            replacement_flags[(r_no, n)] = {
                "identity": (idxv, surf, qid, slen), "reason": reason,
                "title": title, "article_qid": rec["qid"],
            }

    for r in overrides_replacements.get("restore", []):
        r_no, n = r["article"], int(r["n"])
        key = (r_no, n)
        if key not in replacement_flags:
            raise SystemExit(
                f"HARD ERROR: overrides_replacements.restore article={r_no} n={n} is not in "
                f"the replacement-audit flagged set -- nothing to restore"
            )
        rf = replacement_flags[key]
        idxv, surf, qid, slen = rf["identity"]
        if r.get("anchor") is not None and r["anchor"] != surf:
            raise SystemExit(
                f"HARD ERROR: overrides_replacements.restore article={r_no} n={n} anchor "
                f"mismatch: override says {r['anchor']!r}, resolved anchor_text={surf!r}"
            )
        del replacement_flags[key]
        restored.append({
            "article_no": r_no, "title": rf["title"], "article_qid": rf["article_qid"],
            "token_index": idxv, "span_len": slen, "anchor_text": surf, "qid": qid,
            "reason": r["reason"], "provenance": "replacement-audit-override",
        })

    for a in overrides_replacements.get("add_removals", []):
        r_no, n = a["article"], int(a["n"])
        ridx = int(r_no[1:])
        title = manifest_replacements[ridx - 1]["title"]
        rec = current_by_title[title]
        tuples = rec["gt_tuples"]
        if not (1 <= n <= len(tuples)):
            raise SystemExit(
                f"HARD ERROR: overrides_replacements.add_removals {r_no} n={n} out of range "
                f"(current gt_tuples has {len(tuples)} entries)"
            )
        idxv, surf, qid, slen = tuples[n - 1]
        if a["anchor"] != surf:
            raise SystemExit(
                f"HARD ERROR: overrides_replacements.add_removals article={r_no} n={n} anchor "
                f"mismatch: override says {a['anchor']!r}, resolved anchor_text={surf!r}"
            )
        key = (r_no, n)
        if key in replacement_flags:
            raise SystemExit(
                f"HARD ERROR: overrides_replacements.add_removals article={r_no} n={n} is "
                f"already flagged -- unexpected duplicate add"
            )
        replacement_flags[key] = {
            "identity": (idxv, surf, qid, slen), "reason": a["reason"],
            "title": title, "article_qid": rec["qid"],
        }

    # identity (token_index, anchor_text, qid, span_len) is only unique WITHIN an
    # article (e.g. "др.-греч." legitimately recurs at the same relative
    # token_index across many unrelated articles' language-tag anchors) -- a
    # real collision means the same TITLE already has this identity excluded.
    existing_identities_by_title: dict[str, set[Identity]] = {}
    for e in exclusions:
        existing_identities_by_title.setdefault(e["title"], set()).add(
            (e["token_index"], e["anchor_text"], e["qid"], e["span_len"])
        )
    replacement_audit_add_count = 0
    for (r_no, n), rf in replacement_flags.items():
        identity = rf["identity"]
        title_identities = existing_identities_by_title.setdefault(rf["title"], set())
        if identity in title_identities:
            raise SystemExit(
                f"HARD ERROR: replacement article {r_no} n={n} ({rf['title']!r}) identity "
                f"{identity} collides with an existing exclusion for the same title"
            )
        idxv, surf, qid, slen = identity
        exclusions.append({
            "article_no": r_no, "title": rf["title"], "article_qid": rf["article_qid"],
            "token_index": idxv, "span_len": slen, "anchor_text": surf, "qid": qid,
            "reason": rf["reason"], "provenance": "replacement-audit",
        })
        title_identities.add(identity)
        replacement_audit_add_count += 1

    exclusions.sort(key=lambda e: (e["article_no"], e["token_index"]))
    dropped.sort(key=lambda e: (e["article_no"], e["token_index"]))
    restored.sort(key=lambda e: (e["article_no"], e["token_index"]))
    moot_article_replaced.sort(key=lambda e: (e["article_no"], e["token_index"]))

    # ── step 6b + 7: sweep candidates over CURRENT gold, not already excluded.
    # Keyed by TITLE (current gt.jsonl position is not a stable article id).
    # The 5 new articles from the 2026-07-10 swap have no manifest entry; they
    # are labeled with the manifest article_no they replaced, for continuity. ──
    excluded_identity_by_title: dict[str, set[Identity]] = {}
    for (i, n), rec in flags.items():
        excluded_identity_by_title.setdefault(titles[i - 1], set()).add(rec["identity"])
    for (r_no, n), rf in replacement_flags.items():
        excluded_identity_by_title.setdefault(rf["title"], set()).add(rf["identity"])

    manifest_article_no_by_title = {e["title"]: art3(i) for i, e in enumerate(manifest, start=1)}
    replaced_article_no_by_new_title = {
        new_title_by_old_title[e["title"]]: art3(i)
        for i, e in enumerate(manifest, start=1)
        if art3(i) in REPLACED_ARTICLES
    }

    def article_no_for(title: str) -> str:
        if title in manifest_article_no_by_title:
            return manifest_article_no_by_title[title]
        return replaced_article_no_by_new_title[title]

    sweep_candidates: list[dict[str, Any]] = []
    sweep_rule_counts: Counter[str] = Counter()

    for rec in current_records:
        title = rec["title"]
        article_no = article_no_for(title)
        excluded = excluded_identity_by_title.get(title, set())
        for t in rec["gt_tuples"]:
            idx, surf, qid, slen = t[0], t[1], t[2], t[3]
            identity = (idx, surf, qid, slen)
            if identity in excluded:
                continue
            if surf == PINYIN_ANCHOR_TEXT:
                sweep_candidates.append({
                    "article_no": article_no, "title": title, "anchor_text": surf,
                    "token_index": idx, "qid": qid, "rule": PINYIN_SWEEP_RULE,
                })
                sweep_rule_counts[PINYIN_SWEEP_RULE] += 1
                continue
            for rule_name, pattern in SWEEP_REGEXES:
                if pattern.match(surf):
                    sweep_candidates.append({
                        "article_no": article_no, "title": title, "anchor_text": surf,
                        "token_index": idx, "qid": qid, "rule": rule_name,
                    })
                    sweep_rule_counts[rule_name] += 1
                    break

    sweep_candidates.sort(key=lambda e: (e["article_no"], e["token_index"]))

    # ── assemble output ──
    open_questions = list(overrides_wave1.get("pending_owner", [])) + OPEN_QUESTIONS_EXTRA
    gt_rev = git_rev(GT_PATH)
    note = (
        "APPROVED by owner 2026-07-10. Semantic anchor exclusions from the "
        "gold-cleanup campaign; applied at scoring time (gt.jsonl stays raw). "
        "Anchor identity is (token_index, anchor_text, qid, span_len) against "
        f"gt.jsonl @ {gt_rev}."
    )
    counts = {
        "live_exclusions": len(exclusions),
        "dropped_by_parser_fix": len(dropped),
        "moot_article_replaced": len(moot_article_replaced),
        "restored": len(restored),
        "override_add": sum(override_add_counts.values()),
        "cross_wave_add": cross_wave_add_count,
        "replacement_audit_add": replacement_audit_add_count,
        "sweep_candidates": len(sweep_candidates),
        "open_questions": len(open_questions),
    }
    output = {
        "note": note,
        "generated_by": "data/eval/wiki/cleanup/tools/aggregate_exclusions.py",
        "counts": counts,
        "exclusions": exclusions,
        "dropped_by_parser_fix": dropped,
        "moot_article_replaced": moot_article_replaced,
        "restored": restored,
        "sweep_candidates": sweep_candidates,
        "open_questions": open_questions,
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ── summary printout ──
    print("== per-wave-dir flag counts (base 'remove' entries) ==")
    for dirname, _ in WAVE_DIRS:
        print(f"  {dirname:22s} {wave_flag_counts[dirname]}")
    print(f"\nrestored (un-flagged by owner ruling): {len(restored)}")
    print(f"override adds: {sum(override_add_counts.values())} "
          f"(wave1={override_add_counts['override-wave1']}, wave2={override_add_counts['override-wave2']})")
    print(f"cross-wave adds: {cross_wave_add_count}")
    print(f"replacement-audit adds: {replacement_audit_add_count} "
          f"(restored: {sum(1 for r in restored if r.get('provenance') == 'replacement-audit-override')})")
    print(f"\nlive exclusions total: {len(exclusions)}")
    print(f"dropped_by_parser_fix total: {len(dropped)}")
    dropped_by_article = Counter(e["article_no"] for e in dropped)
    for art in sorted(dropped_by_article):
        print(f"  dropped in {art}: {dropped_by_article[art]}")
    print(f"\nmoot_article_replaced total: {len(moot_article_replaced)}")
    moot_by_article = Counter(e["article_no"] for e in moot_article_replaced)
    for art in sorted(moot_by_article):
        print(f"  moot in {art}: {moot_by_article[art]}")
    print(f"\nsweep candidates total: {len(sweep_candidates)}")
    for rule_name, cnt in sorted(sweep_rule_counts.items()):
        print(f"  {rule_name}: {cnt}")
    print(f"\nduplicate identity cases (same tuple flagged twice in pre-fix gt_tuples): "
          f"{len(duplicate_identity_cases)}")
    for case in duplicate_identity_cases:
        print(f"  {case['article_no']} n_prefix={case['n_prefix']} {case['anchor_text']!r}")

    anchor_freq = Counter(e["anchor_text"] for e in exclusions)
    print("\nTOP-15 most frequent excluded anchor_text:")
    for surf, cnt in anchor_freq.most_common(15):
        print(f"  {cnt:4d}  {surf!r}")

    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
