# План реализации: пересборка seed-данных из gemma_par_by_par (волна 3, задача 4)

Up-link: [спека rev-2](../specs/2026-07-02-seed-refresh.md) · [docs/subsystems/webapp.md](../../subsystems/webapp.md) · [docs/stages/terminology.md](../../stages/terminology.md)

**Цель:** демо-документ = первые 15 **телесных** абзацев книги с переводом gemma, 0 кириллицы в EN target, baseline'ы и термины — реальные выходы пайплайна под капами `budget.py` и suggestion-guard'ом, прод пересеян и перезапущен, стоимость задокументирована.

**Ветка / worktree:** `feat/seed-refresh` в `/Users/a1111/Projects/Work/worktrees/seed-refresh` (создаётся оркестратором от `dev-demo`, см. «Создание worktree» ниже). PR → `dev-demo`.

**Зависимость мерджа (жёсткая):** `settings-rework` (даёт `PALIMPSEST_SEED_DEMO` + правку §4, куда добавляется forward-ссылка) → `suggestion-guard` (даёт `looks_like_advice` + контракт-preamble; регенерация baseline'ов должна идти уже под guard'ом) → **seed-refresh**. Phase B/C/D запускаются только после того, как обе ветки-предшественницы влиты в базу `feat/seed-refresh`.

---

## Отклонения от спеки (см. header-требование)

1. **`2026-07-02-settings-rework.md` отсутствует в worktree `term-consolidated`** (проверено: файла нет; ветка `settings-rework` ещё не влита). Спека требует «тем же коммитом добавить forward-ссылку в §4». Поэтому supersession-правка §4 вынесена в **Phase D, задача D0**, которая выполняется **после ребейза на влитую settings-rework** — раньше править нечего. Если к моменту старта Phase D файл так и не появился — СТОП и вопрос владельцу (нельзя закрыть критерий supersession без него).
2. **`PALIMPSEST_SEED_DEMO` в коде отсутствует** (grep по `src/`/`docs/` — только в самих спеках). Флаг приходит из settings-rework; `seed.py` его пока не читает. План опирается на семантику флага из спеки (полный ресид разрешён только под `=1`), но **не реализует** его — это ответственность settings-ветки. Phase D задаёт флаг через `-e`, как в спеке; если после мерджа `seed.py` его не проверяет — СТОП (ресид без гейта опасен).
3. **Адаптер `Term[]→identified_terms` уже существует наполовину**: `scripts/load_terms.py` грузит `terminology_out.json` прямо в DB-таблицу `term` по точному совпадению `source`. Это делает шаг «адаптер» в Phase C тоньше, чем описано в спеке §4: seed JSONL несёт `terminology.identified_terms` только для «мок»-пути `seed.py:_seed_terms`, а **реальные** термины кладутся в БД через `load_terms.py` (обходя placeholder-ротацию `[i%3]`). План использует `load_terms.py` как основной путь и добавляет обратный адаптер `Term[]→identified_terms` в rebuild-скрипт, чтобы seed JSONL тоже был честным (для будущих `POST reset` и для инварианта «seed.py в одиночку даёт реальные термины», критерий успеха §1). Placeholder-ротация `[i%3]` в `seed.py:_seed_terms` при этом становится мёртвой для демо-документа — трогать её не нужно (спека: «не меняем seed.py кроме флага»).
4. **`id` в seed JSONL — непоследовательный** (текущие: 92,52,40,…522 — исходные номера абзацев книги). `term_pipeline`/`load_terms`/`emit_*` ключуются по этому `id`. Rebuild-скрипт присваивает новым 15 записям стабильные `id` = **1-based номер телесного абзаца** (1..15), а НЕ номер строки файла — так проще и детерминированно. (Отклонение от «исторических» id, но формат допускает любой уникальный int; проверено — потребители используют id только как ключ словаря.)
5. **Стоимость judge уточнена**: спека пишет «~75 OR-вызовов». Модель по умолчанию — `openai/gpt-5.4-mini` (`DEFAULT_CRITERION_MODEL`). 5 критериев × 15 абзацев = **75 первичных вызовов**; с `EVAL_RETRIES=2` худший случай — до 225, но ретраи бьют только по transient-ошибкам и одной резервацией. Реалистичная оценка ниже (см. Phase B).

---

## Источник данных (пин механического фильтра — проверено)

Оба файла в старом чекауте (read-only, абсолютные пути):

- **RU:** `/Users/a1111/Projects/Work/gse-translation/data/pilot/pilot_original.md` (548 строк).
- **EN:** `/Users/a1111/Projects/Work/gse-translation/data/pilot/translating/local/gemma_par_by_par/translation.md` (548 строк).

**Механический фильтр телесного абзаца** (без ручного выбора): строка отсеивается, если после `strip()` она (а) пустая, ИЛИ (б) == литерал `"Picture text"`, ИЛИ (в) **all-caps** (все буквы `c.upper()==c`; заголовки). Остальное — тело.

**Результат применения (проверено скриптом, пин):** первые 15 телесных абзацев = строки (1-based, одни и те же для RU и EN):

```
[2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18]
```

Отсеяно в голове: L1 `МЕСОПОТАМИЯ` (all-caps), L10 `Picture text` (литерал), L15 `ОТ ОБЩИН К ДЕСПОТИЯМ…` (all-caps). Выравнивание RU↔EN на этих 15 строках подтверждено выборочно (1:1), **кириллица в EN-срезе = 0** (проверено регэкспом `[а-яёА-ЯЁ]`). Правило режет RU и EN по одним индексам.

---

## Данные / артефакты (карта потоков)

| Файл | Роль | Кто пишет |
|---|---|---|
| `data/seed/seed_paragraphs.jsonl` | 15 записей `{source, translated, <5 crit>{final_score,summary,identified_issues}, terminology{identified_terms}, id}` | Phase A (тексты+id) → Phase B (baseline crit-блоки) → Phase C (terminology-блок) |
| `data/seed/extracted_surfaces.json` | NER-поверхности на абзац | Phase C: `term_pipeline extract --real` |
| `data/seed/lemmas.json` | surface→lemma | Phase C: extract побочно |
| `data/seed/terminology_terms.jsonl` | mentions (спаны) | Phase C: `term_pipeline mentions` |
| `reports/terminology/demo_grounding_inputs.json` | вход сабагенту-groundеру (per-lemma + кандидаты) | Phase C: `emit_demo_grounding.py` |
| `reports/terminology/g3_groundings.json` | `{lemma:{qid,difficulty}}` — вердикты сабагента G3 | **Phase C: ОРКЕСТРАТОР (сабагент)** |
| `reports/terminology/judge_inputs.json` | вход сабагенту-paireру (canon_en+target) | Phase C: `emit_judge_inputs.py` |
| `reports/terminology/judgments_pairing.json` | `{surface:{verdict,target_surface,recommended}}` — вердикты сабагента P3 | **Phase C: ОРКЕСТРАТОР (сабагент)** |
| `data/seed/terminology_out.json` | собранный `Term[]` на абзац | Phase C: `rebuild_demo.py` |
| `docs/reports/e2e/2026-07-02-seed-refresh-budget.jsonl` | копия budget-лога (evidence) | Phase B/D: `cp` дефолтного `budget_calls.jsonl` |

**Формат записи seed** (подтверждён из текущего файла): top-keys `source, translated, accuracy, fluency, style, terminology, cultural, consistency, id`. Каждый крит-блок: `{identified_issues:[{problematic_fragment, source_fragment, explanation, suggestion}], criteria_assessment, summary, final_score}`. `terminology` дополнительно несёт `identified_terms:[{domain, source_term, translation_used}]`.

---

## Как выполнять / глобальные ограничения

- LLM-вызовы только через `palimpsest.llm.client.LLMClient` (инвариант №6). Phase A — **без** LLM. Phase B — judge через локальный webapp (`/evaluate`, тот же клиент). Phase C — extraction через `term_pipeline` (тот же клиент); grounding/pairing — сабагенты (для них OR-обвязки нет и не пишем).
- Не трогаем старый чекаут `gse-translation` (read-only).
- Не правим тексты руками: любое расхождение RU↔EN по индексам = **СТОП и вопрос владельцу**.
- Не меняем формат seed JSONL и `seed.py` (кроме флага из settings-ветки — он не в этой ветке).
- Не пишем OR-бэкенд для grounding/pairing-судей (known_issues capability).
- Тесты НЕ ходят в реальный OpenRouter (Phase A guards мокают/офлайн). Реальные деньги тратятся только в Phase B (judge) и Phase C (extraction) — budget-critical, на verify ревьюить особо.
- Один коммит на задачу; Conventional Commits, английский, императив, **без** трейлера `Co-Authored-By` (правило репо).

### Создание worktree (шаг оркестратора, до Phase A)

```bash
git -C /Users/a1111/Projects/Work/gse-translation worktree add \
  /Users/a1111/Projects/Work/worktrees/seed-refresh -b feat/seed-refresh dev-demo
```

Все команды Phase A–C выполняются с `cwd = /Users/a1111/Projects/Work/worktrees/seed-refresh` и `PYTHONPATH=src` (или `uv run`). Ключ — из `/Users/a1111/Projects/Work/worktrees/seed-refresh/.env` (после создания worktree `.env` берётся из рабочего дерева; если его нет — скопировать из `term-consolidated/.env`, ключ `sk-or-…` присутствует, проверено).

---

## Phase A — rebuild-скрипт + тексты + pytest-guards (БЕЗ LLM)

Детерминированная, идемпотентная, коммитится. Ноль сети.

### Задача A1: скрипт `scripts/rebuild_seed_texts.py` [M]

**Файлы:** Create `scripts/rebuild_seed_texts.py`; Modify (write) `data/seed/seed_paragraphs.jsonl`.

**Что делает (идемпотентно):**
1. Абсолютные пути к RU/EN old-checkout (константы вверху, read-only open).
2. `body_indices(lines) -> list[int]`: применяет фильтр (пусто / `"Picture text"` / all-caps → отсеять), возвращает 1-based индексы; берёт первые 15.
3. **Guard совпадения индексов:** если `body_indices(ru)[:15] != body_indices(en)[:15]` → `raise SystemExit` с диффом (правило «расхождение = стоп»).
4. Читает существующий `seed_paragraphs.jsonl`, **сохраняет** структуру записи, но для новых 15 записей выставляет `id = 1..15`, `source = ru[idx-1]`, `translated = en[idx-1]`; крит-блоки и `terminology` инициализируются пустыми плейсхолдерами (`final_score: null`, `identified_issues: []`, `identified_terms: []`) — заполнятся в Phase B/C.
5. Пишет ровно 15 строк JSONL (`ensure_ascii=False`), детерминированный порядок по `id`.
6. Печатает сводку: `wrote 15 paragraphs, body_indices=[…], cyrillic_in_en=0`.

**Проверка сразу:** повторный запуск даёт byte-identical файл (идемпотентность).

### Задача A2: pytest-guards `tests/test_seed_refresh.py` [M]

**Файлы:** Create `tests/test_seed_refresh.py`.

TDD-порядок: тесты пишутся против будущего состояния и гоняются на каждой фазе (A даёт тексты; B — baseline; C — термины). На выходе Phase A часть должна пройти, часть (baseline/термины) — падать помечены `xfail(strict=False)` до соответствующей фазы, затем снимаем xfail.

Тесты (все читают `data/seed/seed_paragraphs.jsonl`):
1. `test_15_paragraphs` — ровно 15 записей.
2. `test_no_cyrillic_in_translated` — регэксп `[а-яёА-ЯЁ]` не матчит ни одну `translated` (критерий успеха §1). **Проходит после A.**
3. `test_ids_unique` — все `id` уникальны.
4. `test_each_has_baseline` — у каждой записи ≥1 крит-блок с ненулевым `final_score` по всем 5 критериям (accuracy/fluency/style/cultural/terminology). **xfail до Phase B.**
5. `test_real_terms` — каждая запись: `terminology.identified_terms` непуст ИЛИ явно `[]` для абзаца без терминов; хотя бы у части записей `translation_used` присутствует (не placeholder). **xfail до Phase C.**
6. `test_advice_free` — прогон `looks_like_advice` (из `judge.py`, приходит с suggestion-guard) по всем `suggestion` во всех крит-блоках → 0 срабатываний (re-validation trigger из guard-спеки §4). **xfail до Phase B + до мерджа guard.**

**Команда:** `uv run pytest tests/test_seed_refresh.py -q`.

- [x] **Принятое промежуточное состояние (verify-pr, 2026-07-02):** после Phase A 18 preexisting-тестов (`tests/{test_apply_edit,test_db,test_issue_dedup,test_issue_status,test_seed_registry,test_test_endpoint}.py`) временно красные — завязаны на контент старого 16-абзацного сида. Не регрессия, ожидаемо до Phase B/C. Сигнальная запись — [known_issues.md](../../known_issues.md) (**удалить эту запись known_issues, когда Phase B/C будут выполнены и 18 тестов снова зелёные**).
- [x] **Одобренное отклонение от «не трогаем seed.py»:** `src/palimpsest/webapp/seed.py:83` изменён с `"final_score" not in payload` на `payload.get("final_score") is None` — иначе Phase A плейсхолдеры (`final_score: null`, ключ присутствует) ложно проходили бы условие «есть baseline» и попадали в агрегат как 0. Точечный guard-фикс, не расширение функциональности; согласовано в рамках verify-pr 2026-07-02.

### Задача A3: doc-parity ссылка

**Файлы:** Modify `docs/stages/terminology.md` (или webapp.md) — одна строка: «demo seed regenerated from gemma_par_by_par via `scripts/rebuild_seed_texts.py`; baselines via local `/evaluate`, terminology via subagent G3/P3». Коммит вместе с A1.

**Коммит Phase A:** `feat(seed): rebuild demo seed texts from gemma par-by-par (first 15 body paragraphs)`.

---

## Phase B — регенерация baseline'ов через ЛОКАЛЬНЫЙ инстанс webapp

Реальные деньги. Идёт **после мерджа suggestion-guard** (иначе baseline'ы соберутся без guard-контракта). Все команды — `cwd=/Users/a1111/Projects/Work/worktrees/seed-refresh`.

### B0: throwaway-БД + сид без baseline'ов

Тексты уже в seed JSONL, но крит-блоки пусты, поэтому `seed.py` не запишет baseline-score'ы (в `seed.py:83` `payload` без `final_score` пропускается) — ровно то, что нужно: тексты в БД, baseline'ов нет.

```bash
export PALIMPSEST_DB=/tmp/seed_refresh_throwaway.db
export PALIMPSEST_BUDGET_LOG=/tmp/seed_refresh_budget.jsonl
set -a; . ./.env; set +a          # OPENROUTER_API_KEY из .env (sk-or-…)
uv run python -m palimpsest.webapp.seed   # 15 абзацев, 0 baseline-score'ов, модель-реестр 8 строк
```

### B1: запуск локального инстанса

```bash
PALIMPSEST_DB=/tmp/seed_refresh_throwaway.db \
PALIMPSEST_BUDGET_LOG=/tmp/seed_refresh_budget.jsonl \
OPENROUTER_API_KEY=$OPENROUTER_API_KEY \
uv run uvicorn palimpsest.webapp.app:app --port 8011 --workers 1
```

(`--workers 1` обязателен — single-writer lock.) Инстанс несёт активные капы `budget.py` ($2 / 200 вызовов) и suggestion-guard (после мерджа).

### B2: прогон judge по 15 абзацам × 5 критериев

Для каждого `paragraph.id` в БД (15 штук) один HTTP-вызов, который внутри гоняет 5 критериев:

```bash
for pid in $(curl -s localhost:8011/api/documents/1 | python -c \
    'import sys,json;[print(p["id"]) for p in json.load(sys.stdin)["paragraphs"]]'); do
  curl -s -X POST localhost:8011/api/paragraphs/$pid/evaluate -H 'content-type: application/json' -d '{}'
  sleep 1
done
```

- **Ожидаемые вызовы OR:** 15 × 5 = **75 первичных**. С `EVAL_RETRIES=2` — ретраи только на transient (429/5xx/timeout), одной резервацией; типично +0..10.
- **Оценка стоимости:** RU-абзац ~1.5–3 kB → `count_tokens` (UTF-8-байты, консервативно) ~2–3k prompt-токенов; вывод ~300–600. На `gpt-5.4-mini` ≈ **$0.003–0.006 за вызов** → **75 × ≈ $0.005 ≈ $0.35–0.45**, под капом $0.5 из спеки и глубоко под hard-cap $2.
- **Гейт:** `curl localhost:8011/api/budget` до/после — `spentUsd` не должен превысить ~$0.5; если у кап-стоп (`BudgetExceeded`) — остановиться, `POST /api/budget/reset` не делать (расследовать).

### B3: экспорт scores/issues из БД → seed JSONL

**Файлы:** Create `scripts/export_baselines.py` (read-only к throwaway-БД, write к seed JSONL). Для каждого абзаца сопоставляет `paragraph.source` ↔ seed-запись, читает `score` (`kind='seed'`? нет — здесь `kind='live'` от `/evaluate`; берём последние `live`) и `issue` строки, собирает крит-блоки в форму seed JSONL:
`{<crit>: {final_score: value, summary, identified_issues:[{problematic_fragment: target_fragment, source_fragment, explanation, suggestion}]}}`.

**Важно:** `/evaluate` пишет `kind='live'`, а `seed.py` при финальном ресиде ждёт baseline в JSONL и сам проставит `kind='seed'`. Экспортёр читает `live`-строки (свежие оценки) и укладывает их как baseline в JSONL — семантически это и есть новый baseline.

Guard в экспортёре: если у абзаца нет score по какому-то из 5 критериев → печать предупреждения (критерий провалился на всех ретраях). Решение — повторить B2 точечно (`{"criterionIds":["style"]}`) для этого абзаца.

### B4: budget-лог → evidence

```bash
cp /tmp/seed_refresh_budget.jsonl \
   docs/reports/e2e/2026-07-02-seed-refresh-budget.jsonl
```

(Дефолтный путь gitignored — evidence-конвенция; каталог `docs/reports/e2e/` существует.)

**Проверка Phase B:** снять xfail с `test_each_has_baseline` и `test_advice_free`; `uv run pytest tests/test_seed_refresh.py -q` → green. Остановить uvicorn, удалить throwaway-БД (одноразовая).

**Коммит Phase B:** `feat(seed): regenerate baselines via local evaluate under budget+guard`.

---

## Phase C — регенерация терминологии (ОРКЕСТРАТОР + сабагенты)

> **ЭТО НЕ СКРИПТ ЦЕЛИКОМ.** Шаги C1/C4/C6 — скрипты; шаги **C3 (grounding G3) и C5 (pairing P3) выполняет ОРКЕСТРАТОР, диспетчеризуя сабагенты** (Sonnet, `temperature=0`, structured output), как в историческом G3/P3-прогоне. OR-обвязки для этих судей не существует и не пишется. Скрипты только сериализуют вход и собирают выход сабагентов.

`cwd=/Users/a1111/Projects/Work/worktrees/seed-refresh`, `.env` подгружен.

- [x] **C1** — done: 15 haiku-4.5 calls, `MAX_CALLS` 20→15, `data/seed/extracted_surfaces.json`/`lemmas.json`/`reports/terminology/extract_llm_calls.jsonl` regenerated.
- [x] **C2** — done: `terminology_terms.jsonl` (204 mentions) + `demo_grounding_inputs.json` regenerated.
- [x] **C3** — done: orchestrator-judged G3 grounding, `reports/terminology/g3_groundings.json` (137 lemmas: 40 green/14 yellow/83 red).
- [x] **C4/C5** — done, with a deviation: `scripts/emit_judge_inputs.py` turned out to be a golden-corpus tool keyed to OLD seed ids (pre-dates this rebuild), not usable as-is for the new 15-paragraph demo seed. The orchestrator built `reports/terminology/p3_inputs.json` directly (same `{surface, context, target, canon_en}` shape) instead of running that script, then judged pairing from it → `reports/terminology/judgments_pairing.json` (59 surfaces: 53 green/6 yellow, `target_surface` verified verbatim against the real translated text).
- [x] **C6** — done: `scripts/rebuild_demo.py` → `data/seed/terminology_out.json` (204 terms; difficulty {green:62, yellow:31, red:111}; pairAccuracy {green:86, yellow:7, null:111}, P3 overlaid on 93 occurrences). Adapter implemented as a new standalone `scripts/load_terms_into_seed.py` (not a `rebuild_seed_texts.py` flag) — writes only `terminology.identified_terms` per paragraph, verified by diff to leave `source`/`translated`/all 5 criterion blocks untouched.

### C1: extraction (реальный OR, haiku) — СКРИПТ

Спека §3: подтянуть `MAX_CALLS`/`--max-usd` к 15/0.2.

**Файлы:** Modify `scripts/term_pipeline.py` — `MAX_CALLS = 20 → 15` (первичных = число абзацев = 15); default `--max-usd 0.20` уже стоит.

```bash
uv run python scripts/term_pipeline.py extract --dry-run     # печатает 15 намеренных вызовов, $0
uv run python scripts/term_pipeline.py extract --real --max-usd 0.2
# → data/seed/extracted_surfaces.json, data/seed/lemmas.json,
#   reports/terminology/extract_llm_calls.jsonl
```

- Вызовы: **15** haiku-4.5, оценка **~$0.01** (спека), гейт `--max-usd 0.2` + credits-delta проверка в скрипте (mid-batch на i=7 и последнем).
- Модель по умолчанию `anthropic/claude-haiku-4.5` (winner турнира).

### C2: mentions — СКРИПТ

```bash
uv run python scripts/term_pipeline.py mentions   # → data/seed/terminology_terms.jsonl
uv run python scripts/emit_demo_grounding.py       # → reports/terminology/demo_grounding_inputs.json
```

`emit_demo_grounding.py` дергает live-Wikidata кандидатов (`WikidataClient`, кеш/User-Agent/maxlag/Retry-After — этикет в коде; ~свежие вызовы, бесплатно).

### C3: grounding G3 — **ОРКЕСТРАТОР (сабагент)**

Оркестратор читает `reports/terminology/demo_grounding_inputs.json` (список `{lemma, surface, context, candidates:[{qid,label,description}]}`) и диспетчеризует сабагент(ы), которые для каждого distinct lemma:
- выбирают лучший `qid` из кандидатов (или none),
- ставят `difficulty` 🟢/🟡/🔴 по контексту (античный vs современный смысл, гомонимы),
- пишут результат в `{lemma: {qid, difficulty}}`.

**Выход (пишет оркестратор/сабагент):** `reports/terminology/g3_groundings.json`.
**Объём:** ~190 вызовов сабагентами (спека), ≈$0 в OR-бюджете. Отметить в плане выполнения как orchestrator-step, НЕ как shell-скрипт.

### C4: pairing-вход — СКРИПТ

```bash
uv run python scripts/emit_judge_inputs.py   # → reports/terminology/judge_inputs.json
```

(Секция `pairing`: `{surface, context, target, canon_en:[…]}`.)

### C5: pairing P3 — **ОРКЕСТРАТОР (сабагент)**

Оркестратор читает секцию `pairing` из `judge_inputs.json` и диспетчеризует сабагент(ы): для каждого term решают, отрендерил ли перевод канонический EN-эквивалент — `verdict` 🟢/🟡/🔴 + `target_surface` + `recommended`.

**Выход:** `reports/terminology/judgments_pairing.json` = `{surface:{verdict, target_surface, recommended}}`.
**Объём:** ~78 вызовов сабагентами, ≈$0. Orchestrator-step.

### C6: сборка `Term[]` + адаптер в seed JSONL — СКРИПТ

```bash
uv run python scripts/rebuild_demo.py   # G3 grounding + P1 baseline, P3 overlaid → data/seed/terminology_out.json
```

`rebuild_demo.py` уже: red-null-rule, `pair_from_forms` (P1), overlay P3 из `judgments_pairing.json`.

**Адаптер `Term[]→identified_terms` (спека §4):** расширить `scripts/rebuild_seed_texts.py` (или отдельный `scripts/load_terms_into_seed.py`) — прочитать `terminology_out.json`, для каждого абзаца собрать `terminology.identified_terms = [{source_term: sourceSurface, translation_used: targetSurface, domain: note} for t in terms]` и записать в соответствующую запись seed JSONL (ключ — `id`↔seed-`id` через `source`-мэтч, как в `load_terms.py:db_by_source`). Реальные `pairAccuracy` вытесняют placeholder-ротацию `[i%3]` (та остаётся мёртвой для демо-документа, `seed.py` не трогаем).

**Проверка Phase C:** снять xfail с `test_real_terms`; полный `uv run pytest tests/test_seed_refresh.py -q` → green.

**Коммит Phase C:** `feat(seed): regenerate terminology (haiku extract + subagent G3/P3 grounding/pairing)`.

**Финальная локальная валидация (критерий успеха §1):**
```bash
rm -f data/demo.db
uv run python -m palimpsest.webapp.seed              # чистая БД из нового JSONL
uv run python scripts/load_terms.py                  # реальные термины в term-таблицу
uv run python -c "import sqlite3;c=sqlite3.connect('data/demo.db');\
print('paras',c.execute('select count(*) from paragraph').fetchone()[0]);\
print('seed_scores',c.execute(\"select count(*) from score where kind='seed'\").fetchone()[0]);\
print('terms',c.execute('select count(*) from term').fetchone()[0])"
```
Ожидание: 15 абзацев, 5×15=75 seed-score'ов, реальные термины, 0 advice-issue (guard), 0 кириллицы.

---

## Phase D — деплой + rollback (литеральные команды)

> Выполняется **после** мерджа settings-rework и suggestion-guard в `feat/seed-refresh` и ребейза. Прод-контейнер `gse-demo` (см. webapp.md §Production container).

### D0: supersession-правка §4 (отклонение №1)

**Файлы:** Modify `docs/superpowers/specs/2026-07-02-settings-rework.md` §4 — добавить forward-ссылку: «Исключение: `feat/seed-refresh` — единственный разрешённый полный ресид (данные меняются целиком); после него точечная политика возвращается. См. [seed-refresh spec](2026-07-02-seed-refresh.md).» **Тем же коммитом**, что и деплой-артефакты. Если файла нет (не влит) — СТОП, вопрос владельцу.

### D1: pre-check (ключ на месте)

```bash
docker exec gse-demo env | grep -c OPENROUTER_API_KEY    # == 1, иначе СТОП (ресид сотрёт ключи model-строк)
```

### D2: бэкап

```bash
cp /opt/gse-demo/data/demo.db /opt/gse-demo/data/demo.db.bak
```

### D3: ресид (флаг через `-e` — обязателен)

```bash
docker exec -e PALIMPSEST_SEED_DEMO=1 gse-demo python -m palimpsest.webapp.seed
```

(`PALIMPSEST_SEED_DEMO` нет в базовом env контейнера → идёт через `-e`; `OPENROUTER_API_KEY` уже в env, `-e` не нужен. Это же закрывает курацию vLLM-строк.) **Отклонение №2:** зависит от того, что settings-rework научила `seed.py` читать флаг; если не читает — СТОП. При необходимости после ресида — `docker exec gse-demo python scripts/load_terms.py` для реальных терминов (если образ несёт `scripts/`; иначе термины из seed JSONL через адаптер C6 уже в БД).

### D4: рестарт (обязательный)

```bash
docker restart gse-demo
```

(Запущенный uvicorn держит fd удалённого inode и без рестарта отдаёт старую БД — то же верно для отката.)

### D5: проверки

```bash
curl -s https://gse-translation.ru/api/documents            # 15 абзацев
curl -s https://gse-translation.ru/api/models               # 5 строк? (реестр; ключи маскированы first-4+…)
curl -s -X POST https://gse-translation.ru/api/paragraphs/<pid>/evaluate \
     -H 'content-type: application/json' -d '{"criterionIds":["accuracy"]}'   # живой evaluate 1 критерия
```
Судьи не должны флагать русские слова (0 кириллицы). Копия budget-лога прода → `docs/reports/e2e/2026-07-02-seed-refresh-budget.jsonl` (append) для итогового отчёта стоимости.

### D6: Rollback

```bash
cp /opt/gse-demo/data/demo.db.bak /opt/gse-demo/data/demo.db
docker restart gse-demo                                     # обязателен (тот же fd/inode эффект)
curl -s https://gse-translation.ru/api/documents            # проверки по СТАРЫМ ожиданиям (16 абзацев)
```
Загрузки пользователей, сделанные между ресидом и откатом, теряются — принято (одноразовые).

**Коммит Phase D:** `docs(seed): supersession note + deploy runbook + budget evidence`.

---

## Критерии успеха (маппинг на фазы)

1. Чистая БД после `python -m palimpsest.webapp.seed`: 15 абзацев, 0 кириллицы, реальные термины (`target_surface`/`pair_accuracy` из пайплайна), baseline всех 5 критериев, advice-suggestion=0 → **Phase A/B/C + финальная валидация**.
2. Прод после ресида+рестарта: судьи не флагуют русские слова; реестр 5 строк; живой evaluate проходит → **Phase D5**.
3. Отчёт с фактической стоимостью из `docs/reports/e2e/2026-07-02-seed-refresh-budget.jsonl` → **Phase B4 + D5**.

## Оценка стоимости (refined)

| Этап | Вызовы | Модель | Оценка $ |
|---|---|---|---|
| Phase B judge | 75 первичных (+ретраи ≤ +10) | gpt-5.4-mini | **$0.35–0.45** (< $0.5 кап) |
| Phase C extraction | 15 | claude-haiku-4.5 | **~$0.01** |
| Phase C grounding (G3) | ~190 сабагентами | Sonnet subagent | **≈$0** (вне OR-бюджета) |
| Phase C pairing (P3) | ~78 сабагентами | Sonnet subagent | **≈$0** |
| Wikidata | ~200 свежих | — | **$0** (кеш+этикет) |
| Phase D prod evaluate | 1 (проверка) | gpt-5.4-mini | **~$0.005** |
| **Итого OR-бюджет** | | | **≈ $0.36–0.47** |
