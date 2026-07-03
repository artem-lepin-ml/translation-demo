# Stage 4 — Atomic-fact extraction and verification

Extract every atomic factual claim made in the English translation. For each, verify it against the **Russian source only** — do not draw on external knowledge.

Return JSON lines, one object per fact:

```
{"claim": "...", "source_span_ru": "...", "status": "supported|contradicted|unsupported", "note": "..."}
```

- `supported` — the RU source entails the claim.
- `contradicted` — the RU source entails the negation of the claim.
- `unsupported` — the RU source neither entails nor contradicts it (e.g. the translation added something).

The `note` is a short justification. Do not include any prose outside the JSON lines.
