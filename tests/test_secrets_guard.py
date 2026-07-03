from palimpsest.webapp.secrets_guard import is_secret_key

ALLOWED = [
    "max_tokens", "top_k", "top_p", "min_p", "temperature", "reasoning",
    "effort", "enable_thinking", "frequency_penalty", "presence_penalty",
]
BLOCKED = [
    "api_key", "apiKey", "api-key", "apikey", "token", "auth_token",
    "access_token", "refresh_token", "authorization", "auth", "password",
    "passwd", "client_secret", "bearer", "credential",
]

import pytest

@pytest.mark.parametrize("key", ALLOWED)
def test_allowed_keys_not_flagged(key):
    assert is_secret_key(key) is False

@pytest.mark.parametrize("key", BLOCKED)
def test_blocked_keys_flagged(key):
    assert is_secret_key(key) is True
