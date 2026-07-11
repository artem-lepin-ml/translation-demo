"""Seed the demo DB from the curated pilot slice (rev-4 contract §3 seed).

Run: ``uv run python -m palimpsest.webapp.seed``. Creates one document of ~16
curated paragraphs (richest by issue count) with baseline scores+issues
(kind='seed'), a pre-computed 'cache' uplift used as the /evaluate timeout
fallback, mock terms (two 🟢🟡🔴 signals) and a few glossary rows.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from .. import paths
from . import db
from .aggregate import compute_aggregate
from .judge import derive_severity, sanitize_issue
from .model_matrix import MATRIX, DEFAULT_CRITERION_MODEL

# label_first is the terminology grounding package's judge-prompt constant, not
# an LLMClient import — no conflict with the LLM-access-via-LLMClient design.
from ..terminology.grounding.label_first import DEFAULT_GROUNDING_JUDGE_PROMPT

SEED_FILE = paths.DATA / "seed" / "seed_paragraphs.jsonl"

# 3 default evaluators (EMNLP demo sprint, 2026-07-11): Terminology (the
# LLM-judge scoring dimension — NOT the separate Wikidata term-grounding
# pipeline, which is untouched and still fed by `_seed_terms` below) and the
# already-disabled legacy Cultural Adaptation (dropped wave-4 Б4) are both
# retired; see docs/superpowers/specs/2026-06-30-demo-contracts.md rev-6
# delta. Cold palette — NOT 🟢🟡🔴.
CRITERIA = [
    ("accuracy", "Accuracy", 0.40, "#4d8dff"),
    ("fluency",  "Fluency",  0.30, "#2ad4c8"),
    ("style",    "Style",    0.30, "#b072ff"),
]
SCALE_MIN, SCALE_MAX = 1.0, 10.0
CACHE_UPLIFT = 1.5
MODEL_NAME = DEFAULT_CRITERION_MODEL
VERDICTS = ("green", "yellow", "red")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _criteria_rows(conn):
    return conn.execute("SELECT * FROM criterion WHERE enabled=1").fetchall()


def seed() -> None:
    if db.DB_PATH.exists() and not os.environ.get("PALIMPSEST_SEED_FORCE"):
        existing = sqlite3.connect(str(db.DB_PATH))
        try:
            n_docs = existing.execute("SELECT COUNT(*) FROM document").fetchone()[0]
        except sqlite3.OperationalError:
            n_docs = 0  # pre-schema file (e.g. empty placeholder) — nothing to protect
        finally:
            existing.close()
        if n_docs > 0:
            raise RuntimeError(
                f"refusing to reseed non-empty DB at {db.DB_PATH} ({n_docs} document(s)) — "
                "this destroys live predictions. Set PALIMPSEST_SEED_FORCE=1 to override."
            )
    conn = db.init_db(reset=True)
    ts = _now()

    # model registry: all 5 curated demo/paper rows, unconditionally (2026-07-11
    # EMNLP sprint — MATRIX itself is now exactly the curated set, so the old
    # PALIMPSEST_SEED_DEMO "skip the dead vLLM placeholders" branch no longer
    # applies; the one remaining vLLM row, TranslateGemma-27B, is a deliberate
    # display-only placeholder every environment seeds the same way). Shared OR
    # key from env goes to OpenRouter rows; the vLLM row keeps an empty key.
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    for spec in MATRIX.values():
        conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                     (spec.name, spec.base_url,
                      or_key if spec.is_openrouter else "",
                      json.dumps(spec.default_params)))

    # criteria (prompt body carried into prompts/scoring/<id>.md)
    for cid, name, weight, color in CRITERIA:
        prompt = (paths.PROMPTS / "scoring" / f"{cid}.md").read_text(encoding="utf-8")
        conn.execute(
            "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
            "VALUES(?,?,?,?,?,?,?,?,1)",
            (cid, name, MODEL_NAME, prompt, SCALE_MIN, SCALE_MAX, weight, color))

    crit_rows = _criteria_rows(conn)

    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,seed_model,"
        "seed_prompt_variant,version,origin,created_at) VALUES(?,?,?,?,?,?,0,'seed',?)",
        ("Mesopotamia — ancient Near East (pilot)", "ru", "en", "gpt-5.4-mini",
         "gpt-5.5-low", "v2", ts)).lastrowid

    rows = [json.loads(l) for l in SEED_FILE.read_text("utf-8").splitlines() if l.strip()]
    for idx, d in enumerate(rows):
        ru, en = d["source"], d["translated"]
        pid = conn.execute(
            "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
            (doc_id, idx, ru, en, en)).lastrowid
        revision_id = db.write_revision(conn, pid, en, "seed", ts)

        baseline_vals: dict[str, float] = {}
        for cid, *_ in CRITERIA:
            payload = d.get(cid)
            if not isinstance(payload, dict) or payload.get("final_score") is None:
                continue
            baseline_vals[cid] = float(payload["final_score"])
        agg, ckey = compute_aggregate(baseline_vals, crit_rows)
        cache_vals = {c: min(v + CACHE_UPLIFT, SCALE_MAX) for c, v in baseline_vals.items()}
        cache_agg, _ = compute_aggregate(cache_vals, crit_rows)

        for cid, *_ in CRITERIA:
            payload = d.get(cid)
            if cid not in baseline_vals:
                continue
            summary = payload.get("summary", "")
            conn.execute(
                "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at,revision_id) "
                "VALUES(?,?,?,?,?,?,'seed',?,?)",
                (pid, cid, baseline_vals[cid], summary, agg, ckey, ts, revision_id))
            conn.execute(
                "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at,revision_id) "
                "VALUES(?,?,?,?,?,?,'cache',?,?)",
                (pid, cid, cache_vals[cid], summary, cache_agg, ckey, ts, revision_id))
            for it in (payload.get("identified_issues") or []):
                expl = it.get("explanation", "")
                issue = sanitize_issue({
                    "targetFragment": it.get("problematic_fragment", ""),
                    "sourceFragment": it.get("source_fragment", ""),
                    "explanation": expl,
                    "suggestion": it.get("suggestion", ""),
                    "severity": derive_severity(expl),
                    "mqmCategory": None,
                })
                conn.execute(
                    "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
                    "suggestion,severity,mqm_category,status,kind,created_at) VALUES(?,?,?,?,?,?,?,?,'open','seed',?)",
                    (pid, cid, issue["targetFragment"], issue["sourceFragment"], issue["explanation"],
                     issue["suggestion"], issue["severity"], issue["mqmCategory"], ts))

        _seed_terms(conn, pid, ru, en, d.get("terminology"))

    _seed_glossary(conn)
    _seed_grounding_config(conn)
    _seed_translator_config(conn)
    _seed_refiner_config(conn)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) n FROM paragraph").fetchone()["n"]
    print(f"seeded {n} paragraphs, doc_id={doc_id}, model_key={'set' if os.environ.get('OPENROUTER_API_KEY') else 'EMPTY (cache fallback)'}")


def _seed_terms(conn, pid: int, ru: str, en: str, terminology) -> None:
    if not isinstance(terminology, dict):
        return
    seen: set[tuple[int, int]] = set()
    for i, t in enumerate(terminology.get("identified_terms") or []):
        surface = t.get("source_term", "")
        if not surface:
            continue
        start = ru.find(surface)
        if start == -1 or (start, start + len(surface)) in seen:
            continue
        seen.add((start, start + len(surface)))
        end = start + len(surface)
        target = t.get("translation_used") or None
        diff = VERDICTS[i % 3]
        ctx = ru[max(0, start - 30): end + 30]
        # scripts/enrich_seed_terms.py (spec §7) stamps real Wikidata grounding
        # onto identified_terms entries — qid/candidates/trace instead of the
        # synthetic Q-id fallback below. "resolved_by" is the marker key.
        enriched = "resolved_by" in t
        candidates_json = "[]"
        trace_json = "{}"
        if diff == "red":
            # Null rule mirrors the real pipeline (terminology.pipeline.run):
            # a red-difficulty term never carries a grounded qid or candidates,
            # even when enrichment did resolve one — see
            # tests/test_terminology.py::test_pipeline_enforces_null_rule_on_red.
            grounded, pair, rec = None, None, None
            if enriched:
                trace_json = json.dumps(t.get("trace") or {})
        elif enriched:
            qid = t.get("qid")
            grounded = None
            if qid:
                cand_desc = next(
                    (c.get("description") for c in (t.get("candidates") or []) if c.get("qid") == qid), None)
                grounded = {"qid": qid, "label": t.get("label_en") or target or surface,
                            "description": cand_desc or t.get("domain", "term"),
                            "url": f"https://www.wikidata.org/wiki/{qid}"}
            candidates_json = json.dumps(t.get("candidates") or [])
            trace_json = json.dumps(t.get("trace") or {})
            pair = "green" if diff == "green" else "yellow"
            rec = None if pair == "green" else (target or surface)
        else:
            qid = f"Q{100000 + (hash(surface) % 900000)}"
            grounded = {"qid": qid, "label": (target or surface),
                        "description": t.get("domain", "term"),
                        "url": f"https://www.wikidata.org/wiki/{qid}"}
            pair = "green" if diff == "green" else "yellow"
            rec = None if pair == "green" else (target or surface)
        if target and en.find(target) == -1:
            target = None  # not present in translation → pairAccuracy stays, EN span suppressed by UI
        conn.execute(
            "INSERT OR IGNORE INTO term(paragraph_id,source_surface,source_lemma,context,char_start,char_end,"
            "difficulty,grounded_json,candidates_json,target_surface,pair_accuracy,recommended,note,trace_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, surface, surface, ctx, start, end, diff,
             json.dumps(grounded) if grounded else None, candidates_json,
             target, pair, rec, t.get("domain", ""), trace_json))


def _seed_grounding_config(conn) -> None:
    conn.execute(
        "INSERT INTO grounding_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (MODEL_NAME, DEFAULT_GROUNDING_JUDGE_PROMPT,
         json.dumps({"max_tokens": 512, "temperature": 0})))


def _seed_translator_config(conn) -> None:
    """Mirrors _seed_grounding_config (spec 2026-07-05-translator §2.1) — the
    same default draft prompt every fresh dev/test/e2e DB gets, generalised
    with {source_lang}/{target_lang} placeholders rendered per document."""
    prompt = (paths.PROMPTS / "translator" / "default.md").read_text(encoding="utf-8")
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, prompt, json.dumps({"max_tokens": 2048, "temperature": 0.3})))


def _seed_refiner_config(conn) -> None:
    """Mirrors _seed_translator_config — the refiner role (paper: "a dedicated
    refiner LLM integrates aggregated corrections in a single pass") is a
    singleton config exactly like the translator's, just for a rewrite-style
    call instead of a first-pass draft."""
    prompt = (paths.PROMPTS / "refiner" / "default.md").read_text(encoding="utf-8")
    conn.execute(
        "INSERT INTO refiner_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, prompt, json.dumps({"max_tokens": 2048, "temperature": 0.2})))


def _seed_glossary(conn) -> None:
    entries = [
        ("Месопотамия", "в низовьях Тигра и Евфрата", "Mesopotamia",
         "https://www.wikidata.org/wiki/Q11767", "Q11767"),
        ("убейдская культура", "археологическая культура Южного Двуречья", "Ubaid culture",
         "https://www.wikidata.org/wiki/Q392941", "Q392941"),
        ("шумеры", "носители клинописи", "Sumerians",
         "https://www.wikidata.org/wiki/Q35355", "Q35355"),
    ]
    for term, ctx, eq, url, qid in entries:
        conn.execute(
            "INSERT OR IGNORE INTO glossary(term,context,target_equivalent,wikidata_url,wikidata_id) "
            "VALUES(?,?,?,?,?)", (term, ctx, eq, url, qid))


if __name__ == "__main__":
    seed()
