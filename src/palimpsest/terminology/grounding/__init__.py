"""Grounding strategies (difficulty signal).

Runnable here: G1 ``api_first`` (default, deterministic), G3 ``llm_judge`` (subagent
judge), G5 ``hybrid`` (api_first difficulty + judge-picked QID). Shared candidate
generation lives in [candidates.py](candidates.py). Code-only (GPU, not run in this
environment): G2 ``mgenre``.
"""
from __future__ import annotations

from .api_first import ApiFirstGrounding
from .hybrid import HybridGrounding
from .llm_judge import LlmJudgeGrounding
from .mgenre import MGenreGrounding

__all__ = ["ApiFirstGrounding", "HybridGrounding", "LlmJudgeGrounding", "MGenreGrounding"]
