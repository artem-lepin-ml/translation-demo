"""Curated domain lexicon of (often lowercase) historical terms + guarded ethnonym suffixes.
Recall hints only — never QIDs/notability; grounding remains the existence authority."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_LEXICON = Path(__file__).resolve().parents[3] / "data/seed/hist_term_lexicon.json"
_SUFFIXES = ("цы", "яне", "ане", "еи")          # ethnonym gentilic endings
_SUFFIX_STOPLIST = {  # common -цы/-еи words that are not ethnonyms
    "молодцы", "бойцы", "жрецы", "гонцы", "певцы", "борцы", "жрицы",
    "трофеи", "владельцы", "границы", "гробницы", "страницы", "ножницы", "единицы",
}
_MIN_STEM = 4                                    # чтобы -цы не ловило короткие обычные слова


@lru_cache(maxsize=1)
def _entries() -> list[dict]:
    return json.loads(_LEXICON.read_text(encoding="utf-8"))


def gazetteer_surfaces(source: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    # 1) exact lexicon forms as whole words
    for e in _entries():
        for form in e.get("forms", [e["lemma"]]):
            if form in seen:
                continue
            if re.search(rf"(?<![А-Яа-яЁё]){re.escape(form)}(?![А-Яа-яЁё])", source):
                seen.add(form)
                out.append({"surface": form, "category": e.get("category")})
    # 2) suffix ethnonyms (guarded). Match FULL words at a word boundary (first letter may be
    #    upper-case) so a capitalised word is never truncated to a bogus mid-word surface; the
    #    ethnonym rule then applies ONLY to lowercase-initial words — capitalised runs are the
    #    capitalised-surface extractor's job.
    for w in re.findall(r"(?<![А-Яа-яЁё])[А-Яа-яЁё][а-яё\-]+", source):
        if not w[:1].islower() or w in seen or w in _SUFFIX_STOPLIST:
            continue
        if any(w.endswith(sfx) for sfx in _SUFFIXES) and len(w) >= _MIN_STEM + 2:
            seen.add(w)
            out.append({"surface": w, "category": "people"})
    return out
