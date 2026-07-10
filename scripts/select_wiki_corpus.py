# -*- coding: utf-8 -*-
"""Selection: ns0-only + transparent date-cutoff topicality gate (<500 CE,
undated kept, tiny P31 blacklist) + hard section-binding (first fixed-order
section claims each article, used once). Fixed seed. Records the date used, so
the rule is visible in the table.

Output committed as data/eval/wiki/selection.json + titles.txt; documented
in docs/stages/wiki-eval.md § Corpus."""
from __future__ import annotations
import sys, os, json, re, time, random, urllib.parse, urllib.request, urllib.error, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from palimpsest.terminology.wikidata import USER_AGENT, WIKIPEDIA_API, _ssl_context
from palimpsest.terminology.evaluation.wiki_gt import (
    fetch_html, _collect_anchor_titles, titles_to_qids, WikiFetchError,
)

SEED = 42
NMIN = 30
CUTOFF = 500                     # CE; keep entities whose earliest date < CUTOFF
MAX_EXAMINE = 90
ROOT = Path(__file__).resolve().parents[1]
CACHE = str(ROOT / "data" / "eval" / "wiki" / "pages")
os.makedirs(CACHE, exist_ok=True)
BASE = WIKIPEDIA_API.format(lang="ru")
WD_API = "https://www.wikidata.org/w/api.php"
CTX = _ssl_context()
DATE_PROPS = ("P571", "P580", "P585", "P569", "P577")   # inception/start/point-in-time/birth/publication
P31_BLACKLIST = {"Q11424", "Q3305213", "Q33506", "Q207694"}  # film / painting / museum / art museum

SECTIONS = [
    ("Месопотамия (Шумер)", "Категория:Шумер"),
    ("Древний Египет", "Категория:Древний Египет"),
    ("Ассирия", "Категория:Ассирия"),
    ("Хеттское царство", "Категория:Хеттское царство"),
    ("Финикия", "Категория:Финикия"),
    ("Древний Иран (Ахемениды)", "Категория:Держава Ахеменидов"),
    ("Древняя Индия", "Категория:Древняя Индия"),
    ("Древний Китай", "Категория:Древний Китай"),
    ("Древняя Греция", "Категория:Древняя Греция"),
    ("Древний Рим", "Категория:Древний Рим"),
]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (attempt + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1 + attempt); continue
    return {}


def _members(cat, cmtype):
    out, cont = [], {}
    for _ in range(8):
        p = {"action": "query", "list": "categorymembers", "cmtitle": cat,
             "cmtype": cmtype, "cmlimit": "500", "format": "json"}
        if cmtype == "page":
            p["cmnamespace"] = "0"           # ns0 fix: articles only
        p.update(cont)
        data = _get(BASE + "?" + urllib.parse.urlencode(p))
        out += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        cont = data.get("continue", {})
        if not cont:
            break
        time.sleep(0.1)
    return out


def build_pool(root, maxdepth=1):
    arts, seen = set(), set()
    frontier = [(root, 0)]
    while frontier:
        cat, d = frontier.pop()
        if cat in seen:
            continue
        seen.add(cat)
        arts.update(_members(cat, "page"))
        if d < maxdepth:
            for sub in _members(cat, "subcat"):
                if sub not in seen:
                    frontier.append((sub, d + 1))
        time.sleep(0.08)
    return arts


def parse_year(t):
    if not t:
        return None
    m = re.match(r"([+-])0*(\d+)-", t)
    if not m:
        return None
    y = int(m.group(2))
    return -y if m.group(1) == "-" else y


def wbget_claims(qids):
    out = {}
    for i in range(0, len(qids), 50):
        batch = [q for q in qids[i:i + 50] if q]
        if not batch:
            continue
        params = {"action": "wbgetentities", "ids": "|".join(batch),
                  "props": "claims", "format": "json"}
        data = _get(WD_API + "?" + urllib.parse.urlencode(params))
        for qid, e in data.get("entities", {}).items():
            claims = e.get("claims", {})
            p31 = set()
            for st in claims.get("P31", []):
                v = st.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(v, dict) and v.get("id"):
                    p31.add(v["id"])
            years = []
            for P in DATE_PROPS:
                for st in claims.get(P, []):
                    v = st.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                    y = parse_year(v.get("time")) if isinstance(v, dict) else None
                    if y is not None:
                        years.append(y)
            out[qid] = {"p31": p31, "minyear": min(years) if years else None}
        time.sleep(0.1)
    return out


def gate_drop(info):
    """True = drop. Modern/medieval by date, or blacklisted type."""
    if info is None:
        return False                       # no info -> keep (undated ancient)
    if info["p31"] & P31_BLACKLIST:
        return True
    y = info["minyear"]
    return y is not None and y >= CUTOFF


def url_of(t):
    return "https://ru.wikipedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_"))


# ── build all pools (parallel), then make them exclusive by fixed section order ──
print("building pools ...", flush=True)
pools = {}
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(build_pool, c): n for n, c in SECTIONS}
    for f in cf.as_completed(futs):
        pools[futs[f]] = f.result()
        print(f"  pool {futs[f]:26s} = {len(pools[futs[f]])}", flush=True)

assigned = {}
for name, _ in SECTIONS:               # fixed order -> first wins
    for t in pools[name]:
        assigned.setdefault(t, name)
exclusive = {name: sorted(t for t in pools[name] if assigned[t] == name) for name, _ in SECTIONS}

# ── per section: seed-shuffle exclusive pool, walk windows, gate + >=NMIN links ──
out_sections = []
for name, cat in SECTIONS:
    pool = list(exclusive[name])
    rng = random.Random(SEED)
    rng.shuffle(pool)
    picks, i, examined, dropped = [], 0, 0, 0
    while len(picks) < 10 and i < len(pool) and examined < MAX_EXAMINE:
        window = pool[i:i + 45]; i += 45
        qmap = titles_to_qids(window)
        qids = [ (qmap.get(t) or {}).get("qid") for t in window ]
        claims = wbget_claims([q for q in qids if q])
        for t in window:
            if len(picks) >= 10 or examined >= MAX_EXAMINE:
                break
            examined += 1
            q = (qmap.get(t) or {}).get("qid")
            info = claims.get(q) if q else None
            if gate_drop(info):
                dropped += 1
                continue
            try:
                html = fetch_html(t, CACHE)
            except WikiFetchError:
                continue
            n = len(_collect_anchor_titles(html))
            if n >= NMIN:
                picks.append({"title": t, "links": n,
                              "year": (info or {}).get("minyear"),
                              "qid": q, "url": url_of(t)})
    out_sections.append({"section": name, "category": cat,
                         "pool_exclusive": len(exclusive[name]),
                         "examined": examined, "dropped_gate": dropped,
                         "n_found": len(picks), "picks": picks})
    yrs = [p["year"] for p in picks if p["year"] is not None]
    print(f"[v2] {name:26s} found={len(picks)}/10 examined={examined} "
          f"dropped={dropped} pool_excl={len(exclusive[name])} "
          f"years[{min(yrs) if yrs else '—'}..{max(yrs) if yrs else '—'}]", flush=True)

out = {"seed": SEED, "nmin": NMIN, "cutoff_ce": CUTOFF,
       "metric": "unique ns0 article links in <p> body",
       "rule": "ns0 + earliest-date<500CE (undated kept) + P31 blacklist {film,painting,museum} + hard bind: first fixed-order section, used once",
       "sections": out_sections}
path = str(ROOT / "data" / "eval" / "wiki" / "selection.json")
json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)
print("WROTE " + path, flush=True)
