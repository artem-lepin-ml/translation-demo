"""Verdict logic shared by every strategy: type filter + difficulty + pairAccuracy.

Strategies differ only in how they *generate* candidates and locate the target
surface; the mapping candidates→verdict lives here so results are comparable.
"""
from __future__ import annotations

import difflib
import re

from .base import Verdict, WikidataRef
from .wikidata import ANACHRONISTIC_TYPES, DISAMBIGUATION, SCHOLARLY_ARTICLE

TYPE_DROP = {DISAMBIGUATION, SCHOLARLY_ARTICLE} | ANACHRONISTIC_TYPES

# Fuzzy thresholds for locating an EN equivalent in the translation.
GREEN_SIM = 0.90
YELLOW_SIM = 0.70


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def passes_type_filter(types: list[str]) -> bool:
    """Drop disambiguation pages and scholarly articles; keep everything else."""
    return not (set(types) & TYPE_DROP)


def difficulty_from_candidates(names: str | list[str], candidates: list[dict]) -> tuple[Verdict, WikidataRef | None, list[WikidataRef]]:
    """Map filtered candidates to (difficulty, grounded, candidates).

    ``names`` is the surface (and optionally the nominative lemma) to exact-match
    against candidate labels/aliases — Russian labels on Wikidata are nominative,
    so matching the lemma as well avoids false homonym/ambiguity calls.
    ``candidates`` are dicts ``{qid, label, description, aliases, types}`` in
    search-rank order, already type-filtered.

    green  = exactly one plausible sense (or one clear exact match)
    yellow = two or more exact-name senses (homonyms) or several plausible ones
    red    = nothing left after filtering
    """
    forms = [names] if isinstance(names, str) else list(names)
    fallback = forms[0] if forms else ""
    refs = [WikidataRef.from_qid(c["qid"], c.get("label") or fallback, c.get("description", "")) for c in candidates]
    if not refs:
        return "red", None, []

    targets = {_norm(f) for f in forms if f}

    def is_exact(c: dict) -> bool:
        return _norm(c.get("label", "")) in targets or any(_norm(a) in targets for a in c.get("aliases", []))

    grounded = refs[0]
    # yellow only for genuine notable homonyms: ≥2 candidates that both exact-match
    # the name AND are notable (have an enwiki sitelink). Minor namesakes don't count.
    notable_exact = [c for c in candidates if is_exact(c) and c.get("notable")]
    if len(notable_exact) >= 2:
        return "yellow", grounded, refs
    if is_exact(candidates[0]) or len(refs) == 1:
        return "green", grounded, refs
    return "yellow", grounded, refs


def pair_from_forms(canon_en: list[str], target: str) -> tuple[str | None, Verdict, str | None]:
    """Locate a canonical EN form in the translation → (target_surface, pairAccuracy, recommended)."""
    recommended = canon_en[0] if canon_en else None
    if not canon_en or not target.strip():
        return None, "red", recommended

    low = target.lower()
    # exact substring wins outright
    for form in canon_en:
        idx = low.find(form.lower())
        if idx != -1:
            return target[idx:idx + len(form)], "green", None

    # otherwise best fuzzy window over the translation. Guard against matching on a
    # shared tail only ("town of Akkad" vs "Sargon of Akkad"): a sub-0.95 match must
    # also share the form's head content-word.
    best_sim, best_span = 0.0, None
    tokens = re.findall(r"\S+", target)
    for form in canon_en:
        parts = form.split()
        width = max(1, len(parts))
        head = next((_norm(p) for p in parts if len(p) > 2), _norm(parts[0]) if parts else "")
        for i in range(len(tokens) - width + 1):
            window = tokens[i:i + width]
            span = " ".join(window)
            sim = difflib.SequenceMatcher(None, _norm(span), _norm(form)).ratio()
            if sim > best_sim:
                shares_head = any(head and head in _norm(w) for w in window)
                if sim >= 0.95 or shares_head:
                    best_sim, best_span = sim, span
    if best_sim >= GREEN_SIM:
        return best_span, "green", None
    if best_sim >= YELLOW_SIM:
        return best_span, "yellow", recommended
    return None, "red", recommended
