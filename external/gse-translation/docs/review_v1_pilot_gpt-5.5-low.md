# Вычитка оценок gpt-5.5-low (v1, 2 пилотные оценки)

Привет, Андрей! Это инструкция как открыть оценки. Ветка ещё не смержена — заберите её отдельно.

## 1. Забрать ветку

```bash
git clone ssh://git@gitlab.frontierai.ru:8022/frontierai/teams/research/history-translation/ru2en-enciclopedia-translation.git
cd ru2en-enciclopedia-translation
git checkout feat/usage-and-gpt-5.5-low-pilot
```

Внимание: репозиторий тянет через **Git LFS** примерно **~150 МБ** review-файлов (12 JSONL по 12-13 МБ). Перед клоном убедитесь, что LFS установлен:

```bash
# macOS
brew install git-lfs && git lfs install   # один раз на машине

# Linux (apt)
sudo apt install git-lfs && git lfs install

# Windows: Git for Windows обычно уже включает git-lfs (галочка в установщике).
#   Тогда достаточно одной команды:
#     git lfs install
#   Если не установлен — любой из вариантов:
#     winget install GitHub.GitLFS
#     choco install git-lfs
#   или скачать инсталлятор с https://git-lfs.com и запустить.
#   После установки — git lfs install
```

Если уже клонировали без LFS — `git lfs pull` после checkout.

## 2. Где лежат файлы

Под каждой трансляцией — по 6 JSONL-файлов в подкаталоге `review/`:

**Qwen (отредактированный, пар-за-пар):**
- [data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_paragraph.jsonl](data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_paragraph.jsonl) — в порядке следования абзацев (0 → 548)
- [by_accuracy_desc.jsonl](data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_accuracy_desc.jsonl) — по убыванию accuracy
- [by_cultural_desc.jsonl](data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_cultural_desc.jsonl) — по убыванию cultural
- [by_fluency_desc.jsonl](data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_fluency_desc.jsonl) — по убыванию fluency
- [by_style_desc.jsonl](data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_style_desc.jsonl) — по убыванию style
- [by_terminology_desc.jsonl](data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_terminology_desc.jsonl) — по убыванию terminology

**Claude Opus 4.7 (пар-за-пар):**
- [data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/gpt-5.5-low/review/by_paragraph.jsonl](data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/gpt-5.5-low/review/by_paragraph.jsonl)
- [by_accuracy_desc.jsonl](data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/gpt-5.5-low/review/by_accuracy_desc.jsonl)
- [by_cultural_desc.jsonl](data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/gpt-5.5-low/review/by_cultural_desc.jsonl)
- [by_fluency_desc.jsonl](data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/gpt-5.5-low/review/by_fluency_desc.jsonl)
- [by_style_desc.jsonl](data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/gpt-5.5-low/review/by_style_desc.jsonl)
- [by_terminology_desc.jsonl](data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/gpt-5.5-low/review/by_terminology_desc.jsonl)

Внизу каждой `*_desc.jsonl` лежат абзацы без скора (маркеры `* * *` / `picture`, провалы перевода — всего 7 штук на run).

## 3. Что в одной строке JSONL

Каждая строка — один абзац. Поля:

```json
{
  "id": 386,
  "source": "<русский исходник>",
  "translated": "<английский перевод>",
  "scores": {"accuracy": 9, "cultural": 8, "fluency": 9, "style": 7, "terminology": 9},
  "criteria": {
    "accuracy":    {"score": 9, "llm_report": {...}, "usage": {...}},
    "cultural":    {"score": 8, "llm_report": {...}, "usage": {...}},
    "fluency":     {"score": 9, "llm_report": {...}, "usage": {...}},
    "style":       {"score": 7, "llm_report": {...}, "usage": {...}},
    "terminology": {"score": 9, "llm_report": {...}, "usage": {...}}
  }
}
```

В `criteria.<crit>.llm_report` — полный отчёт судьи: `identified_issues` (что не так в переводе), `criteria_assessment` (разбор по подкритериям), `summary`, `final_score`.

## 4. Как читать

JSONL = одна JSON-строка на абзац. Удобные варианты:

- **VS Code**: открыть файл, поставить расширение `jsonl` или просто читать как длинные строки.
- **CLI (`jq`)**:
  ```bash
  # первый абзац целиком, красиво
  head -1 data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_accuracy_desc.jsonl | jq .

  # пройти по всем, печатая только id + перевод + summary accuracy
  jq -r '"\(.id)\t\(.scores.accuracy)\t\(.criteria.accuracy.llm_report.summary)"' \
    data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_accuracy_desc.jsonl | head -20
  ```
- **Python**:
  ```python
  import json
  with open("data/pilot/evaluation/qwen_edited_par_by_par/v1/gpt-5.5-low/review/by_accuracy_desc.jsonl") as f:
      for line in f:
          row = json.loads(line)
          print(row["id"], row["scores"], row["criteria"]["accuracy"]["llm_report"]["summary"])
  ```
