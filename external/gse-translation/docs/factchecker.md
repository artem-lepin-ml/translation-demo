# Factcheck (Stage 03 critic)

**Содержит что-то полезное, но не факт, что полностью актуально**

Operational guide for the factcheck critic of [Stage 03 — Scoring](stages/03_scoring.md). Pipeline overview in [pipeline.md](pipeline.md).

Two-sided atomic-fact overlap check over a translated chunk: extract RU facts and EN facts independently, then measure semantic overlap with a single-call judge. Outputs precision / recall / F1 plus unmatched lists on each side.

See `docs/data_layout.md` for the surrounding data model.

## Input contract

**Granularity: one paragraph.** Stage 03 operates per paragraph id (0-indexed line number in `data/pilot/pilot_original.md`). One paragraph in, one JSONL row out.

**Inputs read per paragraph:**

| What | Where | Shape |
|---|---|---|
| RU source paragraph | `data/pilot/pilot_original.md`, line at index id | plain UTF-8 Russian, single paragraph (no inner newlines) |
| EN translation | `data/pilot/translating/<run_name>/translation.md`, line at index id | plain UTF-8 English, single paragraph (no inner newlines) |

**What Stage 02 must produce for this to work:**

- `data/pilot/translating/<run_name>/translation.md` — line-aligned with `pilot_original.md`. Same line count, no blank lines.
- UTF-8, one paragraph per line, no HTML envelope.

**What Stage 4 writes:**

- `data/pilot/evaluation/<run_name>/factcheck/factcheck_scores.jsonl` — one row per paragraph, schema `{id, source, translated, score (=F1 ∈ [0..1]), precision, recall, matches, unmatched_ru, unmatched_en, llm_report (P=… R=… F1=… |RU|=N |EN|=M)}`. See [stages/03_scoring.md](stages/03_scoring.md) for the cross-critic schema and `src/palimpsest/factcheck/__init__.py` for the implementation classes.

**What Stage 4 does NOT touch:**

- Chunking JSONs — factcheck reads source and translation directly by line index; it does not consume `data/pilot/chunking/` artifacts.
- Glossary — factcheck is term-agnostic; term consistency is Stage 3's job.

**Smoke-test mode (`scripts/03_factcheck.py`).** Takes two raw markdown files (`<ru_md> <en_md>`) — useful for manual experiments outside the pipeline. The pipeline wiring lives in `palimpsest.scoring._score_factcheck_for_run`: per-paragraph iteration, idempotent JSONL append at `data/pilot/evaluation/<run_name>/factcheck/factcheck_scores.jsonl`, plus `meta.json` snapshot of the factcheck judge.

## Smoke-test run (server)

### 1. Клонировать и поставить зависимости

```bash
git clone <repo-url> gse-translation
cd gse-translation
uv sync
cp .env.example .env
set -a && source .env && set +a
```

`.env.example` уже содержит `VLLM_API_KEY=dummy` — ничего больше трогать не нужно, если ты на vLLM.

### 2. Поднять vLLM

В `tmux`-сессии:

```bash
python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-4B-Thinking-2507 \
    --reasoning-parser deepseek_r1 \
    --dtype bfloat16 \
    --data-parallel-size 1 \
    --max-num-batched-tokens 32768 \
    --max-model-len 32768 \
    --max-num-seqs 1024 \
    --gpu-memory-utilization 0.90
```

**Важно:** флаг `--reasoning-parser deepseek_r1` обязателен для Qwen3-Thinking — без него `<think>…</think>` попадёт в ответ и фактчек упадёт на парсинге JSON.

Проверь, что сервер ожил:
```bash
curl http://localhost:8000/v1/models
```

### 3. Прописать модель в конфиге

[../configs/models.yaml](../configs/models.yaml) — добавить запись:

```yaml
models:
  qwen3-4b-thinking:
    name: Qwen/Qwen3-4B-Thinking-2507
    base_url: http://localhost:8000/v1
    api_key_env: VLLM_API_KEY
    temperature: 0.0
    max_tokens: 4096
```

[../configs/factcheck.yaml](../configs/factcheck.yaml) — указать ключ модели:

```yaml
extractor_model: qwen3-4b-thinking
judge_model: qwen3-4b-thinking
extraction_temperature: 0.0
judge_temperature: 0.0
few_shot_k: 3
```

### 4. Тестовые пары RU/EN

Для smoke-теста в репо лежат три готовые пары под [../tests/smoke/factcheck/](../tests/smoke/factcheck/):

| Сценарий | Файлы | Что проверяет |
| --- | --- | --- |
| (a) идентичный | `identical_{ru,en}.md` | расширяемые границы парсинга: recall ≈ 1.0, precision ≈ 1.0 |
| (b) урезанный | `truncated_{ru,en}.md` | пропуск фактов в EN: recall падает, precision высокий |
| (c) галлюцинация | `halluc_{ru,en}.md` | лишний факт в EN: precision падает, recall высокий |

### 5. Запустить фактчек

```bash
mkdir -p /tmp/fc
```

# (a) идентичный
```bash
uv run python scripts/05_factcheck.py \
    tests/smoke/factcheck/identical_ru.md tests/smoke/factcheck/identical_en.md \
    --output tests/reports/factcheck/out_identical.json
```

# (b) урезанный
```bash
uv run python scripts/05_factcheck.py \
    tests/smoke/factcheck/truncated_ru.md tests/smoke/factcheck/truncated_en.md \
    --output tests/reports/factcheck/out_tranated.json
```

# (c) с галлюцинацией
```bash
uv run python scripts/05_factcheck.py \
    tests/smoke/factcheck/halluc_ru.md tests/smoke/factcheck/halluc_en.md \
    --output tests/reports/factcheck/out_halluc.json
```

Для каждого запуска появится строка вида:
```
P=0.777 R=1.000 F1=0.420 |RU|=6 |EN|=6
```

### 6. Проверить отчёты

```bash
for f in tests/reports/factcheck/out_*.json; do
  echo "=== $f ==="
  python -c "import json,sys; o=json.load(open('$f'))['overlap']; print(json.dumps({k:o[k] for k in ['precision','recall','f1','unmatched_ru','unmatched_en']}, ensure_ascii=False, indent=2))"
done
```

Ожидаемый паттерн:

| Сценарий | precision | recall | в unmatched |
| --- | --- | --- | --- |
| (a) идентичный | 1.0 | 1.0 | пусто с обеих сторон |
| (b) урезанный | 1.0 | 0.5 | непустой `unmatched_ru` (потерянные факты) |
| (c) галлюцинация | 0.85 | 1.0 | непустой `unmatched_en` (лишний факт про Империю) |

Если на всех трёх сценариях метрики такие — фактчек живой.

### 7. Диагностика, если что-то падает

- **`AttributeError: 'NoneType' object has no attribute 'items'`** → `configs/models.yaml` пустой, не сохранил правки из шага 3.
- **`extractor returned non-JSON output: '<think>…'`** → забыт флаг `--reasoning-parser deepseek_r1` при запуске vLLM.
- **`extractor returned non-JSON output: '```json\n[…]\n```'`** → модель оборачивает ответ в code-fences. Напиши — добавлю защитную обрезку в клиент.
- **`openai.AuthenticationError: 401`** → `.env` не загрузился или `VLLM_API_KEY` пустой. Проверь `echo $VLLM_API_KEY`.
- **`KeyError` / `ValidationError` на `OverlapMatch`** → судья сбрасывает одно из полей `ru_idx`/`en_idx`/`confidence`. Если редко — перезапусти; если систематически — модель не тянет роль судьи, возьми модель побольше.
