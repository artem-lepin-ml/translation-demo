"""Pairing verdict logic: locate the EN equivalent of a grounded term in the translation.

Grounding verdicts (difficulty, exact-match resolution) live in
``grounding/label_first.py`` (G6) — this module only maps a set of canonical
EN forms onto the translated text (pairAccuracy).
"""
from __future__ import annotations

import difflib
import re

from .base import Verdict

# Fuzzy thresholds for locating an EN equivalent in the translation.
GREEN_SIM = 0.90
YELLOW_SIM = 0.70


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


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
