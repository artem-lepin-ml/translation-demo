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
