"""Parse a model's params_json and keep only what THAT model supports (per matrix)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .model_matrix import MATRIX

# Fixed judge seed for reproducibility (spec: wave-4 block B6). A constant, not
# configurable — the goal is identical sampling across repeated judge calls on
# the same text, not per-call seed control.
JUDGE_SEED = 7


def _is_openrouter(base_url: str) -> bool:
    return "openrouter.ai" in (base_url or "")


class ModelParams(BaseModel):
    model_config = ConfigDict(extra="ignore")  # unknown keys silently dropped

    temperature: float | None = None
    max_tokens: int = 1024
    top_k: int | None = None
    min_p: float | None = None
    seed: int | None = None
    reasoning: dict | None = None          # {"effort": ...} | {"max_tokens": ...}
    enable_thinking: bool | None = None

    @classmethod
    def for_model(cls, name: str, raw: dict) -> "ModelParams":
        raw = dict(raw or {})
        spec = MATRIX.get(name)
        if spec is not None:
            if not spec.supports_temperature:
                raw.pop("temperature", None)
            if not spec.supports_top_k:
                raw.pop("top_k", None)
            if not spec.supports_min_p:
                raw.pop("min_p", None)
            if spec.supports_seed:
                raw["seed"] = JUDGE_SEED
            else:
                raw.pop("seed", None)
            if spec.reasoning in ("none", "enable_thinking"):
                raw.pop("reasoning", None)
            if spec.reasoning != "enable_thinking":
                raw.pop("enable_thinking", None)
            reasoning = raw.get("reasoning")
            if isinstance(reasoning, dict):
                if spec.reasoning == "effort":
                    reasoning = {k: v for k, v in reasoning.items() if k == "effort"}
                elif spec.reasoning == "max_tokens":
                    reasoning = {k: v for k, v in reasoning.items() if k == "max_tokens"}
                if reasoning:
                    raw["reasoning"] = reasoning
                else:
                    raw.pop("reasoning", None)
        return cls(**raw)

    def to_extra_body(self, name: str, base_url: str) -> dict:
        eb: dict = {}
        if self.top_k is not None:
            eb["top_k"] = self.top_k
        if self.min_p is not None:
            eb["min_p"] = self.min_p
        if self.reasoning:
            eb["reasoning"] = self.reasoning
        if self.enable_thinking is not None:
            eb["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        if _is_openrouter(base_url):
            eb["usage"] = {"include": True}            # ask OR to report cost
        return eb
