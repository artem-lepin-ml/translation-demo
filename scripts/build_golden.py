#!/usr/bin/env python3
"""Build + verify the non-circular golden set for the terminology tournament.

Labels are hand-authored from domain knowledge (NOT from any running strategy's
output). Each non-red QID is verified by a *direct* Wikidata label lookup — an
identity check independent of G1's candidate-selection logic — and mismatches
are printed for correction. See spec §9 (golden non-circularity).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from palimpsest.terminology.wikidata import WikidataClient, label_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/seed/terminology_gold.jsonl"
CACHE = ROOT / "reports/terminology/wikidata_cache.jsonl"

# (surface, lemma, pid, gold_qid, expected_en, gold_difficulty, category,
#  gold_target, gold_pair, gold_recommended)  — pairing fields None = not labeled.
GOLD = [
    # ── clear greens: places ── (QIDs verified by direct EN label lookup)
    ("Месопотамии", "Месопотамия", 40, "Q11767", "Mesopotamia", "green", "place", "Mesopotamia", "green", None),
    ("Вавилон", "Вавилон", 92, "Q5684", "Babylon", "green", "place", "Babylon", "green", None),
    ("Евфрат", "Евфрат", 92, "Q34589", "Euphrates", "green", "place", "Euphrates", "green", None),
    ("Аккаде", "Аккад", 43, "Q150996", "Akkad", "green", "place", "Akkad", "green", None),
    ("Элам", "Элам", 52, "Q128904", "Elam", "green", "place", "Elam", "green", None),
    ("Ашшур", "Ашшур", 92, "Q200200", "Assur", "green", "place", "Assur", "green", None),
    ("Ниппуре", "Ниппур", 46, "Q188395", "Nippur", "green", "place", "Nippur", "green", None),
    ("Спарта", "Спарта", 306, "Q5690", "Sparta", "green", "place", "Sparta", "green", None),
    ("Афины", "Афины", 306, "Q1524", "Athens", "green", "place", "Athens", "green", None),
    ("Сицилию", "Сицилия", 291, "Q1460", "Sicily", "green", "place", "Sicily", "green", None),
    ("Эпир", "Эпир", 441, "Q11266977", "Epirus", "green", "place", "Epirus", "green", None),
    ("Хуанхэ", "Хуанхэ", 121, "Q7355", "Yellow River", "green", "place", "Yellow River", "green", None),
    ("Дамаска", "Дамаск", 92, "Q3766", "Damascus", "green", "place", "Damascus", "green", None),
    ("Македонию", "Македония", 441, "Q83958", "Macedonia", "green", "place", "Macedonia", "green", None),
    # ── greens: people (persons) ──
    ("Саргон", "Саргон", 43, "Q199461", "Sargon of Akkad", "green", "person", "Sargon", "green", None),
    ("Нарам-Суэн", "Нарам-Суэн", 46, "Q297506", "Naram-Sin of Akkad", "green", "person", "Naram-Sin", "green", None),
    ("Хаммурапи", "Хаммурапи", 64, "Q36359", "Hammurabi", "green", "person", "Hammurabi", "green", None),
    ("Александр", "Александр", 441, "Q8409", "Alexander the Great", "green", "person", "Alexander", "green", None),
    ("Алкивиад", "Алкивиад", 291, "Q187982", "Alcibiades", "green", "person", "Alcibiades", "green", None),
    ("Эпаминонда", "Эпаминонд", 306, "Q190436", "Epaminondas", "green", "person", "Epaminondas", "green", None),
    ("Уруинимгину", "Уруинимгину", 40, "Q315698", "Urukagina", "green", "person", "Urukagina", "green", None),
    ("Лугальзагеси", "Лугальзагеси", 43, "Q316241", "Lugal-zage-si", "green", "person", "Lugalzagesi", "green", None),
    # ── greens: peoples / ethnic groups ──
    ("шумеры", "шумеры", 54, "Q656043", "Sumer", "green", "people", "Sumerians", "green", None),
    ("амореев", "амореи", 92, "Q203507", "Amorites", "green", "people", "Amorites", "green", None),
    # ── greens: culture / concept ──
    ("лугалем", "лугаль", 45, "Q854642", "Lugal", "green", "institution", "lugal", "green", None),
    # ── yellows: genuine ambiguity / homonym / wrong-sense trap ──
    ("Фивах", "Фивы", 306, "Q101583", "Thebes", "yellow", "place", "Thebes", "green", None),
    ("Китая", "Китай", 121, "Q29520", "China", "yellow", "place", "China", "green", None),
    ("Клеопатра", "Клеопатра", 441, "Q257526", "Cleopatra Eurydice", "yellow", "person", None, None, None),
    ("Кадашман-Харбе", "Кадашман-Харбе", 92, "Q879879", "Kadashman-Harbe", "yellow", "person", None, None, None),
    # ── reds: genuinely no dedicated Wikidata entity in this domain ──
    ("авилумы", "авилумы", 64, None, None, "red", "people", None, None, None),
    ("мушкенумы", "мушкенумы", 64, None, None, "red", "people", None, None, None),
    ("вардумы", "вардумы", 64, None, None, "red", "people", None, None, None),
    ("Байляньдун", "Байляньдун", 122, None, None, "red", "place", None, None, None),
    ("Душицзы", "Душицзы", 122, None, None, "red", "place", None, None, None),
    ("Цзэнпиянь", "Цзэнпиянь", 122, None, None, "red", "place", None, None, None),
    ("людьми су", "люди су", 52, None, None, "red", "people", None, None, None),
    ("шаньдунского архипелага", "шаньдунский архипелаг", 121, None, None, "red", "place", None, None, None),
    ("сутии-амореи", "сутии-амореи", 92, None, None, "red", "people", None, None, None),
]

FIELDS = ("surface", "lemma", "paragraph_id", "gold_qid", "expected_en", "gold_difficulty",
          "category", "gold_target_surface", "gold_pair_accuracy", "gold_recommended")


def main() -> int:
    wd = WikidataClient(cache_path=CACHE)
    qids = [g[3] for g in GOLD if g[3]]
    ents = wd.get_entities(qids, props="labels", languages="en")
    mismatches = []
    for g in GOLD:
        d = dict(zip(FIELDS, g))
        if d["gold_qid"]:
            got = label_of(ents.get(d["gold_qid"], {}), "en")
            exp = d["expected_en"]
            if not got or exp.lower() not in got.lower() and got.lower() not in exp.lower():
                mismatches.append((d["surface"], d["gold_qid"], f"expected~{exp!r} got {got!r}"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for g in GOLD:
            fh.write(json.dumps(dict(zip(FIELDS, g)), ensure_ascii=False) + "\n")
    dist = {v: sum(1 for g in GOLD if g[5] == v) for v in ("green", "yellow", "red")}
    print(f"wrote {len(GOLD)} gold terms → {OUT.relative_to(ROOT)}  dist={dist}")
    print(f"pairing-labeled: {sum(1 for g in GOLD if g[8])}")
    if mismatches:
        print("\n⚠ QID LABEL MISMATCHES (fix these):")
        for s, q, msg in mismatches:
            print(f"  {s}: {q} — {msg}")
    else:
        print("✓ all non-red QIDs verified by direct label lookup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
