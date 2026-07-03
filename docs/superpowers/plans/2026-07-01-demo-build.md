# План реализации — Palimpsest demo (feat/demo)

Up-link: [архитектура](../specs/2026-06-30-demo-architecture-design.md) · [контракты rev-4](../specs/2026-06-30-demo-contracts.md) · дата: 2026-07-01

> Исполняется автономно в worktree `/Users/a1111/Projects/Work/worktrees/feat-demo` (ветка `feat/demo`). Все агенты пинятся к этому пути. Контракт — единственный источник истины; этот план — порядок и границы модулей.

## Цель (проверяемое состояние)

Seed-документ грузится; `/evaluate` живьём оценивает абзац по включённым критериям и эмитит issues; accept-fix → пересчёт показывает числовую дельту (`aggregate` vs `aggregateBaseline`); терминология рисует два сигнала на seed-терминах; reset возвращает к оригиналу; Settings правит критерии и реестр моделей. Прогон цикла подтверждён в браузере.

## Опора и переносы

**Строим поверх scaffold `a9c69b9`** (НЕ с нуля): `webapp/app.py` (FastAPI app-factory), `llm/client.py` (`LLMClient.complete(system,user,**ov)->str`, sync, openai), `evaluation/criteria.py` (`Criterion`, `consensus`), `evaluation/judge.py` (заглушка — переписываем), `glossary.py`. pyproject уже несёт fastapi/uvicorn/pydantic/openai; SQLite = stdlib `sqlite3`.

**Переносим из artem-чекаута** (`/Users/a1111/Projects/Work/gse-translation`):
- `prompts/03_scoring/v2/{accuracy,fluency,style,cultural,terminology}.md` — per-criterion промпты, эмитят `identified_issues:[{source_fragment,problematic_fragment,explanation,suggestion}]` → `prompts/scoring/` в feat/demo.
- `prompts/04_correction/system.md` → для `/apply-edit`.
- `data/pilot/evaluation/gpt-5.4-mini_par_by_par/translation_scores.jsonl` (549 абзацев) → `data/seed/translation_scores.jsonl` (LFS).

**Строим с нуля (rev-4):** `db.py` (8 таблиц + соединение), API-роуты, `judge_one` (per-criterion → score+issues), `compute_aggregate`, `seed.py`.

## Модули и интерфейсы (backend, `src/palimpsest/webapp/`)

- **`db.py`** — DDL rev-4 §4 (`document/paragraph/score/issue/term/criterion/model/glossary`, `kind`, `seed_target`, `version`, FK + `PRAGMA foreign_keys=ON`); `connect()`, `init_db()`, row-helpers. `sqlite3`, `--workers 1`, `check_same_thread=False` + lock.
- **`aggregate.py`** — `compute_aggregate(scores_by_criterion, criteria) -> (value, criteria_key)`; `norm=(v−min)/(max−min)`, взвешенно по ВСЕМ enabled, подстановка последнего для не-переоценённых.
- **`judge.py`** (переписать) — `judge_one(client, criterion, ru, en) -> ScoreRow + list[IssueRow]`; грузит per-criterion промпт, парсит `{final_score, summary, identified_issues}`, маппит `problematic_fragment→targetFragment`, деривит `severity`, `mqmCategory=None`. Параллельность по критериям — `asyncio.gather` + `asyncio.to_thread` (client sync).
- **`routes.py`** (расширить app.py) — все эндпоинты rev-4 §2: `GET /api/documents[/{id}]`, `PATCH /api/paragraphs/{id}`, `POST .../evaluate|apply-edit`, `POST /api/documents/{id}/reset`, CRUD `/api/criteria` + `/api/models` (masked, params secret-guard), `POST .../terms`. Семантика цикла/кеша/reset — rev-4 §3.
- **`seed.py`** — курируемый срез ~15–20 абзацев (по числу issues; хедлайнер id=92, терминологичные id=52/40) из `translation_scores.jsonl` → `document/paragraph(seed_target)/score(kind=seed)+score(kind=cache)/issue/term(моки)/glossary(моки, wikidataUrl)`; `criterion` из `prompts/scoring` + `models.yaml`; `compute_aggregate` тот же.

## Frontend (`frontend/`, бывш. web-prototype)

- **`src/demo/api-client.ts`** — DTO-типы rev-4 §1 + fetch к API; base `''` (тот же origin / vite proxy на :8000).
- **Стор Zustand** — `document/criteria/models` + UI-состояние; данные из API вместо мок-`data.ts`.
- Variant A: убрать мок `data.ts` как источник; `/evaluate` с loading + `cached`-бейдж; before/after из `aggregate`/`aggregateBaseline`; кнопка **reset**; Settings — редактор `params` (key-value), модель по имени; терминология — два сигнала из `Term`; `mqmCategory` в карточке issue.

## Порядок исполнения (зависимости)

1. **Phase 0** (оркестратор): `git mv web-prototype frontend`; перенос промптов+данных; `uv sync`; vite proxy `/api`→`:8000`.
2. **db.py + aggregate.py** (Sonnet) → 3. **judge.py** (Sonnet, зависит от client+prompts) → 4. **routes** (Sonnet, зависит от db+judge+aggregate) → 5. **seed.py** (Sonnet, зависит от db+aggregate).
6. **Frontend api-client + wiring** (Sonnet) — параллельно 2–5 (контракт фиксирован).
7. **Тесты** (Sonnet) — backend unit (aggregate, judge-parse, db) + integration (seed→GET→evaluate-mock→apply-edit→reset).
8. **Интеграция + e2e** (оркестратор + e2e-tester): живой прогон цикла в браузере, отчёт.

## Тест-стратегия

- Unit: `compute_aggregate` (нормализация, частичный набор), judge-парсер (v2 payload→IssueRow, severity-деривация), db (FK, kind-выборка latest, reset).
- Integration: seed на изолированной БД → `GET /api/documents/{id}` → `evaluate` (LLM замокан) → `apply-edit` → `reset`; проверка инвариантов (accepted переживает пересчёт, latest исключает cache, criteria_key).
- e2e: реальный браузер, цикл «accept→re-score→прирост», два сигнала терминологии, Settings, reset.

## Риски

- LLMClient sync vs параллельность → `asyncio.to_thread`.
- `models.yaml` пуст → seed добавляет ≥1 рабочую модель (ключ из env).
- Seed-данные под LFS → проверить `.gitattributes` до коммита.
- Живой `/evaluate` дорог/долог на тестах → в integration мокаем `LLMClient.complete`.
