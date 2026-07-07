#!/usr/bin/env python3
"""Correct the ``lemma`` field of the demo seed mentions to the Russian nominative.

The seed mentions (``data/seed/terminology_terms.jsonl``) carry ``lemma ==
surface`` for every entry — the inflected form, not the nominative lemma the
grounding pipeline's documented invariant expects (docs/stages/terminology.md:
"grounding searches the nominative lemma before the surface"). Because Russian
is heavily inflected, ``wbsearchentities`` on a genitive/dative/prepositional
surface (``Месопотамии``, ``Евфрата``, ``Вавилоне``) misses the entity that the
nominative (``Месопотамия``, ``Евфрат``, ``Вавилон``) finds as the top hit — so
every inflected occurrence of the demo's core entities falls through to a
judge rejection (red) even though the entity is trivially groundable. This is a
data bug in the seed, not a pipeline bug: the nominative occurrences ground
fine.

This pass corrects ONLY the ``lemma`` field, in place, preserving every other
field (surface, spans, context, category) so the mention set — and therefore
the demo's char-offset highlights — is unchanged. Source of the nominative,
in priority order per unique surface:

  1. ``data/seed/lemmas.json`` — the hand-curated surface->lemma map (trusted;
     non-``null`` entries win).
  2. an LLM lemmatizer pass (same CloseRouter provider selection as the eval
     harness / ``rebuild_demo.py``) for the surfaces ``lemmas.json`` doesn't
     cover — handles multi-word agreement (``Нижней Месопотамии`` ->
     ``Нижняя Месопотамия``) a single-word map can't.

Without ``OPENROUTER_API_KEY`` the LLM step is skipped and only the
``lemmas.json`` corrections are applied (the rest keep ``lemma = surface``,
i.e. no worse than before). Re-runnable: it recomputes from the current file
each time.

Run: ``uv run python scripts/fix_mention_lemmas.py`` then re-run
``scripts/rebuild_demo.py``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MENTIONS = ROOT / "data/seed/terminology_terms.jsonl"
LEMMAS = ROOT / "data/seed/lemmas.json"
ENV_CANDIDATES = (
    ROOT / ".env",
    Path("/Users/a1111/Projects/Work/translation-demo/.env"),
    Path("/Users/a1111/Projects/Work/gse-translation/.env"),
)

LEMMA_SYSTEM = "You are a Russian lemmatizer. Return strict JSON only."
LEMMA_PROMPT = """Given a Russian term as it appears in text (possibly inflected,
possibly multi-word) and its sentence, return the term's DICTIONARY NOMINATIVE
form — the form a Wikidata/Wikipedia entity would carry.

Rules:
- Single word: nominative singular (an adjective agrees with its head noun).
- Multi-word: the whole phrase in agreed nominative
  (e.g. "Нижней Месопотамии" -> "Нижняя Месопотамия",
   "III династии Ура" -> "III династия Ура").
- Do NOT translate and do NOT change the entity; keep it Russian.
- Preserve proper-noun capitalization.

Return strict JSON only: {{"lemma": "<nominative form>"}}

Term: {surface}
Sentence: {context}
"""


def _load_dotenv(paths: tuple[Path, ...] = ENV_CANDIDATES) -> None:
    """Manual .env parser -> os.environ. Never prints/logs the value."""
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value
        return


def _build_lemmatizer():
    """Return ``(lemmatize_callable, stats)`` or ``(None, None)`` if no key.

    ``lemmatize_callable(surface, context) -> str`` returns the nominative
    lemma (or the surface unchanged on any parse/network failure — a wrong
    lemma is worse than the surface, which at least still runs surface search).
    """
    _load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None, None

    model = os.environ.get("CLOSEROUTER_MODEL", "google/gemini-3.1-flash-lite")
    provider = os.environ.get("CLOSEROUTER_PROVIDER", "provider-9")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://api.closerouter.dev/v1")

    from palimpsest.llm.client import LLMClient, LLMConfig

    client = LLMClient(
        LLMConfig(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=0,
            max_tokens=64,
            extra_body={"provider": provider},
        )
    )
    stats = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

    def lemmatize(surface: str, context: str) -> str:
        res = client.complete_retrying(
            system=LEMMA_SYSTEM,
            user=LEMMA_PROMPT.format(surface=surface, context=context or surface),
        )
        stats["calls"] += 1
        u = res.usage
        stats["prompt_tokens"] += u.prompt_tokens
        stats["completion_tokens"] += u.completion_tokens
        stats["cost_usd"] += u.cost_usd or 0.0
        text = res.content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            lemma = json.loads(text).get("lemma")
        except Exception:
            return surface
        return lemma.strip() if isinstance(lemma, str) and lemma.strip() else surface

    return lemmatize, stats


def main() -> int:
    lines = MENTIONS.read_text("utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    lemmas_map = json.loads(LEMMAS.read_text("utf-8")) if LEMMAS.exists() else {}

    # One representative context per unique surface (first occurrence).
    surfaces: dict[str, str] = {}
    for r in rows:
        surfaces.setdefault(r["surface"], r.get("context", ""))

    lemmatize, stats = _build_lemmatizer()

    resolved: dict[str, str] = {}
    n_from_map = n_from_llm = n_kept = 0
    for i, (surface, context) in enumerate(surfaces.items(), 1):
        mapped = lemmas_map.get(surface)
        if mapped:  # trusted hand-curated nominative
            resolved[surface] = mapped
            n_from_map += 1
        elif lemmatize is not None:
            lemma = lemmatize(surface, context)
            resolved[surface] = lemma
            if lemma != surface:
                n_from_llm += 1
            else:
                n_kept += 1
            if i % 25 == 0 or i == len(surfaces):
                print(f"  lemmatized {i}/{len(surfaces)} ({stats['calls']} live calls)")
        else:
            resolved[surface] = surface
            n_kept += 1

    changed = 0
    for r in rows:
        new_lemma = resolved.get(r["surface"], r["surface"])
        if new_lemma != r.get("lemma"):
            changed += 1
        r["lemma"] = new_lemma

    MENTIONS.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")

    print(
        f"corrected lemmas: {changed} of {len(rows)} mention rows ({len(surfaces)} unique surfaces)"
    )
    print(
        f"  from lemmas.json: {n_from_map} unique · from LLM: {n_from_llm} unique "
        f"(corrections) · kept-as-surface: {n_kept} unique"
    )
    if stats is not None:
        print(
            f"  live lemmatizer calls: {stats['calls']} "
            f"(prompt {stats['prompt_tokens']} + completion "
            f"{stats['completion_tokens']} tokens, ${stats['cost_usd']:.4f})"
        )
    else:
        print("  no OPENROUTER_API_KEY — LLM step skipped (lemmas.json corrections only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
