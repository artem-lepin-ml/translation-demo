"""G2 — mGENRE grounding (GPU, code-only in this environment).

mGENRE (Cao et al., 2022) is a multilingual autoregressive entity linker: an
mBART model generates the entity name under a prefix-trie constraint, yielding a
QID directly from the source-language mention. It needs a CUDA GPU and the
prebuilt title trie / KB, which are absent in this session, so ``ground`` raises
rather than silently degrading. The class documents the interface and the wiring
for a GPU host; it is **not run** in the no-CUDA demo (see the report).
"""
from __future__ import annotations

from ..base import GroundingResult, Judge, TermMention


def cuda_available() -> bool:
    try:
        import torch  # noqa: PLC0415

        return bool(torch.cuda.is_available())
    except Exception:
        return False


class MGenreGrounding:
    name = "mgenre"

    def __init__(self, model_name: str = "facebook/mgenre-wiki", device: str | None = None) -> None:
        self.model_name = model_name
        self.device = device or ("cuda" if cuda_available() else "cpu")
        self._model = None  # lazily loaded on a GPU host

    def _load(self):  # pragma: no cover - requires GPU + weights
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # noqa: PLC0415

        self._tok = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name).to(self.device)

    def ground(self, mention: TermMention, *, judge: Judge | None = None) -> GroundingResult:
        if not cuda_available():
            raise RuntimeError(
                "MGenreGrounding requires a CUDA GPU + the mGENRE trie/KB, unavailable in this "
                "environment. Code-only strategy; run on a GPU host. See docs/stages/terminology.md."
            )
        self._load()  # pragma: no cover
        raise NotImplementedError("mGENRE decode + trie-constrained QID resolution is a GPU-host TODO.")
