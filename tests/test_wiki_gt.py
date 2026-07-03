"""Tests for wiki_gt: anchor extraction, hardness, strata, filters, determinism.

All offline: fixture HTML strings + fake title->qid maps. No network.
"""
from __future__ import annotations

import json

import pytest

from palimpsest.terminology.evaluation.wiki_gt import (
    CHRONO_P31_QIDS,
    AnchorTarget,
    _follow_redirect_chain,
    build_gt,
    extract_gt,
    hardness,
    memoized_titles_to_qids,
    select_articles,
    titles_to_qids,
)

FIXTURE_HTML = """
<html>
<body>
<table class="infobox"><tr><td>Infobox junk</td></tr></table>
<p>Первое предложение о <a href="/wiki/Рим">Риме</a>, древнего
<a href="/wiki/Город">города</a>.</p>
<p>Второе предложение о <a href="./Римская_империя">падении империи</a> и
<a href="/wiki/Category:История">категории</a> и
<a href="https://example.com">внешней ссылке</a>.</p>
</body>
</html>
"""

TITLE_TO_QID = {
    "Рим": {"qid": "Q220", "canonical_title": "Рим"},
    "Город": {"qid": "Q515", "canonical_title": "Город"},
    "Римская империя": {"qid": "Q2277", "canonical_title": "Римская империя"},
}


def test_extract_gt_anchor_tuples_from_fixture():
    result = extract_gt(FIXTURE_HTML, TITLE_TO_QID)
    tuples_by_qid = {t[2]: t for t in result.tuples}

    assert "Q220" in tuples_by_qid
    assert "Q515" in tuples_by_qid
    assert "Q2277" in tuples_by_qid

    rim = tuples_by_qid["Q220"]
    assert rim[1] == "Риме"
    assert rim[3] == 1  # single-token span

    # multi-word anchor: "падении империи" -> span_len 2
    empire = tuples_by_qid["Q2277"]
    assert empire[1] == "падении империи"
    assert empire[3] == 2


def test_extract_gt_tuples_are_index_ordered_and_first_token_index():
    result = extract_gt(FIXTURE_HTML, TITLE_TO_QID)
    indices = [t[0] for t in result.tuples]
    assert indices == sorted(indices)
    # "Риме," is the 4th token (0-based index 3): Первое(0) предложение(1) о(2) Риме,(3).
    rim = next(t for t in result.tuples if t[2] == "Q220")
    assert rim[0] == 3


def test_extract_gt_excludes_nonmain_namespace_anchors():
    result = extract_gt(FIXTURE_HTML, TITLE_TO_QID)
    surfaces = [t[1] for t in result.tuples]
    assert "категории" not in surfaces
    assert "внешней ссылке" not in surfaces
    # Category: link + the external http(s) link are both non-main-namespace/external.
    assert result.counters.n_excluded_nonmain == 2


def test_extract_gt_counts_anchors_only_for_main_namespace():
    result = extract_gt(FIXTURE_HTML, TITLE_TO_QID)
    # 3 main-namespace anchors resolve to QIDs: Рим, Город, Римская империя.
    assert result.counters.n_anchors == 3


def test_extract_gt_redlink_counter():
    html = (
        '<html><body><p>Есть '
        '<a href="/wiki/Несуществующая">несуществующая</a> статья.</p></body></html>'
    )
    result = extract_gt(html, {})
    assert result.counters.n_redlink == 1
    assert result.tuples == []
    assert result.anchor_targets[0].qid is None


def test_extract_gt_no_qid_counter():
    html = '<html><body><p>Есть <a href="/wiki/БезQID">страница без QID</a>.</p></body></html>'
    title_to_qid = {"БезQID": {"qid": None, "canonical_title": "БезQID"}}
    result = extract_gt(html, title_to_qid)
    assert result.counters.n_no_qid == 1
    assert result.tuples == []


def test_extract_gt_piped_anchor_surface_differs_from_canonical_title():
    html = '<html><body><p>Это <a href="/wiki/Цин (династия)">Цин</a> династия.</p></body></html>'
    title_to_qid = {"Цин (династия)": {"qid": "Q12345", "canonical_title": "Цин (династия)"}}
    result = extract_gt(html, title_to_qid)
    assert len(result.tuples) == 1
    target = result.anchor_targets[0]
    assert target.surface == "Цин"
    assert target.canonical_title == "Цин (династия)"
    assert target.surface != target.canonical_title  # piped -> contributes to hardness


def test_extract_gt_chrono_filter_drops_year_target():
    html = (
        '<html><body><p>Это случилось в '
        '<a href="/wiki/1990_год">1990 году</a>.</p></body></html>'
    )
    title_to_qid = {"1990 год": {"qid": "Q2544", "canonical_title": "1990 год"}}
    calendar_year_qid = next(iter(CHRONO_P31_QIDS))
    result = extract_gt(
        html, title_to_qid, p31_of=lambda qid: {calendar_year_qid} if qid == "Q2544" else set()
    )
    assert result.tuples == []
    assert result.counters.n_excluded_chrono == 1


def test_extract_gt_redirect_canonicalization():
    # anchor points at a redirect title; title_to_qid records the canonical
    # (post-redirect) title, distinct from the href target.
    html = '<html><body><p>См. <a href="/wiki/СтараяФорма">Старая форма</a>.</p></body></html>'
    title_to_qid = {"СтараяФорма": {"qid": "Q999", "canonical_title": "НоваяФорма"}}
    result = extract_gt(html, title_to_qid)
    assert len(result.tuples) == 1
    assert result.tuples[0][2] == "Q999"
    target = result.anchor_targets[0]
    assert target.anchor_target_title == "СтараяФорма"
    assert target.canonical_title == "НоваяФорма"


def test_extract_gt_global_index_across_paragraph_boundary():
    result = extract_gt(FIXTURE_HTML, TITLE_TO_QID)
    empire = next(t for t in result.tuples if t[2] == "Q2277")
    rim = next(t for t in result.tuples if t[2] == "Q220")
    assert empire[0] > rim[0]


# ── hardness ─────────────────────────────────────────────────────────────────


def test_hardness_piped_anchor_counts_as_ambiguous():
    targets = [
        AnchorTarget(surface="Цин", anchor_target_title="Цин (династия)",
                     canonical_title="Цин (династия)", qid="Q1"),
        AnchorTarget(surface="Рим", anchor_target_title="Рим",
                     canonical_title="Рим", qid="Q2"),
    ]
    scores = hardness({"page": targets})
    assert scores["page"] == 0.5  # 1 of 2 grounded anchors is piped/ambiguous


def test_hardness_same_surface_different_qid_across_pool_is_ambiguous():
    page_a = [AnchorTarget(surface="Мир", anchor_target_title="Мир",
                            canonical_title="Мир", qid="Q_peace")]
    page_b = [AnchorTarget(surface="Мир", anchor_target_title="Мир (город)",
                            canonical_title="Мир (город)", qid="Q_town")]
    scores = hardness({"a": page_a, "b": page_b})
    assert scores["a"] == 1.0
    assert scores["b"] == 1.0


def test_hardness_unambiguous_page_scores_zero():
    targets = [
        AnchorTarget(surface="Рим", anchor_target_title="Рим", canonical_title="Рим", qid="Q1"),
        AnchorTarget(
            surface="Афины", anchor_target_title="Афины", canonical_title="Афины", qid="Q2"
        ),
    ]
    scores = hardness({"page": targets})
    assert scores["page"] == 0.0


def test_hardness_page_with_no_grounded_anchors_scores_zero():
    targets = [AnchorTarget(surface="X", anchor_target_title="X", canonical_title=None, qid=None)]
    scores = hardness({"page": targets})
    assert scores["page"] == 0.0


# ── select_articles ──────────────────────────────────────────────────────────


def test_select_articles_forces_seeds_into_hard():
    pool = {f"page{i}": 0.1 for i in range(10)}
    pool["low_score_seed"] = 0.0
    result = select_articles(pool, n_hard=3, n_typical=3, seeds=["low_score_seed"])
    assert "low_score_seed" in result.hard
    assert result.n_hard_seeds == 1


def test_select_articles_ranks_by_hardness_descending():
    pool = {"a": 0.9, "b": 0.5, "c": 0.1, "d": 0.3}
    result = select_articles(pool, n_hard=2, n_typical=2, seeds=[])
    assert result.hard == ["a", "b"]


def test_select_articles_typical_excludes_hard():
    pool = {"a": 0.9, "b": 0.5, "c": 0.1, "d": 0.3}
    result = select_articles(pool, n_hard=1, n_typical=3, seeds=[])
    assert "a" not in result.typical
    assert set(result.typical) == {"b", "c", "d"}


def test_select_articles_seed_not_in_pool_is_ignored():
    pool = {"a": 0.5, "b": 0.3}
    result = select_articles(pool, n_hard=2, n_typical=2, seeds=["ghost"])
    assert "ghost" not in result.hard
    assert result.n_hard_seeds == 0


# ── build_gt: determinism + fail-loud ────────────────────────────────────────


def _fake_fetch(title, cache_dir):
    return {
        "PageA": FIXTURE_HTML,
        "PageB": '<html><body><p>Простой <a href="/wiki/Рим">Рим</a> текст.</p></body></html>',
    }[title]


def _fake_titles_to_qids(titles):
    merged = dict(TITLE_TO_QID)
    merged.setdefault("Рим", {"qid": "Q220", "canonical_title": "Рим"})
    return {t: merged.get(t) for t in titles}


def test_build_gt_is_deterministic_byte_identical(tmp_path):
    titles = {"PageA": "Q_A", "PageB": "Q_B"}
    out1 = tmp_path / "gt1.jsonl"
    out2 = tmp_path / "gt2.jsonl"

    build_gt(titles, tmp_path / "cache", out1,
             fetch_fn=_fake_fetch, titles_to_qids_fn=_fake_titles_to_qids)
    build_gt(titles, tmp_path / "cache", out2,
             fetch_fn=_fake_fetch, titles_to_qids_fn=_fake_titles_to_qids)

    assert out1.read_bytes() == out2.read_bytes()


def test_build_gt_writes_one_record_per_article_sorted_by_title(tmp_path):
    titles = {"PageA": "Q_A", "PageB": "Q_B"}
    out = tmp_path / "gt.jsonl"
    build_gt(titles, tmp_path / "cache", out,
             fetch_fn=_fake_fetch, titles_to_qids_fn=_fake_titles_to_qids)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert [r["title"] for r in records] == ["PageA", "PageB"]
    assert records[0]["qid"] == "Q_A"
    assert "gt_tuples" in records[0]
    assert "counters" in records[0]
    assert records[0]["chrono_p31_version"] == "chrono_p31_v1"
    assert "chrono_p31_hash" in records[0]


def test_build_gt_fails_loud_over_failure_threshold(tmp_path):
    from palimpsest.terminology.evaluation.wiki_gt import WikiFetchError

    def flaky_fetch(title, cache_dir):
        if title == "PageA":
            raise WikiFetchError("boom")
        return _fake_fetch(title, cache_dir)

    # 1 of 2 articles fails -> 50% > 10% threshold -> fail loud.
    titles = {"PageA": "Q_A", "PageB": "Q_B"}
    with pytest.raises(WikiFetchError):
        build_gt(titles, tmp_path / "cache", tmp_path / "gt.jsonl",
                 fetch_fn=flaky_fetch, titles_to_qids_fn=_fake_titles_to_qids)


# ── redirect chains (bug fix: only one hop was followed) ───────────────────


def test_follow_redirect_chain_single_hop():
    redirects = {"A": "B"}
    assert _follow_redirect_chain("A", redirects) == "B"


def test_follow_redirect_chain_double_redirect():
    # A -> B -> C: a single .get() lookup would wrongly stop at B.
    redirects = {"A": "B", "B": "C"}
    assert _follow_redirect_chain("A", redirects) == "C"


def test_follow_redirect_chain_no_redirect_returns_input():
    assert _follow_redirect_chain("A", {}) == "A"


def test_follow_redirect_chain_cycle_guard_terminates():
    # A -> B -> A: must not loop forever; must return a stable value.
    redirects = {"A": "B", "B": "A"}
    result = _follow_redirect_chain("A", redirects)
    assert result in ("A", "B")


def test_titles_to_qids_resolves_double_redirect_end_to_end(monkeypatch):
    """A -> B -> C double redirect via the real titles_to_qids parsing path:
    the API's `redirects` list itself contains a chain that must be followed
    to the fixed point, not stopped after one hop."""
    import json as _json
    from io import BytesIO

    api_response = {
        "query": {
            "redirects": [
                {"from": "A", "to": "B"},
                {"from": "B", "to": "C"},
            ],
            "normalized": [],
            "pages": {
                "1": {"title": "C", "pageprops": {"wikibase_item": "Q999"}},
            },
        }
    }

    class _FakeResponse:
        def __init__(self, payload: bytes):
            self._buf = BytesIO(payload)

        def read(self):
            return self._buf.read()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _fake_urlopen(req, timeout=None, context=None):
        return _FakeResponse(_json.dumps(api_response).encode("utf-8"))

    monkeypatch.setattr(
        "palimpsest.terminology.evaluation.wiki_gt.urllib.request.urlopen", _fake_urlopen
    )

    result = titles_to_qids(["A"])
    assert result["A"] == {"qid": "Q999", "canonical_title": "C"}


# ── build_gt: distinct failure counters (E-D17) ─────────────────────────────


def test_build_gt_distinguishes_fetch_failed_from_malformed_html(tmp_path):
    from palimpsest.terminology.evaluation.wiki_gt import WikiFetchError

    def fetch_with_both_failure_kinds(title, cache_dir):
        if title == "PageFetchFail":
            raise WikiFetchError("network boom")
        if title == "PageMalformed":
            return "<html><body></body></html>"  # no <p> text -> zero tokens
        return _fake_fetch(title, cache_dir)

    # 2 failures / 21 titles ~= 9.5% -- stays under the 10% fail-loud
    # threshold so build_gt returns a summary instead of raising.
    titles = {"PageFetchFail": "Q_X", "PageMalformed": "Q_Y"}
    titles.update({f"PageA{i}": f"Q_A{i}" for i in range(19)})

    def fetch_healthy_by_default(title, cache_dir):
        if title in ("PageFetchFail", "PageMalformed"):
            return fetch_with_both_failure_kinds(title, cache_dir)
        return _fake_fetch("PageA", cache_dir)

    summary = build_gt(
        titles, tmp_path / "cache", tmp_path / "gt.jsonl",
        fetch_fn=fetch_healthy_by_default, titles_to_qids_fn=_fake_titles_to_qids,
    )
    assert summary["n_fetch_failed"] == 1
    assert summary["n_malformed_html"] == 1
    assert summary["n_title_to_qid_failed"] == 0
    # both distinct counters written to the companion summary file
    summary_path = tmp_path / "gt.jsonl.summary.json"
    assert summary_path.exists()
    on_disk = json.loads(summary_path.read_text(encoding="utf-8"))
    assert on_disk["n_fetch_failed"] == 1
    assert on_disk["n_malformed_html"] == 1


# ── build_gt: batch title->QID failure isolation ────────────────────────────


def test_build_gt_isolates_title_to_qid_batch_failure_to_one_article(tmp_path):
    """A transient titles_to_qids_fn failure on one article must not abort
    the whole build or discard other articles' progress (spec Sec.3.1)."""
    from palimpsest.terminology.evaluation.wiki_gt import WikiFetchError

    def flaky_titles_to_qids(titles):
        # PageA's anchor set includes "Рим" -- fail only when asked about it.
        if "Рим" in titles and "Город" in titles:
            raise WikiFetchError("batch boom")
        return _fake_titles_to_qids(titles)

    def fetch_by_prefix(title, cache_dir):
        return FIXTURE_HTML if title == "PageA" else _fake_fetch("PageB", cache_dir)

    # 1 failure / 20 titles == 5% -- stays under the 10% fail-loud threshold.
    titles = {"PageA": "Q_A"}
    titles.update({f"PageB{i}": f"Q_B{i}" for i in range(19)})

    summary = build_gt(
        titles, tmp_path / "cache", tmp_path / "gt.jsonl",
        fetch_fn=fetch_by_prefix, titles_to_qids_fn=flaky_titles_to_qids,
    )
    # PageA's batch call fails (excluded); all PageB* still get written.
    assert summary["n_title_to_qid_failed"] == 1
    assert summary["n_articles_written"] == 19

    lines = (tmp_path / "gt.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(l) for l in lines]
    titles_written = {r["title"] for r in records}
    assert "PageA" not in titles_written
    assert len(titles_written) == 19


# ── memoized_titles_to_qids: single fetch per title, reused across calls ───


def test_memoized_titles_to_qids_fetches_each_title_only_once():
    calls: list[list[str]] = []

    def fake_fn(titles):
        calls.append(list(titles))
        return {t: {"qid": f"Q_{t}", "canonical_title": t} for t in titles}

    wrapped = memoized_titles_to_qids(fake_fn)

    first = wrapped(["A", "B"])
    assert first == {
        "A": {"qid": "Q_A", "canonical_title": "A"},
        "B": {"qid": "Q_B", "canonical_title": "B"},
    }
    assert calls == [["A", "B"]]

    # "A" already cached; only "C" is a new title -> only "C" is fetched.
    second = wrapped(["A", "C"])
    assert second == {
        "A": {"qid": "Q_A", "canonical_title": "A"},
        "C": {"qid": "Q_C", "canonical_title": "C"},
    }
    assert calls == [["A", "B"], ["C"]]  # "A" NOT re-fetched


def test_memoized_titles_to_qids_no_call_when_all_titles_cached():
    calls: list[list[str]] = []

    def fake_fn(titles):
        calls.append(list(titles))
        return {t: {"qid": f"Q_{t}", "canonical_title": t} for t in titles}

    wrapped = memoized_titles_to_qids(fake_fn)
    wrapped(["A"])
    wrapped(["A"])  # fully cached -> underlying fn not called again
    assert calls == [["A"]]
