# Спека: пересборка seed-данных из gemma_par_by_par (волна 3, задача 4) — rev-2

Дата: 2026-07-02. Ветка: `feat/seed-refresh`. Статус: **rev-2 после /verify-spec (3 аспекта: 2 CRITICAL, 5 HIGH закрыты)**.

**Done when:** демо-документ = первые 15 телесных абзацев книги с переводом gemma, 0 кириллицы в EN, baseline'ы и термины — реальные выходы пайплайна под капами и guard'ом, прод пересеян и перезапущен, стоимость задокументирована.

## Проблема (воспроизведена)

4 из 16 абзацев текущего `data/seed/seed_paragraphs.jsonl` содержат кириллицу в английском target («ядро», «хозяйства.», «отменил»…) → каскад честных ошибок судей. Плюс advice-вставки в prod-target (см. suggestion-guard).

## Источник данных (проверено verify-spec)

- **RU: `data/pilot/pilot_original.md`** (уровень `data/pilot/`, НЕ внутри translating/) — 548 строк, построчно соответствует EN.
- **EN: `data/pilot/translating/local/gemma_par_by_par/translation.md`** — 548 строк.
- Оба в чекауте old-ветки `/Users/a1111/Projects/Work/gse-translation` (read-only, абсолютные пути).
- **Правило отбора: первые 15 ТЕЛЕСНЫХ абзацев** — неабзацные строки отсеиваются механически: all-caps заголовки (строки 1, 15), литерал «Picture text» (строка 10); никакого ручного выбора. RU и EN режутся одним правилом по одним индексам (соответствие 1:1 подтверждено выборочно).

## Решение

1. **Скрипт пересборки** (`scripts/`, идемпотентный, коммитится): читает пары, пишет тексты в новый seed JSONL.
2. **Baseline-оценки/issues — через локальный экземпляр webapp**, не отдельным скриптом: сид новых текстов без baseline'ов в throwaway-БД → прогон judge по 5 критериям × 15 абзацев HTTP-вызовами `/evaluate` на локальном инстансе с реальным ключом → так автоматически действуют **капы $2/200 (`budget.py: reserve/settle`)** и **suggestion-guard** (ветка guard мержится ПЕРВОЙ — зависимость) → экспорт scores/issues из БД в seed JSONL. ~75 OR-вызовов (gpt-5.4-mini), оценка ≤$0.5, ретраи ограничены существующим `EVAL_RETRIES=2` с одной резервацией.
3. **Терминология**: extraction — 15 OR-вызовов haiku-4.5 через `term_pipeline` (его `MAX_CALLS`/`--max-usd` подтянуть к 15/0.2); grounding+pairing — **сабагент-бэкенд, как в историческом G3/P3 прогоне** (~190+78 вызовов сабагентами, ≈$0 в OR-бюджете; OR-обвязки для них не существует и НЕ пишется — это отдельная capability по known_issues); Wikidata — существующий `WikidataClient` (кеш, User-Agent, maxlag, Retry-After; ~200 свежих вызовов на новый набор — бесплатно, этикет соблюдён кодом).
4. **Адаптер формата** (verify-spec: форматы несовместимы): `Term[]` пайплайна → `identified_terms` сида: `{source_term: source_surface, translation_used: target_surface, domain: note}` — явный шаг скрипта. Реальные `pair_accuracy` заменяют placeholder-ротацию `[i % 3]`.
5. **Гарды**: pytest — 0 кириллицы во всех `translated`; 15 абзацев; у каждого ≥1 baseline; повторный прогон `looks_like_advice` по новому корпусу (re-validation из guard-спеки).
6. **Стоимость — таблица в отчёте**: judge ~75 OR-вызовов ≤$0.5 (капы), extraction 15 вызовов ~$0.01, grounding/pairing сабагенты ≈$0, Wikidata $0. Budget-лог копируется в `docs/reports/e2e/2026-07-02-seed-refresh-budget.jsonl` (evidence-конвенция; дефолтный путь gitignored).

## Деплой (rev-2: ops-находки)

**Supersession:** этот деплой — единственное разрешённое исключение из запрета полного ресида в `2026-07-02-settings-rework.md` §4 (данные меняются целиком); после него точечная политика возвращается. В settings-спеку тем же коммитом добавляется forward-ссылка. **Порядок мерджа: settings-rework (даёт `PALIMPSEST_SEED_DEMO`) → suggestion-guard → seed-refresh.**

1. Pre-check: `docker exec gse-demo env | grep -c OPENROUTER_API_KEY` = 1 (иначе стоп: ресид сотрёт ключи строк).
2. Бэкап: `cp /opt/gse-demo/data/demo.db /opt/gse-demo/data/demo.db.bak`.
3. Ресид: **`docker exec -e PALIMPSEST_SEED_DEMO=1 gse-demo python -m palimpsest.webapp.seed`** (флаг обязан идти через `-e` — в базовом env контейнера его нет; OPENROUTER_API_KEY уже в env, `-e` не нужен). Это же закрывает курацию vLLM-строк.
4. **`docker restart gse-demo` — обязательный шаг**: запущенный uvicorn держит fd удалённого inode и без рестарта продолжит отдавать старую БД (то же верно для отката).
5. Проверка: `/api/documents` (15 абзацев), `/api/models` (5 строк, ключи маскированы), живой evaluate 1 критерия.
6. **Rollback**: `cp demo.db.bak demo.db` → `docker restart gse-demo` → те же проверки по старым ожиданиям. Загрузки при ресиде теряются — принято (одноразовые).

## Не делаем

- Не пишем OR-бэкенд для grounding/pairing-судей; не меняем формат seed JSONL и seed.py (кроме флага из settings-ветки); не трогаем old-чекаут; не правим тексты руками (расхождение = стоп и вопрос владельцу).

## Критерии успеха

1. Чистая БД после `python -m palimpsest.webapp.seed`: 15 абзацев, 0 кириллицы, реальные термины (target_surface/pair_accuracy из пайплайна), baseline всех 5 критериев, advice-suggestion = 0.
2. Прод после ресида+рестарта: судьи не флагуют русские слова; реестр 5 строк; живой evaluate проходит.
3. Отчёт с фактической стоимостью из `docs/reports/e2e/2026-07-02-seed-refresh-budget.jsonl`.
