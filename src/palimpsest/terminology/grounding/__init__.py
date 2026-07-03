"""Grounding strategies (difficulty signal).

G1 ``api_first``, G2 ``mgenre``, G3 ``llm_judge``, G5 ``hybrid`` are archived at
git tag ``archive/grounding-g-strategies`` — superseded by the single G6
``label_first`` strategy (deterministic exact-label match, LLM judge only on
genuine ambiguity). Shared candidate generation lives in
[candidates.py](candidates.py).
"""
from __future__ import annotations

from .label_first import LabelFirstGrounding

__all__ = ["LabelFirstGrounding"]
