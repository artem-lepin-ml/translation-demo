"""Shared Wikidata candidate generation for the G6 label_first strategy.

Search order, widening only when thin:

  1. ``wbsearchentities(lemma)`` — only if ``config.use_lemma`` and the lemma
     differs from the surface (Russian is heavily inflected; the nominative
     lemma recovers hits the inflected surface misses).
  2. ``wbsearchentities(surface)``
  3. if 0 hits total and ``config.use_cirrus``: CirrusSearch full-text
     (``list=search``) over both forms — recovers inflected/rare terms the
     prefix search misses.
  4. if still 0 and ``config.use_sitelink``: Wikipedia RU-title → Wikidata
     item — last resort for historicisms. Independently gatable from rung 3
     because it shares its title->QID mapping with the wiki-eval reference
     annotations (evaluation circularity, see docs/stages/wiki-eval.md).

Every search call is logged to ``queries`` (feeds ``GroundingTrace`` v1); each
query dict carries ``"strategy"`` — ``"prefix"`` (rungs 1-2 and the alt-names
widening tier, all ``wbsearchentities``), ``"cirrus"`` (rung 3), ``"sitelink"``
(rung 4), or ``"guess"`` (the label-guess widening tier's queries — same
``wbsearchentities`` backend as ``"prefix"``, but flagged distinctly so a
trace UI can visually tell an LLM-guessed query apart from an ordinary
widening call at a glance; live-pipeline wiring, owner-approved 2026-07-17)
— so a trace UI can tell 5+ escalating calls for one 2-word mention apart
from dumb repetition (owner UI review, 2026-07-16).
Candidates are filtered for Wikidata "meta" items (Wikinews articles,
disambiguation/category/template/list *pages* -- see
``_NON_ENTITY_P31_BLOCKLIST``) via their already-fetched P31 claim, then
enriched, redirect-canonicalised, and returned as plain dicts plus a
``canon_by_qid`` map of canonical EN forms for pairing; candidates that share
an identical ``(label_ru, label_en, description)`` signature (i.e. render
100% identically to the judge, see ``_format_judge_prompt`` in
``label_first.py``) are also deduped, keeping the first (owner fix,
2026-07-16 -- Wikinews items from CirrusSearch full-text reaching the
candidate list for "Египтяне", plus a hypothetical Paris FC men's/women's
near-duplicate pair). Deliberately requires the FULL signature, not just
label_ru: two distinct entities sharing a Russian label but differing in
label_en or description are exactly the homonym case G6's judge escalation
exists to disambiguate, and must never be silently collapsed to 1 candidate.
This dedup is deliberately narrower than the entity-*type*
filter D3/Q1 removed: that filter tried to guess which *kind* of entity
("city" vs "football club" vs "person") best fits, which is exactly the
judge's disambiguation job (spec 2026-07-03-grounding-label-first-design.md
D3/Q1) -- it is NOT reintroduced here. The items dropped by
``_NON_ENTITY_P31_BLOCKLIST`` are never a valid grounding target under ANY
context (a Wikinews *article*, a disambiguation *page* as a wiki-structure
object, not any particular sense it disambiguates between); keeping them out
is pure candidate-list noise removal, not a type-disambiguation heuristic.

``config.search_mode`` (wiki-eval experiment, 2026-07-10) cumulatively widens
rungs 1-4 above when they find nothing, entirely deterministic aside from the
optional "label-guess" tier:

  - ``"baseline"`` (default): exactly rungs 1-4, byte-identical to the
    pre-2026-07-10 behavior — a hard regression constraint, so every
    ``search_mode`` branch below is skipped entirely in this mode and
    candidate dicts never gain a ``"source"`` key.
  - ``"alt-names"``: when rungs 1-4 still found 0 hits, derive alternate
    surface forms from parenthesized alternates immediately following the
    mention in its sentence context (e.g. «Унку (Unqi)» → "Unqi"; also
    comma/«или»-separated alternates inside the parens) and re-run the same
    ``wbsearchentities`` prefix search per alternative form. Zero LLM calls.
  - ``"label-guess"``: alt-names PLUS, if still 0 hits, ONE call to the
    injected ``label_guesser`` (the run's judge LLM client, a different
    system prompt than disambiguation) asking it to guess the entity's exact
    Wikidata label; the guessed label(s) go through the same prefix search.

In both widening modes, every candidate dict gains a ``"source"`` key
(``"baseline"`` | ``"alt"`` | ``"label_guess"``) recording which tier first
surfaced its QID (dedup-by-QID: a QID already found at an earlier tier keeps
that tier's provenance).
"""
from __future__ import annotations

import re
from itertools import zip_longest

from ..base import FatalGroundingJudgeError, GroundingConfig, Judge, TermMention
from ..wikidata import (
    WikidataClient,
    aliases_of,
    canonical_en_forms,
    label_of,
)

# Enrichment head-cut for hits that came from a widening tier (alt-names /
# label-guess). Sized so that with the rank-wise interleave in ``_widen``
# every one of up to 5 query forms gets its top-2 hits enriched (5 forms x
# rank 2 = position 10); the baseline single-form path keeps the tighter
# ``config.enrich_top``.
_WIDEN_ENRICH_TOP = 10

# Role + strict-JSON output contract for the "label-guess" tier's one-shot
# call (spec: "guess the exact Wikidata label ... given {surface, lemma,
# sentence}"). Single source of truth here (not label_first.py's judge
# prompts, a genuinely different call) -- scripts/wiki_eval.py's
# _build_label_guesser imports DEFAULT_LABEL_GUESS_SYSTEM_PROMPT directly,
# same pattern as it already does for DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT.
DEFAULT_LABEL_GUESS_SYSTEM_PROMPT = """## Role
You are a Wikidata lookup assistant for a Russian-to-English historical
translation pipeline. A term could not be found by a direct Wikidata label
search. Given its Russian surface form, its lemma, and the sentence it
occurs in, guess the EXACT Wikidata item label the entity is most likely
filed under -- in Russian and/or English.

## Output
Return strict JSON only, no other text:
{"label_ru": "<exact label>" or null, "label_en": "<exact label>" or null,
 "variants": ["<alternative exact label>", ...] or []}

Guess a plausible EXACT Wikidata label string (e.g. a standard
transliteration or the common English name), never a description or
paraphrase. Use null for a language you cannot confidently guess.

In "variants" add up to 3 ALTERNATIVE exact-label spellings that Wikidata
might file the entity under instead: the scholarly (Library of Congress)
romanization of a Russian name when it differs from the common one (х->kh,
ц->ts, дж->j: «Хана» -> "Khana" as well as "Hana"), and the bare canonical
proper noun without generic type words («Ханейское царство» -> "Khana", not
"Khana kingdom"). Empty list if no distinct variant comes to mind.
"""

DEFAULT_LABEL_GUESS_USER_TEMPLATE = """Surface form: {surface}
Lemma: {lemma}
Sentence context: {context}
"""


def _description(entity: dict, lang: str = "en") -> str:
    return entity.get("descriptions", {}).get(lang, {}).get("value", "")


# Wikidata items that are wiki-maintenance structure, never a real-world
# grounding target under any context -- see the module docstring for why this
# is distinct from the removed D3/Q1 entity-type filter.
_NON_ENTITY_P31_BLOCKLIST = frozenset({
    "Q17633526",  # Wikinews article
    "Q4167410",   # Wikimedia disambiguation page
    "Q4167836",   # Wikimedia category
    "Q11266439",  # Wikimedia template
    "Q13406463",  # Wikimedia list article
})


def _p31_qids(entity: dict) -> set[str]:
    """QIDs from the entity's P31 (instance of) claims.

    Defensive against missing claims, a ``novalue``/``somevalue`` snak, or any
    other malformed shape -- never raises, just yields fewer/no QIDs.
    """
    out: set[str] = set()
    for stmt in entity.get("claims", {}).get("P31", []):
        try:
            out.add(stmt["mainsnak"]["datavalue"]["value"]["id"])
        except (KeyError, TypeError):
            continue
    return out


def _is_non_entity(entity: dict, description: str) -> bool:
    """True for a Wikidata "meta" item that must never reach exact-match/judge.

    P31 is the principled check -- ``claims`` is already in the props
    ``get_entities`` fetches for every candidate, so this costs zero extra
    network calls. Falls back to a description-text match for the single
    "Wikinews article" pattern only when the entity carries no P31 claim at
    all (the fallback case this module's docstring flags as acceptable).
    """
    p31 = _p31_qids(entity)
    if p31:
        return bool(p31 & _NON_ENTITY_P31_BLOCKLIST)
    return description.strip().lower() == "wikinews article"


# Splits a parenthesized alternates group on a comma or the RU conjunction
# «или» -- e.g. "Unqi, или Уна" -> ["Unqi", "Уна"]. "или" uses a word
# boundary (\b, zero-width) rather than requiring literal surrounding
# whitespace (\s+) -- a comma match may already have consumed the space
# adjacent to "или" (e.g. in "Unqi, или Уна" the ", " match eats the space
# right before "или"), which would otherwise leave "или" with nothing left
# to match on its own. The resulting adjacent empty split segment is
# filtered out below (``if p``).
_ALT_SPLIT_RE = re.compile(r"\s*,\s*|\s*\bили\b\s*", re.IGNORECASE)


def _alt_names_from_context(surface: str, context: str) -> list[str]:
    """Alternate surface forms from a parenthesized group immediately
    following ``surface`` in ``context`` (only whitespace may separate them,
    "immediately following" per spec) -- e.g. «Унку (Unqi)» -> ["Unqi"];
    comma/«или»-separated alternates inside the parens are all returned.
    The first such match in ``context`` wins if ``surface`` recurs."""
    if not surface or not context:
        return []
    m = re.search(re.escape(surface) + r"\s*\(([^)]*)\)", context)
    if not m:
        return []
    inner = m.group(1).strip()
    if not inner:
        return []
    return [p for p in (p.strip() for p in _ALT_SPLIT_RE.split(inner)) if p]


def _guess_labels(label_guesser: Judge, mention: TermMention) -> dict:
    """One label-guess call. Best-effort widening tier: any non-fatal
    failure (transient-exhausted, malformed JSON) degrades to "no guess"
    (``{}``) rather than killing the run -- mirrors how the disambiguation
    judge's own failures collapse to a terminal degraded state instead of
    propagating, except a ``FatalGroundingJudgeError`` halt marker (spec
    Р15: token-limit overflow, per-call gate violations) is never tolerated
    and re-raised unchanged."""
    prompt = DEFAULT_LABEL_GUESS_USER_TEMPLATE.format(
        surface=mention.surface, lemma=mention.lemma or mention.surface, context=mention.context,
    )
    try:
        response = label_guesser(prompt)
    except FatalGroundingJudgeError:
        raise
    except Exception:  # noqa: BLE001 -- best-effort widening tier, see docstring
        return {}
    return response if isinstance(response, dict) else {}


def generate_candidates(wd: WikidataClient, mention: TermMention,
                         config: GroundingConfig = GroundingConfig(), *,
                         label_guesser: Judge | None = None) -> dict:
    """Return ``{candidates, canon_by_qid, source, n_hits, queries}`` for a mention.

    ``candidates`` is a list of ``{qid, label_ru, label_en, description,
    aliases_ru, aliases_en}`` dicts in search-rank order, insertion-order
    deduplicated by QID (a documented determinism invariant — spec §3.1, not
    an implementation accident). In ``"alt-names"``/``"label-guess"`` mode
    each candidate also carries ``"source"`` (module docstring); baseline
    mode never adds that key, keeping it byte-for-byte identical to the
    pre-2026-07-10 wire shape (hard regression constraint).

    ``label_guesser`` (only consulted in ``"label-guess"`` mode, and only
    when the alt-names tier also found nothing) is the run's judge-configured
    LLM client for the one-shot label-guess call -- ``None`` simply skips
    that tier (the caller is responsible for failing fast up front when
    ``search_mode == "label-guess"`` but no judge is configured at all, see
    ``scripts/wiki_eval.py``'s CLI guard).
    """
    queries: list[dict] = []

    forms, seen_form = [], set()
    if config.use_lemma and mention.lemma and mention.lemma != mention.surface:
        forms.append(mention.lemma)
    if mention.surface not in forms:
        forms.append(mention.surface)
    forms = [f for f in forms if f and not (f in seen_form or seen_form.add(f))]

    hits, seen_qid = [], set()
    for q in forms:
        results = wd.search_entities(q, lang=mention.lang, limit=config.search_limit)
        queries.append({"q": q, "kind": "lemma" if q == mention.lemma else "surface",
                         "mechanism": "wbsearchentities", "strategy": "prefix",
                         "n_hits": len(results)})
        for h in results:
            if h["id"] not in seen_qid:
                seen_qid.add(h["id"])
                hits.append(h)

    source = "wbsearchentities" if hits else "none"
    if not hits and config.use_cirrus:  # prefix search missed entirely → full-text CirrusSearch recovers inflected/rare terms
        for q in forms:
            results = wd.search_cirrus(q, limit=config.search_limit)
            queries.append({"q": q, "kind": "lemma" if q == mention.lemma else "surface",
                             "mechanism": "cirrus", "strategy": "cirrus",
                             "n_hits": len(results)})
            for h in results:
                if h["id"] not in seen_qid:
                    seen_qid.add(h["id"])
                    hits.append(h)
        if hits:
            source = "cirrus"
    if not hits and config.use_sitelink:  # last resort: RU Wikipedia page → Wikidata item
        wiki_title = mention.lemma or mention.surface
        qid = wd.wikipedia_wikibase_item(wiki_title, lang=mention.lang)
        queries.append({"q": wiki_title,
                         "kind": "lemma" if wiki_title == mention.lemma else "surface",
                         "mechanism": "wikipedia_wikibase_item", "strategy": "sitelink",
                         "n_hits": 1 if qid else 0})
        if qid:
            hits, source = [{"id": qid}], "wikipedia_langlink"

    # hit_tier tracks provenance for the widening tiers below -- untouched
    # (stays empty) in baseline mode or whenever rungs 1-4 already found
    # something, so candidates from those paths never get a "source" key.
    hit_tier: dict[str, str] = {}

    empty_result = {"candidates": [], "canon_by_qid": {}, "source": "none", "n_hits": 0, "queries": queries}

    if not hits:
        if config.search_mode == "baseline":
            return empty_result

        def _widen(q_list: list[str], tier: str) -> None:
            _search_interleaved(wd, mention, config, q_list, tier,
                                queries=queries, seen_qid=seen_qid,
                                hits=hits, hit_tier=hit_tier)

        alt_forms = _alt_names_from_context(mention.surface, mention.context)
        if alt_forms:
            _widen(alt_forms, "alt")

        if not hits and config.search_mode == "label-guess" and label_guesser is not None:
            guess = _guess_labels(label_guesser, mention)
            guess_forms = _guess_forms(guess)
            if guess_forms:
                _widen(guess_forms, "label_guess")

        if not hits:
            return empty_result
        source = "alt" if any(t == "alt" for t in hit_tier.values()) else "label_guess"

    # Widened hits interleave several query forms (up to 5 at the label-guess
    # tier), so config.enrich_top=5 -- sized for the single-form baseline --
    # would re-truncate the interleave: 3 productive forms reach rank 2 only
    # at position 6. One wbgetentities call batches all ids anyway, and the
    # non-entity / near-dup filters below prune before the judge sees them.
    enrich_top = _WIDEN_ENRICH_TOP if hit_tier else config.enrich_top
    qids = [h["id"] for h in hits[:enrich_top]]
    candidates, canon_by_qid = _enrich_candidates(wd, config, qids, hit_tier)
    return {"candidates": candidates, "canon_by_qid": canon_by_qid,
            "source": source, "n_hits": len(hits), "queries": queries}


def _search_interleaved(wd: WikidataClient, mention: TermMention, config: GroundingConfig,
                        q_list: list[str], tier: str, *, queries: list[dict],
                        seen_qid: set[str], hits: list[dict], hit_tier: dict[str, str]) -> None:
    """Prefix-search each widening form and merge the results fairly.

    Both widening tiers ("alt"/"label_guess") hit the same wbsearchentities
    prefix-search backend as rung 1, just with a derived form instead of
    surface/lemma. "alt" keeps ``strategy: "prefix"`` (zero-LLM, already
    distinguishable via "kind"); "label_guess" gets its own ``"guess"``
    strategy so a trace UI can flag an LLM-guessed query distinctly at a
    glance (live-pipeline wiring, owner-approved 2026-07-17).

    Results are rank-wise interleaved across forms, NOT appended form-by-form:
    a junk-rich first form would otherwise starve a later one under the
    ``hits[:enrich_top]`` head-cut -- prod 2026-07-17: «Хана»'s 7 hits (given
    name, Hawaii CDP, football club...) filled the head while "Khana" rank 2
    = Q425405 (Kingdom of Hana, the right entity) never reached enrichment or
    the judge. ``zip_longest`` keeps each form's own ranking while giving
    every form a fair slot per rank.
    """
    per_form: list[list[dict]] = []
    for q in q_list:
        if not q:
            continue
        results = wd.search_entities(q, lang=mention.lang, limit=config.search_limit)
        strategy = "guess" if tier == "label_guess" else "prefix"
        queries.append({"q": q, "kind": tier, "mechanism": "wbsearchentities",
                         "strategy": strategy, "n_hits": len(results)})
        per_form.append(results)
    for rank_slice in zip_longest(*per_form):
        for h in rank_slice:
            if h is not None and h["id"] not in seen_qid:
                seen_qid.add(h["id"])
                hits.append(h)
                hit_tier[h["id"]] = tier


def _guess_forms(guess: dict) -> list[str]:
    """label_ru/label_en plus up to 3 "variants" (scholarly LoC romanization,
    bare canonical noun -- 2026-07-17: «Ханейское царство» guessed
    "Хана"/"Hana" but Q425405 is only reachable via the "Khana" spelling).
    Dedup preserves guess order; the cap keeps the widening tier bounded at
    5 prefix searches."""
    raw_variants = guess.get("variants")
    variants = [v for v in raw_variants if isinstance(v, str)] if isinstance(raw_variants, list) else []
    seen: set[str] = set()
    return [
        g for g in (guess.get("label_ru"), guess.get("label_en"), *variants)
        if g and not (g in seen or seen.add(g))
    ][:5]


def _enrich_candidates(wd: WikidataClient, config: GroundingConfig, qids: list[str],
                       hit_tier: dict[str, str]) -> tuple[list[dict], dict[str, list[str]]]:
    entities = wd.get_entities(qids)
    candidates: list[dict] = []
    canon_by_qid: dict[str, list[str]] = {}
    seen_dedup_keys: set[tuple[str, str]] = set()
    for qid in qids:
        ent = entities.get(qid)
        if not ent:
            continue
        cqid = ent.get("id", qid)  # canonicalise redirects to the target QID
        description = _description(ent, "en") or _description(ent, "ru")
        if _is_non_entity(ent, description):
            continue
        label_ru = label_of(ent, "ru")
        label_en = label_of(ent, "en")
        # Near-duplicate noise (e.g. two clubs/pages that render identically
        # to the judge): dedup only when the FULL displayed signature
        # matches -- label_ru AND label_en AND a real (non-empty)
        # description, not just label_ru+description. Two distinct entities
        # that legitimately share a Russian label (the exact ">=2 exact
        # matches" homonym case G6's judge escalation exists for, e.g. two
        # rulers of the same name) routinely differ only in label_en, or
        # carry no description at all in some data paths -- a looser key
        # silently collapsed that genuine disambiguation case down to 1
        # candidate before the judge ever saw it, caught by this module's own
        # test suite (test_label_first_two_exact_matches_escalates_to_judge_*
        # and the live-pipeline equivalent in test_terminology_live.py, whose
        # fixture gives every entity the same placeholder description).
        # Requiring a non-empty description also means "nothing to compare
        # on" (both descriptions blank) never counts as a match.
        dedup_key = (label_ru, label_en, description) if description and (label_ru or label_en) else None
        if dedup_key is not None:
            if dedup_key in seen_dedup_keys:
                continue
            seen_dedup_keys.add(dedup_key)
        candidate = {
            "qid": cqid,
            "label_ru": label_ru,
            "label_en": label_en,
            "description": description,
            "aliases_ru": aliases_of(ent, "ru"),
            "aliases_en": aliases_of(ent, "en"),
        }
        if config.search_mode != "baseline":
            candidate["source"] = hit_tier.get(qid, "baseline")
        candidates.append(candidate)
        canon_by_qid[cqid] = canonical_en_forms(ent)
    return candidates, canon_by_qid


def escalate_label_guess(wd: WikidataClient, mention: TermMention, config: GroundingConfig,
                         label_guesser: Judge, *, exclude_qids: set[str]) -> dict:
    """One post-rejection widening round (called by ``label_first.py``,
    2026-07-17): the deterministic rungs DID find candidates, so the zero-hit
    gate above never fired -- but the judge then rejected them all ("wrong
    hits" look identical to "good hits" until the judge sees them; prod case:
    «Хана» finds 7 entities, none of them the Bronze-age kingdom). Guess
    labels and search them exactly like the pre-judge label_guess tier,
    excluding the already-rejected QIDs. The caller re-judges ONLY the new
    candidates -- never the deterministic exact-label green path: a fresh
    exact match inside a homonym set the judge just vetoed must not
    auto-green (false-green is the worst error class).

    Returns ``{"candidates", "canon_by_qid", "queries"}``; empty candidates
    when the guess finds nothing new. Transport failures raise like
    ``generate_candidates`` (the caller keeps the honest rejection); tolerable
    guesser-LLM failures yield ``{}`` from ``_guess_labels`` and therefore no
    candidates; ``FatalGroundingJudgeError`` propagates.
    """
    queries: list[dict] = []
    guess = _guess_labels(label_guesser, mention)
    forms = _guess_forms(guess)
    hits: list[dict] = []
    hit_tier: dict[str, str] = {}
    seen_qid = set(exclude_qids)
    if forms:
        _search_interleaved(wd, mention, config, forms, "label_guess",
                            queries=queries, seen_qid=seen_qid,
                            hits=hits, hit_tier=hit_tier)
    qids = [h["id"] for h in hits[:_WIDEN_ENRICH_TOP]]
    candidates, canon_by_qid = _enrich_candidates(wd, config, qids, hit_tier)
    return {"candidates": candidates, "canon_by_qid": canon_by_qid, "queries": queries}
