# Glossary

Single source of truth for RU→EN terminology.

- `main.json` — project-wide merged glossary (hand-curated + auto-written by stage 2/3).
- Per-chapter glossaries live at `data/processed/vol{NN}/ch{NN}/glossary.json` and feed into `main.json` during merge.

## Entry schema

```json
{
  "лугаль": {
    "ru": "лугаль",
    "en": "lugal",
    "strategy": "transcription",
    "source": "wikipedia:Lugal",
    "notes": "Crawford 2004; Van De Mieroop 2016."
  }
}
```

`strategy ∈ {transcription, description, transcription+description, unresolved}`.
