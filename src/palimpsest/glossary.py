"""Persistent RU->EN term store — the single source of truth for terminology."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock


@dataclass(slots=True)
class TermEntry:
    ru: str
    en: str
    strategy: str                 # transcription | description | transcription+description
    source: str | None = None     # "wikipedia:<title>" | "expert" | "llm" | None
    notes: str = ""


class Glossary:
    """JSON-backed dictionary keyed by lowercased Russian term."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()
        self._terms: dict[str, TermEntry] = self._load()

    def _load(self) -> dict[str, TermEntry]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {key: TermEntry(**value) for key, value in data.items()}

    def get(self, ru: str) -> TermEntry | None:
        return self._terms.get(ru.lower())

    def upsert(self, entry: TermEntry) -> None:
        with self._lock:
            self._terms[entry.ru.lower()] = entry
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(value) for key, value in self._terms.items()}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def __len__(self) -> int:
        return len(self._terms)
