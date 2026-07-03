"""P2 — extract-align-link pairing (GPU, code-only in this environment).

Pattern A: Bertalign (LaBSE) aligns RU↔EN sentences, then SimAlign/awesome-align
(mBERT/XLM-R) gives word-level alignment, mapping the RU term span to its EN
span; the EN span is then checked against the QID's canonical equivalent. Needs a
CUDA GPU + LaBSE/mBERT weights, absent here, so ``pair`` raises rather than
degrading. Interface only; **not run** in the no-CUDA demo.
"""
from __future__ import annotations

from ..base import Judge, PairRequest, PairResult


def cuda_available() -> bool:
    try:
        import torch  # noqa: PLC0415

        return bool(torch.cuda.is_available())
    except Exception:
        return False


class NeuralAlignPairing:
    name = "neural_align"

    def __init__(self, aligner: str = "simalign", model_name: str = "sentence-transformers/LaBSE") -> None:
        self.aligner = aligner
        self.model_name = model_name

    def pair(self, req: PairRequest, *, judge: Judge | None = None) -> PairResult:
        if not cuda_available():
            raise RuntimeError(
                "NeuralAlignPairing requires a CUDA GPU + LaBSE/mBERT weights, unavailable in this "
                "environment. Code-only strategy; run on a GPU host. See docs/stages/terminology.md."
            )
        raise NotImplementedError("Bertalign + SimAlign word-alignment mapping is a GPU-host TODO.")
