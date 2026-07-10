"""Quantify sitelink-rung (wikipedia_wikibase_item) contamination of G6 grounded
predictions, per model run, by REPLAYING the candidate ladder from the cached
live-Wikidata responses (no network, no LLM calls).

Ladder replicated exactly from src/palimpsest/terminology/grounding/candidates.py
generate_candidates() under GroundingConfig(use_lemma=True, use_fallbacks=True,
match_aliases=True) == config "111" (the only config these two runs used):

  forms = [lemma, surface] if (lemma and lemma != surface) else [surface]
  1. wbsearchentities(form) for form in forms, lang="ru", limit=7 -> union hits
     -> source="wbsearch" if any hit
  2. else: search_cirrus(form) for form in forms, limit=7 (title startswith "Q")
     -> source="cirrus" if any hit
  3. else: wikipedia_wikibase_item(lemma or surface, lang="ru")
     -> source="sitelink" if a qid comes back

Cache key format matches wikidata.py's WikidataClient._fetch exactly:
  key = base + "?" + urlencode(sorted({**params, "format": "json", "maxlag": "5"}.items()))
so this script reconstructs the identical key string per call and looks it up
in the pre-built per-mechanism index (build_cache_index.py) -- no guessing.
"""
from __future__ import annotations
import json
import sys
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/tmp/claude-0/-home-user-translation-demo/eb7d84db-f5ab-5bf8-9951-e48d0dc8c3ae/scratchpad")
from build_cache_index import build_index  # noqa: E402

sys.path.insert(0, "src")
from palimpsest.terminology.evaluation.matching import match_m2, match_m3  # noqa: E402

REPO = Path("/home/user/translation-demo")
SCRATCH = Path("/tmp/claude-0/-home-user-translation-demo/eb7d84db-f5ab-5bf8-9951-e48d0dc8c3ae/scratchpad")

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API_RU = "https://ru.wikipedia.org/w/api.php"

RUNS = {
    "gemini": {
        "dir": REPO / "reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z",
        "cache": REPO / "reports/terminology/wikidata_cache.gemini.jsonl",
    },
    "deepseek": {
        "dir": REPO / "reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--provider-9/111/2026-07-05T23-35-52Z",
        "cache": REPO / "reports/terminology/wikidata_cache.deepseek.jsonl",
    },
}

# ---- exact key builders, mirroring wikidata.py's _fetch --------------------


def _key(base: str, params: dict) -> str:
    full = {**params, "format": "json", "maxlag": "5"}
    return base + "?" + urllib.parse.urlencode(sorted(full.items()))


def wbsearch_key(term: str, lang: str = "ru", limit: int = 7) -> str:
    return _key(WIKIDATA_API, {
        "action": "wbsearchentities", "search": term, "language": lang,
        "uselang": lang, "type": "item", "limit": str(limit),
    })


def cirrus_key(term: str, limit: int = 7) -> str:
    return _key(WIKIDATA_API, {
        "action": "query", "list": "search", "srsearch": term, "srlimit": str(limit),
    })


def sitelink_key(title: str) -> str:
    return _key(WIKIPEDIA_API_RU, {
        "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
        "titles": title, "redirects": "1",
    })


# ---- ladder replay (config "111": use_lemma=True, use_fallbacks=True) ------


def build_forms(lemma: str | None, surface: str) -> list[str]:
    forms: list[str] = []
    if lemma and lemma != surface:
        forms.append(lemma)
    if surface not in forms:
        forms.append(surface)
    # final dedup pass, mirrors candidates.py
    seen: set[str] = set()
    out = []
    for f in forms:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def replay_source(lemma: str | None, surface: str, wb_hits, cirrus_hits, sitelink_hit) -> str:
    forms = build_forms(lemma, surface)

    total_wb = 0
    for f in forms:
        k = wbsearch_key(f)
        if k not in wb_hits:
            return "unknown"
        total_wb += wb_hits[k]
    if total_wb > 0:
        return "wbsearch"

    total_cirrus = 0
    for f in forms:
        k = cirrus_key(f)
        if k not in cirrus_hits:
            return "unknown"
        total_cirrus += cirrus_hits[k]
    if total_cirrus > 0:
        return "cirrus"

    wiki_title = lemma or surface
    k = sitelink_key(wiki_title)
    if k not in sitelink_hit:
        return "unknown"
    qid = sitelink_hit[k]
    return "sitelink" if qid else "inconsistent_no_candidates"


# ---- data loading -----------------------------------------------------------


def load_gt(path: Path) -> dict[str, list[tuple]]:
    gt_by_title: dict[str, list[tuple]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            gt_by_title[d["title"]] = [tuple(t) for t in d["gt_tuples"]]
    return gt_by_title


def load_tier_assignment(path: Path) -> dict[str, int]:
    return json.load(path.open(encoding="utf-8"))


# ---- main --------------------------------------------------------------------


def recall_micro(gt_by_title, pred_by_title, mode: str, qid_filter=None) -> tuple[int, int]:
    """Sum matched/total over articles (micro-average), per aggregate_corpus's
    method: match per-article, sum raw counts, one division at the end."""
    matcher = match_m3 if mode == "m3" else match_m2
    matched_sum = 0
    total_sum = 0
    for title, gt in gt_by_title.items():
        if qid_filter is not None:
            gt = [t for t in gt if qid_filter(t[2])]
        pred = pred_by_title.get(title, [])
        matched_gt, _ = matcher(gt, pred)
        matched_sum += len(matched_gt)
        total_sum += len(gt)
    return matched_sum, total_sum


def analyze(model_name: str, run_dir: Path, cache_path: Path, gt_by_title, tier_assignment) -> dict:
    t0 = time.time()
    print(f"=== {model_name} ===", file=sys.stderr)
    wb_hits, cirrus_hits, sitelink_hit = build_index(str(cache_path))

    pred_path = run_dir / "pred.jsonl"
    n_total_rows = 0
    source_counts = defaultdict(int)
    pred_all_by_title: dict[str, list[tuple]] = defaultdict(list)
    pred_clean_by_title: dict[str, list[tuple]] = defaultdict(list)
    sitelink_rows: list[dict] = []  # for M3 match check against GT

    with pred_path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            n_total_rows += 1
            qid = d.get("qid")
            if qid is None:
                continue
            title = d["title"]
            tup = (d["index"], d["surface"], qid, d["span_len"])
            pred_all_by_title[title].append(tup)

            source = replay_source(d.get("lemma"), d["surface"], wb_hits, cirrus_hits, sitelink_hit)
            source_counts[source] += 1

            if source == "sitelink":
                sitelink_rows.append({"title": title, "index": d["index"], "surface": d["surface"],
                                       "lemma": d.get("lemma"), "qid": qid, "resolved_by": d.get("resolved_by")})
            else:
                pred_clean_by_title[title].append(tup)

    n_grounded = sum(source_counts.values())

    # sitelink-sourced: how many MATCH the reference under M3 (qid appears
    # anywhere in that article's GT tuples)?
    sitelink_matched = 0
    sitelink_resolved_by_counts = defaultdict(int)
    for row in sitelink_rows:
        gt_qids = {t[2] for t in gt_by_title.get(row["title"], [])}
        if row["qid"] in gt_qids:
            sitelink_matched += 1
        sitelink_resolved_by_counts[row["resolved_by"]] += 1

    def tier_filter(level: int):
        return lambda qid: tier_assignment.get(qid, 0) == 0 if level >= 2 else True

    results = {}
    for mode in ("m3", "m2"):
        m_orig, t_orig = recall_micro(gt_by_title, pred_all_by_title, mode)
        m_clean, t_clean = recall_micro(gt_by_title, pred_clean_by_title, mode)
        results[f"{mode}_original"] = {"matched": m_orig, "total": t_orig, "recall": round(m_orig / t_orig, 4) if t_orig else None}
        results[f"{mode}_clean"] = {"matched": m_clean, "total": t_clean, "recall": round(m_clean / t_clean, 4) if t_clean else None}

        # T2-filtered GT (R-T2): keep gt tuple iff tier_assignment[qid]==0
        t2_filter = tier_filter(2)
        m_orig_t2, t_orig_t2 = recall_micro(gt_by_title, pred_all_by_title, mode, qid_filter=t2_filter)
        m_clean_t2, t_clean_t2 = recall_micro(gt_by_title, pred_clean_by_title, mode, qid_filter=t2_filter)
        results[f"{mode}_T2_original"] = {"matched": m_orig_t2, "total": t_orig_t2, "recall": round(m_orig_t2 / t_orig_t2, 4) if t_orig_t2 else None}
        results[f"{mode}_T2_clean"] = {"matched": m_clean_t2, "total": t_clean_t2, "recall": round(m_clean_t2 / t_clean_t2, 4) if t_clean_t2 else None}
        results[f"{mode}_recall_units_lost"] = m_orig - m_clean
        results[f"{mode}_T2_recall_units_lost"] = m_orig_t2 - m_clean_t2

    out = {
        "model": model_name,
        "n_pred_rows_total": n_total_rows,
        "n_grounded": n_grounded,
        "source_distribution": dict(source_counts),
        "sitelink_count": source_counts.get("sitelink", 0),
        "sitelink_share_of_grounded": round(source_counts.get("sitelink", 0) / n_grounded, 4) if n_grounded else None,
        "unknown_count": source_counts.get("unknown", 0),
        "inconsistent_count": source_counts.get("inconsistent_no_candidates", 0),
        "sitelink_matched_m3": sitelink_matched,
        "sitelink_total": len(sitelink_rows),
        "sitelink_match_rate_m3": round(sitelink_matched / len(sitelink_rows), 4) if sitelink_rows else None,
        "sitelink_resolved_by_counts": dict(sitelink_resolved_by_counts),
        "metrics": results,
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False), file=sys.stderr)
    return out


def main():
    gt_by_title = load_gt(REPO / "data/eval/wiki/gt.jsonl")
    tier_assignment = load_tier_assignment(SCRATCH / "tier_assignment.json")

    all_results = {}
    for name, cfg in RUNS.items():
        all_results[name] = analyze(name, cfg["dir"], cfg["cache"], gt_by_title, tier_assignment)

    with (SCRATCH / "sitelink_contamination.json").open("w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print("wrote sitelink_contamination.json", file=sys.stderr)


if __name__ == "__main__":
    main()
