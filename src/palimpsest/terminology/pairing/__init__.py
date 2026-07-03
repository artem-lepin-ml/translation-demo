"""Pairing strategies (pairAccuracy signal).

Runnable here: P1 ``link_locate`` (default), P3 ``llm_judge`` (subagent judge).
Code-only (GPU, not run in this environment): P2 ``neural_align``.
"""
from __future__ import annotations

from .link_locate import LinkLocatePairing
from .llm_judge import LlmJudgePairing
from .neural_align import NeuralAlignPairing

__all__ = ["LinkLocatePairing", "LlmJudgePairing", "NeuralAlignPairing"]
