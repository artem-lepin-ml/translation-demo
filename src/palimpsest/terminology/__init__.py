"""Terminology module: extract → ground (difficulty) → pair (pairAccuracy) → Term[].

End-to-end RU→EN term analysis for the Palimpsest demo. Fills both signals of the
`Term` contract from a (source, target) paragraph. See
docs/superpowers/specs/2026-07-01-terminology-e2e-design.md.
"""
from __future__ import annotations

from .base import (
    GroundingResult,
    GroundingStrategy,
    PairRequest,
    PairResult,
    PairingStrategy,
    Term,
    TermMention,
    Verdict,
    WikidataRef,
)

__all__ = [
    "Verdict",
    "WikidataRef",
    "TermMention",
    "GroundingResult",
    "PairRequest",
    "PairResult",
    "Term",
    "GroundingStrategy",
    "PairingStrategy",
]
