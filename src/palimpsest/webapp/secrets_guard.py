"""Single source of truth for 'is this params-bag key secret-like?' (used by the
model API param guard and the budget cost-log stripper). Boundary-aware so legit
params like ``max_tokens``/``top_k`` are NOT flagged while ``auth_token``/``api_key`` are.

Also holds ``redact_error``, the sibling concern for free-text exception
messages: provider SDKs (notably ``openai.AuthenticationError``) echo the bad
API key verbatim in the message ("Incorrect API key provided: sk-..."), so any
exception text written to the budget call log must be scrubbed first.
"""
from __future__ import annotations

import re

# Unambiguous secret indicators — match anywhere in the key.
_STRONG_RE = re.compile(r"secret|password|passwd|credential|bearer|api[_-]?key|apikey|authorization", re.I)
# Collision-prone short words — match ONLY as a delimited component (so "token"
# does not fire inside "max_tokens", and "key" does not fire inside "top_k").
_COMPONENT_SECRETS = {"token", "auth", "key"}


def is_secret_key(key: str) -> bool:
    if _STRONG_RE.search(key):
        return True
    parts = re.split(r"[_\-\s]+|(?<=[a-z])(?=[A-Z])", key.lower())
    return bool(set(parts) & _COMPONENT_SECRETS)


# Token-like substrings to mask in free-text error messages: OpenAI/OpenRouter
# style keys (sk-..., sess-...) and generic long base64-ish/opaque runs (e.g.
# a bearer token echoed by a provider's 401 body).
_TOKEN_RE = re.compile(r"\b(?:sk|sess|pk)-[A-Za-z0-9_-]{8,}\b|\b[A-Za-z0-9_-]{24,}\b")
_ERROR_MAX_LEN = 300


def redact_error(text: str) -> str:
    """Mask token-like substrings and cap length before an exception message is
    written to a log. Applied to every free-text error string that lands in
    budget_calls.jsonl — provider SDKs sometimes echo the API key back verbatim
    on auth failures."""
    masked = _TOKEN_RE.sub("[REDACTED]", str(text))
    if len(masked) > _ERROR_MAX_LEN:
        masked = masked[:_ERROR_MAX_LEN] + "…[truncated]"
    return masked
