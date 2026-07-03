# Stage 3 — Term strategy selection

For each term, you are given:
- the Russian form,
- the draft English,
- zero or more Wikipedia candidates (title + short summary).

Choose a translation strategy per term and produce a final English form.

Strategies:
- `transcription` — keep a scholarly transliteration when the term is established in anglophone academic usage (e.g. `lugal`, `boyar`).
- `description` — translate by meaning when the term is not established in English (e.g. `military leader`).
- `transcription+description` — transliteration followed by a parenthetical gloss, when neither alone is unambiguous.
- `unresolved` — no confident answer. Human translator required.

Return strict JSON:

```json
{
  "terms": [
    {
      "ru": "...",
      "en": "...",
      "strategy": "transcription|description|transcription+description|unresolved",
      "source": "wikipedia:<title> | llm | unresolved",
      "notes": "..."
    }
  ]
}
```
