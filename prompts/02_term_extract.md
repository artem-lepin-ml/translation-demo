# Stage 2 — Terminology extraction

Given a Russian source paragraph and its academic English draft, extract all specialised terms that require authoritative translation.

Extract:
- Technical / domain terms (historical titles, political concepts, scientific units).
- Proper names of people, places, works, institutions.
- Transliterated-only items the draft left in square brackets.

Skip general academic vocabulary ("century", "empire", "society").

Return strict JSON — no prose:

```json
{
  "terms": [
    {
      "ru": "...",
      "draft_en": "...",
      "kind": "historical|geographical|scientific|literary|institutional|person|work",
      "notes": "why this needs verification"
    }
  ]
}
```
