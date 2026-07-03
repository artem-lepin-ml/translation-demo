from types import SimpleNamespace

from palimpsest.llm.client import LLMClient, LLMConfig, LLMResult


class _FakeCompletions:
    def __init__(self, holder): self.holder = holder
    def create(self, **kwargs):
        self.holder["kwargs"] = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=5,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
                cost=0.0004),
        )


def _client(monkeypatch, cfg):
    holder = {}
    c = LLMClient.__new__(LLMClient)
    c.config = cfg
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(holder)))
    return c, holder


def test_complete_returns_result_with_usage(monkeypatch):
    cfg = LLMConfig(model="m", base_url="u", api_key="k", temperature=None, max_tokens=64,
                    extra_body={"reasoning": {"effort": "low"}})
    c, holder = _client(monkeypatch, cfg)
    r = c.complete("sys", "usr")
    assert isinstance(r, LLMResult)
    assert r.content == "hi"
    assert r.usage.prompt_tokens == 10 and r.usage.reasoning_tokens == 3
    assert r.usage.cost_usd == 0.0004
    # temperature is None → NOT sent; extra_body IS sent
    assert "temperature" not in holder["kwargs"]
    assert holder["kwargs"]["extra_body"] == {"reasoning": {"effort": "low"}}


def test_complete_sends_temperature_when_set(monkeypatch):
    cfg = LLMConfig(model="m", base_url="u", api_key="k", temperature=0.7, max_tokens=64)
    c, holder = _client(monkeypatch, cfg)
    c.complete("s", "u")
    assert holder["kwargs"]["temperature"] == 0.7


def test_complete_sends_seed_when_set(monkeypatch):
    cfg = LLMConfig(model="m", base_url="u", api_key="k", max_tokens=64, seed=7)
    c, holder = _client(monkeypatch, cfg)
    c.complete("s", "u")
    assert holder["kwargs"]["seed"] == 7


def test_complete_omits_seed_when_none(monkeypatch):
    cfg = LLMConfig(model="m", base_url="u", api_key="k", max_tokens=64, seed=None)
    c, holder = _client(monkeypatch, cfg)
    c.complete("s", "u")
    assert "seed" not in holder["kwargs"]
