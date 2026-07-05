"""Thread-safety tests for palimpsest.terminology.wikidata.WikidataClient
(ticket 002b, article-level parallelism): article workers now share ONE
WikidataClient instance concurrently, so its in-memory cache dict and
cache-file append must be race-free, while concurrent network calls must be
bounded (politeness) WITHOUT serializing cache hits behind that bound.

`urllib.request.urlopen` is monkeypatched to a fast in-process fake -- no real
network access, deterministic and fast.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error

import pytest

from palimpsest.terminology import wikidata as wikidata_mod
from palimpsest.terminology.wikidata import WikidataClient


class _FakeResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def read(self) -> bytes:
        return json.dumps(self._data).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_fetch_bounds_network_concurrency_and_keeps_cache_file_uncorrupted(tmp_path, monkeypatch):
    """Hammer `_fetch` from many threads, each with a UNIQUE query (so every
    call is a genuine cache miss and must hit the fake network). Asserts:
    (1) concurrent network calls never exceed DEFAULT_NETWORK_CONCURRENCY,
    (2) they DO overlap (the bound isn't accidentally a full serialization),
    (3) every cache-file line is valid, uncorrupted JSON (the file-append lock
    holds), and (4) the in-memory cache dict ends up with exactly one entry
    per unique query (no lost updates)."""
    in_flight = [0]
    max_in_flight = [0]
    lock = threading.Lock()

    def fake_urlopen(req, timeout=None, context=None):
        with lock:
            in_flight[0] += 1
            max_in_flight[0] = max(max_in_flight[0], in_flight[0])
        time.sleep(0.02)
        with lock:
            in_flight[0] -= 1
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(wikidata_mod.urllib.request, "urlopen", fake_urlopen)

    cache_path = tmp_path / "cache.jsonl"
    wd = WikidataClient(cache_path=cache_path)

    n_threads = 12
    n_per_thread = 5

    def worker(idx: int) -> None:
        for i in range(n_per_thread):
            wd._fetch(wikidata_mod.API, {"action": "test", "q": f"{idx}-{i}"})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_in_flight[0] > 1  # actually overlapped
    assert max_in_flight[0] <= wikidata_mod.DEFAULT_NETWORK_CONCURRENCY  # bound held

    lines = cache_path.read_text(encoding="utf-8").splitlines()
    n_total = n_threads * n_per_thread
    assert len(lines) == n_total  # every unique query persisted exactly once, no corruption
    for line in lines:
        rec = json.loads(line)  # would raise on an interleaved/corrupted write
        assert rec["value"] == {"ok": True}

    assert len(wd._cache) == n_total
    assert wd.n_calls == n_total


def test_fetch_concurrent_identical_miss_never_corrupts_cache(tmp_path, monkeypatch):
    """Several threads racing on the SAME (identical) cache-miss key must not
    crash and must leave the in-memory cache holding a valid value for that
    key (a redundant duplicate fetch on the thundering-herd race is accepted,
    per the ticket's minimal-locking directive -- correctness, not dedup, is
    the bar)."""

    def fake_urlopen(req, timeout=None, context=None):
        time.sleep(0.01)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(wikidata_mod.urllib.request, "urlopen", fake_urlopen)

    cache_path = tmp_path / "cache.jsonl"
    wd = WikidataClient(cache_path=cache_path)

    results: list[dict] = []
    results_lock = threading.Lock()

    def worker() -> None:
        data = wd._fetch(wikidata_mod.API, {"action": "same-query"})
        with results_lock:
            results.append(data)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(r == {"ok": True} for r in results)
    # cache-file lines may include a small duplicate-write overshoot from the
    # thundering herd, but every line must still be valid, uncorrupted JSON.
    lines = cache_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1
    for line in lines:
        rec = json.loads(line)
        assert rec["value"] == {"ok": True}


# ── 429/5xx retry with Retry-After-honoring backoff (2026-07-05 canary fix) ──


def _http_error(code: int, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://www.wikidata.org/w/api.php", code,
                                  "err", headers or {}, None)


def test_fetch_retries_429_then_succeeds(monkeypatch):
    """Two 429s then a 200 must succeed after backoff -- the exact storm
    signature that killed the 2026-07-05 matrix canary run."""
    calls = [0]
    sleeps: list[float] = []

    def fake_urlopen(req, timeout=None, context=None):
        calls[0] += 1
        if calls[0] <= 2:
            raise _http_error(429)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(wikidata_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(wikidata_mod.time, "sleep", sleeps.append)

    wd = WikidataClient(cache_path=None)
    data = wd._fetch(wikidata_mod.API, {"action": "test-429"})
    assert data == {"ok": True}
    assert calls[0] == 3
    assert len(sleeps) == 2  # backed off before each retry
    assert all(s > 0 for s in sleeps)


def test_fetch_retries_5xx_then_succeeds(monkeypatch):
    calls = [0]

    def fake_urlopen(req, timeout=None, context=None):
        calls[0] += 1
        if calls[0] == 1:
            raise _http_error(500)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(wikidata_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(wikidata_mod.time, "sleep", lambda s: None)

    wd = WikidataClient(cache_path=None)
    assert wd._fetch(wikidata_mod.API, {"action": "test-500"}) == {"ok": True}
    assert calls[0] == 2


def test_fetch_deterministic_4xx_raises_immediately(monkeypatch):
    """A 400 is a deterministic client error -- no retry, no sleep, raise on
    the first attempt."""
    calls = [0]
    sleeps: list[float] = []

    def fake_urlopen(req, timeout=None, context=None):
        calls[0] += 1
        raise _http_error(400)

    monkeypatch.setattr(wikidata_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(wikidata_mod.time, "sleep", sleeps.append)

    wd = WikidataClient(cache_path=None)
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        wd._fetch(wikidata_mod.API, {"action": "test-400"})
    assert excinfo.value.code == 400
    assert calls[0] == 1
    assert sleeps == []


def test_fetch_sustained_429_exhausts_after_five_attempts(monkeypatch):
    calls = [0]

    def fake_urlopen(req, timeout=None, context=None):
        calls[0] += 1
        raise _http_error(429)

    monkeypatch.setattr(wikidata_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(wikidata_mod.time, "sleep", lambda s: None)

    wd = WikidataClient(cache_path=None)
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        wd._fetch(wikidata_mod.API, {"action": "test-429-storm"})
    assert excinfo.value.code == 429
    assert calls[0] == 5


def test_retry_after_honors_server_header_above_old_10s_cap():
    """The 2026-07-05 canary root cause: Retry-After was capped at 10s, so a
    server asking for 60s got hammered again in 10 and the storm never
    cleared. The header must now win up to 120s."""
    assert wikidata_mod._retry_after({"Retry-After": "60"}, 0) == 60.0
    assert wikidata_mod._retry_after({"Retry-After": "300"}, 0) == 120.0  # bounded


def test_retry_after_fallback_escalates_and_floors_the_header():
    # no header -> escalating 2s*(attempt+1)
    assert wikidata_mod._retry_after(None, 0) == 2.0
    assert wikidata_mod._retry_after({}, 3) == 8.0
    # a header smaller than the escalating fallback never shrinks the backoff
    assert wikidata_mod._retry_after({"Retry-After": "1"}, 3) == 8.0
    # malformed header -> fallback
    assert wikidata_mod._retry_after({"Retry-After": "soon"}, 1) == 4.0


def test_network_concurrency_is_configurable(monkeypatch):
    """`network_concurrency` is a constructor param (not hardcoded), so
    callers/tests can dial it -- verify a size-1 semaphore truly serializes."""
    in_flight = [0]
    max_in_flight = [0]
    lock = threading.Lock()

    def fake_urlopen(req, timeout=None, context=None):
        with lock:
            in_flight[0] += 1
            max_in_flight[0] = max(max_in_flight[0], in_flight[0])
        time.sleep(0.02)
        with lock:
            in_flight[0] -= 1
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(wikidata_mod.urllib.request, "urlopen", fake_urlopen)

    wd = WikidataClient(cache_path=None, network_concurrency=1)

    def worker(i: int) -> None:
        wd._fetch(wikidata_mod.API, {"action": "test", "q": str(i)})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_in_flight[0] == 1
