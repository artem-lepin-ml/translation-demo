"""Per-criterion LLM-as-judge for the demo (rev-4 contract §2 /evaluate).

Unlike the scaffold's monolithic ``LLMJudge`` (all six criteria, one prompt,
flat scores), this scores ONE configurable criterion and emits Grammarly-style
issues with a span, an explanation and a suggested fix.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ..llm.client import LLMClient
from .. import paths

# Severity is derived from the explanation text (the v2 judge prompts label
# severity implicitly in prose). Same rule as the seed derivation.
_MAJOR = ("incorrect", "wrong", "mistranslat", "error", "missing", "omit", "distort", "confus")


def derive_severity(explanation: str) -> str:
    low = (explanation or "").lower()
    return "major" if any(k in low for k in _MAJOR) else "minor"


# advice-text guard (spec 2026-07-02-suggestion-guard).
# A `suggestion` must be a drop-in replacement, not advice. These heuristics flag
# advice so _issue_from / seed can empty it (moving the text to explanation).
# ru->en completeness via the English advisory lexicon; other pairs rely on the
# language-agnostic STRUCTURAL signals only.
_ADVICE_START = re.compile(
    r"^\s*(consider|use|retain|prefer|keep|avoid|note|try|opt for|replace|perhaps)\b",
    re.IGNORECASE,
)
_ADVICE_META = re.compile(
    r"\b(the translation|if needed|if context requires|which is the standard|"
    r"gloss|you (?:could|might|may)|would be better|instead of)\b",
    re.IGNORECASE,
)
_QUOTES = "'\"‘’“”"
# Structural (language-agnostic): a quoted alternative offered via '...'/'...' or
# '...' or '...' - i.e. two quoted spans separated by a slash or the word "or".
_QUOTED_ALT = re.compile(
    rf"[{_QUOTES}][^{_QUOTES}]+[{_QUOTES}]\s*(?:/|\bor\b)\s*[{_QUOTES}]"
)


def looks_like_advice(suggestion: str) -> bool:
    """True if `suggestion` reads as advice rather than a drop-in replacement.

    English lexicon (advisory starts + meta markers) gives ru->en completeness;
    the quoted-alternative structural signal is language-agnostic.
    """
    s = (suggestion or "").strip()
    if not s:
        return False
    if _ADVICE_START.match(s) or _ADVICE_META.search(s):
        return True
    if _QUOTED_ALT.search(s):
        return True
    return False


def sanitize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Idempotently move an advice `suggestion` into `explanation` (as ``Advice: ...``)
    and empty the field, so downstream apply-edit refuses it (422 no_suggestion) and
    the UI hides Accept. No-op on honest suggestions and on already-sanitized dicts.
    """
    raw = issue.get("suggestion")
    if not isinstance(raw, str):
        raw = "" if raw is None else str(raw)
        issue["suggestion"] = raw
    sug = raw.strip()
    if not sug or not looks_like_advice(sug):
        return issue
    expl = (issue.get("explanation") or "").rstrip()
    advice = f"Advice: {sug}"
    if advice not in expl:
        expl = f"{expl}\n{advice}".strip() if expl else advice
    issue["explanation"] = expl
    issue["suggestion"] = ""
    return issue


def _parse_json(raw: str) -> dict:
    """Tolerant parse: strip ```json fences, drop trailing commas, else grab the outermost {...}."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


LANG_NAMES = {"ru": "Russian", "en": "English", "de": "German", "fr": "French",
              "es": "Spanish", "it": "Italian", "pt": "Portuguese", "pl": "Polish",
              "uk": "Ukrainian", "zh": "Chinese", "ja": "Japanese", "ar": "Arabic"}


def lang_name(lang: str) -> str:
    """ISO code -> full name; free-text language names pass through as typed."""
    lang = lang.strip()
    return LANG_NAMES.get(lang.lower(), lang)


def _scoring_prompt(criterion_id: str) -> str:
    return (paths.PROMPTS / "scoring" / f"{criterion_id}.md").read_text(encoding="utf-8")


_SUGGESTION_CONTRACT = (
    "SUGGESTION FIELD CONTRACT. The `suggestion` field is a drop-in replacement "
    "for `problematic_fragment`, written in the target language, that can be pasted "
    "verbatim in place of the flagged text. It is NOT advice. Do not write meta or "
    "advisory phrasing (\"Consider ...\", \"Use 'X' ...\", \"if needed\", \"if context "
    "requires\", \"which is the standard ...\", \"add a gloss\"). If you have no single "
    "concrete replacement, set `suggestion` to an empty string and put the advice in "
    "`explanation` instead.\n\n"
)


def scoring_system_prompt(criterion_id: str, source_lang: str = "ru", target_lang: str = "en") -> str:
    src, tgt = lang_name(source_lang), lang_name(target_lang)
    preamble = f"You are evaluating a translation from {src} into {tgt}.\n\n"
    if (src.lower(), tgt.lower()) != ("russian", "english"):
        preamble += (
            f"This rubric was written for Russian→English. Read every mention of Russian "
            f"as {src} (the source language) and every mention of English as {tgt} (the "
            f"target language). Ignore Cyrillic-specific transliteration rules when the "
            f"source is not Russian.\n\n"
        )
    return preamble + _SUGGESTION_CONTRACT + _scoring_prompt(criterion_id)


def judge_one(client: LLMClient, criterion_id: str, source: str, target: str, *,
              source_lang: str = "ru", target_lang: str = "en") -> dict[str, Any]:
    """Score (source, target) on one criterion. Returns {value, summary, issues, usage}.

    ``issues`` items use the rev-4 wire shape (camelCase):
    {targetFragment, sourceFragment, explanation, suggestion, severity, mqmCategory}.
    """
    system = scoring_system_prompt(criterion_id, source_lang, target_lang)
    user = (f"[SOURCE — {lang_name(source_lang)}]\n{source}\n\n"
            f"[TRANSLATION — {lang_name(target_lang)}]\n{target}")
    result = client.complete(system, user)          # per-model temperature decided upstream
    data = _parse_json(result.content)
    issues = [_issue_from(it) for it in (data.get("identified_issues") or [])]
    return {
        "value": float(data["final_score"]),
        "summary": data.get("summary", ""),
        "issues": issues,
        "usage": result.usage,
    }


def _issue_from(it: Mapping[str, Any]) -> dict[str, Any]:
    explanation = it.get("explanation", "")
    issue = {
        "targetFragment": it.get("problematic_fragment", ""),
        "sourceFragment": it.get("source_fragment", ""),
        "explanation": explanation,
        # `or`-fallback is permanent, not a transitional shim: historical DB
        # payloads generated by the old fluency.md prompt used
        # `suggested_improvement` instead of `suggestion` and remain live.
        "suggestion": it.get("suggestion") or it.get("suggested_improvement", ""),
        "severity": derive_severity(explanation),
        "mqmCategory": None,
    }
    return sanitize_issue(issue)
