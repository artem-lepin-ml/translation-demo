# Palimpsest demo — архитектура и контракты нового проекта

Up-link: docs/pipeline.md (документ в ветке `old-gse-translating`) · опирается на: keep-minimum манифест (документ в ветке `old-gse-translating`), reorg-план (документ в ветке `old-gse-translating`), [UI-дизайн Variant A](2026-06-30-palimpsest-demo-ui-design.md) · дата: 2026-06-30

> Дизайн **самого проекта** (бэкенд, хранилище, контракты, что переносим из старых веток). UI зафиксирован отдельно в [palimpsest-demo-ui-design](2026-06-30-palimpsest-demo-ui-design.md). На конфликте — этот документ новее и побеждает по архитектуре/контрактам.

## Главное

Строим **новый проект в новой ветке** старого репозитория: веб-приложение Palimpsest для оценки перевода исторических текстов (EMNLP demo-track). Это **не переписывание** старого pipeline/viewer — чистая основа `main` (a9c69b9) уже развязана со старым кодом; старое остаётся в ветке `artem` нетронутым. Из старого переносим **только проверенные семена** (LLM-клиент, ядро судьи, промпты, реестр моделей) и утверждённый TipTap-UI. Бэкенд — **FastAPI + SQLite**, фронт — **Vite + React + TipTap (Variant A)**.

**Цель достигнута, когда** (проверяемое состояние, дедлайн EMNLP 2026-07-10): seed-документ грузится; `/evaluate` отдаёт живые скоры по всем включённым критериям; accept-fix → пересчёт показывает числовую дельту (`aggregate` vs `aggregateBaseline`); сигналы терминологии рисуются для seed-терминов; reset возвращает документ к оригиналу. **Non-goal первой сборки:** сам term-агент (Wikidata-поиск, роудмапа п.1/п.3) — контрибьюшен 1 показываем на моках/seed за контрактом `Term`.

## Закрытые решения

| # | Решение | Обоснование |
|---|---|---|
| 1 | **Терминология = отдельный term-агент** (позже, non-goal первой сборки). Старый glossary-runtime НЕ переносим. | Term-агент (Wikidata/Wikipedia → вердикты 🟢🟡🔴) — новый движок; старый `matcher.py`/`main.json` жёстко RU-привязан и избыточен. До готовности агента термины — моки за контрактом `Term`. `main.json` (150 терминов) → начальное наполнение `glossary`-таблицы через seed; после seed SSOT терминологии — БД, не `main.json`. |
| 2 | **Хранилище — SQLite** (не файлы/in-memory). | Закладываем основу с персистентностью: правки перевода, статусы issues, конфиг оценщиков и реестр моделей переживают сессию. Владелец: «делаем абстракции заранее». |
| 3 | **`severity` (minor/major) — в схему судьи** структурно. | Чистый путь вместо парсинга текста. Для seed уже посчитанного пилота — деривация из `explanation` (разовая). |
| 4 | **Ветка `feat/demo` от `main`** (a9c69b9). Старое (`artem`/`dev` + прод-viewer) не трогаем и не удаляем. | «Новый проект в ветке старого репо». Прод старого сайта живёт для MGIMO. |

## Раскладка веток (факт на 2026-06-30)

```
artem / dev                       → старый pipeline + задеплоенный viewer (LLM-Comparator)  ← НЕ ТРОГАЕМ
main / demo-v1/v2/v3 / demo-skeleton = a9c69b9 «initial project setup»  ← чистая основа нового проекта
  · demo-v3        → Variant A (утверждённый UI), НЕ закоммичен
  · demo-skeleton  → backend-каркас ~873 LOC (FastAPI app.py, evaluation/judge.py, заглушки)
glossary-overnight                → KG/глоссарий (main.json, 150 терминов Wikidata/Wikipedia)
```

Старый pipeline и viewer **ноль раз** импортируют друг друга в новой основе — поэтому перенос = копирование отдельных семян, без распутывания старого дерева.

## Что переносим (seed) / что НЕ переносим

**Переносим в `feat/demo`:**

| Seed | Откуда | Роль в проекте |
|---|---|---|
| Variant A (UI) | `demo-v3` (uncommitted) | сам продукт; данные приходят из API, а не из `data.ts` |
| `LLMClient` | `artem: src/palimpsest/llm/client.py` | единственная точка доступа к LLM (инвариант #6); движок `/api/evaluate` |
| Judge core (~80 из 811 LOC): `score_paragraph`, `parse_judge_response`, `_JUDGE_TOOL_SCHEMA` + `correction._build_edit_message` | `artem: scoring.py`, `correction.py` | оценка абзаца + «accept → применить правку» |
| Промпты v2 (5 критериев) + correction | `artem: prompts/03_scoring/v2/*`, `prompts/04_correction/system.md` | дефолтная панель оценщиков; `identified_issues[]` = готовая схема карточек |
| `models.yaml` + `ModelConfig` | `artem: configs/` | Model Registry в Settings (309 строк proxy-специфики — не вывести из схемы) |

**НЕ переносим** (остаётся в `artem`): старый batch-pipeline, `chunking`, `factcheck`, build-пайплайн глоссария, glossary-runtime, viewer backend+frontend (~99k строк LLM-Comparator), старые CLI/deploy-скрипты, старые планы/доки. Старый `02_translate` — тоже нет (демо оценивает готовый перевод, не переводит).

## Архитектура (монорепо)

```
feat/demo/
├── frontend/                 Vite + React 19 + TS + TipTap v3 (Variant A)
│   └── src/ (store на Zustand; данные из API; контракты-DTO в api-contract.ts)
├── backend/                  FastAPI + SQLite
│   ├── app.py                create_app(), роуты
│   ├── db.py                 SQLite-схема + доступ
│   ├── seed.py               загрузка пилотных данных в БД
│   └── palimpsest/           перенесённое ядро (llm-client, judge-core, prompts, provider-registry)
└── data/                     seed-источник (пилотный translation_scores.jsonl или его срез)
```

Компоненты — каждый одна ответственность + объявленный интерфейс (по целевой карте keep-minimum): `tiptap-ui` → `backend-api` → {`judge-core`, `provider-registry`, `llm-client`}; `term-pairs` (позже, от агента).

## Контракт данных и API

Полная **SQLite-DDL** и **REST-API** — единственный источник истины в [demo-contracts.md §2, §4](2026-06-30-demo-contracts.md) (там же — семантика цикла/кеша/reset, ревизия 4). Здесь НЕ дублируем: раньше тут лежала устаревшая копия схемы (`term_pair/domain/verdict`, `model.temperature`) и API (`target?`, без reset/glossary) — убрана во избежание расхождения.

Канонические wire-DTO типы (`Paragraph`, `Issue`, `Term`, `Criterion`, `ModelRegistryEntry`) — **единственный источник истины** в [demo-contracts.md §1](2026-06-30-demo-contracts.md). Здесь не дублируем, чтобы не разъезжалось. Сущности те же, что в прототипе Variant A — менялся только транспорт; терминология эволюционировала из единого `TermPair.verdict` в `Term` с двумя сигналами (`difficulty` + `pairAccuracy`).

## Цикл улучшения (ядро демо)

1. **Accept** на issue → `POST /apply-edit` применяет `suggestion` к `target` (или ручная правка `PATCH`).
2. Фронт триггерит `POST /evaluate` (единственный живой LLM-путь) → судья пересчитывает → новые строки `score`/`issue`.
3. UI показывает прирост: `aggregate` vs `aggregateBaseline` (заголовок) и vs `scoresPrev` (шаг). Persist в SQLite. Кнопка **reset** возвращает к seed для следующего посетителя.

Точная семантика (агрегат по всем критериям, кеш-фолбэк `kind='cache'`, reset по `kind!='seed'`, гонки) — в [demo-contracts.md §3](2026-06-30-demo-contracts.md). Мок `scoresImproved` из прототипа удаляется: «после» рождается живым пересчётом.

## Frontend ↔ component

Маленький стор (**Zustand**): `document`, `criteria`, `models` + UI-состояние (`acceptedIds`, `dismissedIds`, `rescoringIds`, `selectedPara`, `inspectorTab`, `hoveredTermId`). Конфиг сквозной (Settings ↔ Document), поэтому стор оправдан против прокидывания пропсов через 4 уровня.

## Seed

`backend/seed.py` читает пилотный `translation_scores.jsonl` (`gpt-5.4-mini_par_by_par`, 549 абзацев — для демо можно срез) → заполняет `document`, `paragraph`, начальные `score`+`issue`, `term` (моки до term-агента). `criterion` — из промптов v2 + `models.yaml`.

**Деривация `severity` для seed** (в upstream поля нет): если `explanation` находки содержит (case-insensitive substring) любое из `incorrect, wrong, mistranslat, error, missing, omit, distort, confus` → `major`, иначе `minor`. Правило фиксируем до написания `seed.py`, чтобы не свалить всё в `minor`. Для будущих ранов — `severity` уйдёт в схему судьи (решение #3), и деривация станет не нужна.

## Входы для плана (из verify-spec, операционные HIGH)

Это не контрактные дыры, а конкретные шаги для `writing-plans`:
- **Git-процедура `feat/demo`:** ветка от `main` (a9c69b9); cherry-pick `cfd0f28` (Variant A) + перенос backend-каркаса из `demo-skeleton` (873 LOC). НЕ ветвиться от `demo-v3`. После — `demo-v1/v2/v3`/`demo-skeleton` архивируем тегами.
- **Перенос-семена С ТЕСТАМИ, не copy:** перед копированием `scoring.py`/`correction.py` — `grep` их внутрипакетных импортов (`from ..`, `import palimpsest`), убедиться что каждый символ либо в наборе семян, либо заменён заглушкой (ловушка приватных импортов из прошлых аудитов). Портировать с smoke-тестами.
- **Git-LFS:** до первого коммита на `feat/demo` проверить, что `translation_scores.jsonl` и новые `data/`-файлы покрыты `.gitattributes` LFS (иначе большой blob ломает LFS).
- **Незакоммиченный `CLAUDE.md`-trim в `demo-v3`** — закоммитить/обработать при заводе ветки.
- **`term_pairs.json`:** путь `data/seed/term_pairs.json`, конверт = массив `Term`; `seed.py` читает если есть, иначе пусто (моки).

**Кураторство абзацев (форк #4, принято):** курируемый срез **~15–20 показательных абзацев** (по числу issues из пилота `gpt-5.4-mini_par_by_par`), а не весь пилот 549; `seed.py` для них считает baseline + `kind='cache'` (ожидаемый после правок). Опционально — **второй документ для A/B** (другая модель/непоправленный перевод), усиливает контрибьюшен 2/3.

**Деплой (форк #5, открыт/отложен):** локальная сборка и запуск (`uvicorn` + `vite`) деплоя не требуют; решение по прод-деплою (Docker/порт/Caddy, развязка с живым старым сайтом) — открыто, владелец решит позже.

## Статус

Прошёл `/verify-spec` (5 аспектов). Механические CRITICAL/HIGH закрыты в контракте (ревизия 4) и здесь. **Гейт:** остаются 5 решений владельца (research/scope) — см. чат; после них → `writing-plans` → ветка `feat/demo`. Реализация не начата.
