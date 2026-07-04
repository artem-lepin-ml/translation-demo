# Goal — Term Pairing module (`pairAccuracy` signal), autonomous overnight

**Дата:** 2026-07-01
**Сценарий:** B (autonomous, без вопросов Артёму)
**Бюджет:** ~8 часов wall-clock · токенов не жалеть
**Спонсор:** Артём (R&D lead)
**Branch:** `feat/term-pairing` от `feat/demo` (через `.claude/skills/superpowers/using-git-worktrees/SKILL.md`)
**Железо:** GPU (CUDA) есть · живой публичный API Wikidata/Wikipedia разрешён

Документ — input для агента, который проснётся ночью и работает по сценарию B (8 шагов из [CLAUDE.md](../../CLAUDE.md)). Ключевые решения зафиксированы в §2 — не передумывать. Любую ambiguity решать своим judgment и фиксировать в spec/plan.

Up-link: docs/pipeline.md (документ в ветке `old-gse-translating`). Контракт `Term`/`WikidataRef`: [docs/superpowers/specs/2026-06-30-demo-contracts.md](../superpowers/specs/2026-06-30-demo-contracts.md) §1. Исследование-основа: docs/experiments/2026-07-01-pairing-research.md (документ в ветке `old-gse-translating`; сохранить туда research Doc 1 при старте).

**Пара к grounding-циклу:** [2026-07-01-grounding-overnight.md](2026-07-01-grounding-overnight.md). Этот цикл делает **вторую половину** `Term` — `pairAccuracy`/`targetSurface`/`recommended`. Grounding (QID термина) здесь **дан** из golden-set (стаб), чтобы циклы были независимы и запускались параллельно в разных worktree.

**Роутинг моделей (жёстко):** спеки, план, ВСЕ решения, построение golden-set, осмотр данных, агрегация, финальный отчёт и решение о прунинге — **Opus** (`model: opus`, effort high→xhigh). Весь код стратегий, тесты, e2e-харнесс, документация — **Sonnet** (`model: sonnet`, medium→high). Рекон/grep/механика — **Haiku**. Правило R1: сабагенты НЕ наследуют модель — ставить `model:` явно.

---

## 1. Цель (one sentence, measurable)

Построить модуль **пары термина** — вход: RU-оригинал + текущий EN-перевод абзаца + список grounded-терминов (сущность + её Wikidata-QID из golden), выход: для каждого термина `targetSurface` (что реально использовал перевод) + сигнал `pairAccuracy` (🟢 адаптация верна / 🟡 приемлемо-но-спорно / 🔴 неверно или потеряно; `null` когда difficulty=🔴) + `recommended` (каноничный EN-эквивалент, если 🟡/🔴) ровно по типу `Term` §1 — реализовав **экстрактор терминов из RU** + **3 полные стратегии пары + 1 stretch** как swappable за одним интерфейсом, прогнав их на **всех** seed-абзацах против golden-set, и выбрав лучшую по accuracy/латентности с числовым сравнением.

Артефакты `src/palimpsest/terminology/pairing/` + `reports/pairing/*` + HTML `docs/reports/2026-07-01-pairing.html` готовы к утреннему ревью.

## 2. Зафиксированные решения — НЕ передумывать

| # | Решение | Резон |
|---|---------|-------|
| 1 | Модуль живёт в **`src/palimpsest/terminology/pairing/`**; тонкий CLI-враппер `scripts/term_pair.py` | «One stage = one module + скрипт». Отдельный субпакет — нет конфликта с `grounding`-веткой на мёрдже. |
| 2 | Интерфейс: `PairingStrategy.pair(PairRequest) -> list[PairResult]` (Protocol в `pairing/base.py`). `PairRequest{paragraph_id, source(RU), target(EN), grounded_terms: list[GroundedTerm]}`; `GroundedTerm{surface, char_start, char_end, qid, canon_en, aliases_en, difficulty}`; `PairResult{source_surface, char_start, char_end, target_surface\|null, pair_accuracy ∈ {green,yellow,red}\|null, recommended\|null, latency_ms, n_api_calls, trace}` | Одна абстракция, стратегии взаимозаменяемы; `trace` — для аудита/HTML. `grounded_terms` даны (стаб grounding). |
| 3 | Выход строго по контракту §1: `pair_accuracy` = `null` **тогда и только тогда**, когда `difficulty='red'`; иначе ∈ {green,yellow,red}. `recommended = null` при 🟢, непустой при 🟡/🔴. Одна `PairResult`-строка на каждое вхождение термина | Чтобы модуль без переделки писал в `Term` и в `POST /terms`. Правило null из контракта §«Два сигнала». |
| 4 | **Экстракция терминов из RU — часть этого модуля** (`pairing/extract.py`): RU-абзац → список упоминаний с char-спанами. Оценивается отдельно (P/R/F1 vs golden). Grounding (QID) к извлечённым НЕ делаем — берём из golden-стаба | Прямо просьба Артёма: «извлекает из оригинала все термины». Держим независимость от grounding-цикла: QID даны. |
| 5 | **Verdict-логика pairAccuracy** (единая, `pairing/verdict.py`): 🟢 = target_surface совпал с каноничным EN-эквивалентом QID (label/alias/sitelink) точно или Jaro-Winkler ≥0.9; 🟡 = найден правдоподобный, но нестандартный вариант (иная транскрипция/синоним/частичное совпадение 0.7–0.9) ИЛИ неоднозначно; 🔴 = термин в переводе не найден / использован неверный эквивалент (<0.7) → `recommended` = каноничный EN | Совпадает с определением сигнала. Порог общий; стратегии отличаются тем, КАК находят `target_surface`. |
| 6 | **Каноничный EN-эквивалент** берём из Wikidata по QID: `labels.en` + `aliases.en` + заголовок enwiki sitelink; живой API вежливо (UA, `maxlag=5`, ≤3 конкурентных, батч `wbgetentities` ≤50, `Retry-After`, локальный кеш `reports/pairing/wikidata_cache.jsonl`) | Из research Doc 1 §link-locate. Кеш = воспроизводимость/скорость. Совпадает с etiquette grounding-цикла. |
| 7 | **Все LLM-вызовы — через субагента, не через внешний API.** Модуль НЕ импортирует `openai`/не зовёт `LLMClient` — принимает **инъектируемый** `judge: Callable[[Prompt], StructuredOut]`. Ночной харнесс подставляет реализацию на **субагенте** (`model: haiku` для экстракции/дешёвого, `model: sonnet` для judge-пары), `temperature=0`, structured output. Прямое требование Артёма + держит Hard Invariant #6 чистым (в `src/` нет LLM-зависимости) | Дёшево, детерминированно, swappable: в проде тот же `judge` завести на `LLMClient` без правки стратегии. |
| 8 | Golden-set строит **Opus**, руками, **не циркулярно**; для каждого термина: правильный `target_surface` в данном переводе, правильный `pair_accuracy`, каноничный EN (`recommended`), сверка независимым источником | Иначе circular validation. |
| 9 | `factowl/` не трогать; `data/raw/` не трогать; ветку `artem` и прод не трогать; `glossary/main.json` — read-only reference | Hard Invariants #7/#9 + правила проекта. |
| 10 | **Не** реализуем grounding-логику (поиск QID из текста) — QID дан. Тут только `pairAccuracy`-половина `Term` | Чёткое разделение двух ночных циклов. |
| 11 | **Каждый подход независим и проходит свой gate.** Подход «принят» ⇔ (a) его unit/integration/e2e-тесты зелёные И (b) независимый **audit-агент** (fresh context, `model: sonnet`, ≠ автор кода) дал PASS. Аудит проверяет: пересчёт метрик из сырых `results_*.jsonl`; качество кода (идиоматичность, изоляция, обработка ошибок); сложные/edge-кейсы (термин потерян в переводе, множественные вхождения, транслитерация vs перевод, морфология EN, difficulty=red→null); полноту документации. FAIL по любому пункту → подход не «зелёный» | Требование Артёма: подход валиден только если реально работает и подтверждён со стороны. Аудитор ≠ автор (анти-круговая проверка). |
| 12 | **Общий интерфейс и харнесс — ПЕРВЫМИ**, до любой стратегии: `base.py` + `extract.py`-контракт + `runner.py` + `eval_harness.py` + audit-контракт фиксируются и замораживаются; стратегии пишутся строго под них, параллельно и независимо | Требование Артёма «предварительно спроектировав общие интерфейс и харнесс». Замороженный контракт = стратегии сравнимы 1:1. |
| 13 | **Финальное сравнение с прошлой веткой `feat/glossary-overnight`** (`glossary/main.json`: RU-ключ → `{ru,en,strategy,source,notes}`). Для каждого термина: совпал ли наш `recommended` с глоссарным `en`; согласуется ли реальный `target_surface` перевода с глоссарным эквивалентом; что нашёл наш модуль сверх глоссария | Артём: «сравни результаты с тем, что я уже делал в другой ветке». Глоссарий — reference, не golden. |

## 3. Скоуп

### IN — обязательно к утру

**Код (`src/palimpsest/terminology/pairing/`):**
- `base.py` — `PairRequest`, `GroundedTerm`, `PairResult`, `PairingStrategy` (Protocol). Проектируется первым (§2.12).
- `extract.py` — экстрактор RU-терминов (§2.4): даёт упоминания с char-спанами. Реализация — инъектируемый `judge` (субагент `model: haiku`, structured output список спанов) ИЛИ детерминированный (spaCy `ru_core_news_lg` NER + capitalized-token эвристика); выбрать в спеке, зафиксировать. Оценивается P/R/F1.
- `verdict.py` — общая verdict-логика pairAccuracy + Jaro-Winkler пороги (§2.5); правило null при difficulty=red (§2.3).
- `wikidata.py` — каноничный EN по QID: `wbgetentities` (labels/aliases.en + sitelinks.enwiki), батч ≤50; UA/maxlag/Retry-After/кеш (§2.6). (Тонкий; можно переиспользовать логику из grounding-ветки после мёрджа, но здесь — своя копия, ветки независимы.)
- `strategies/link_locate.py` — **P1 (дефолт, Pattern B).** По QID → каноничный EN + алиасы + sitelink → локализовать в EN-переводе (exact → Jaro-Winkler≥0.9 по словам/n-граммам) → verdict. Не нашли → 🔴 + recommended. Из research Doc 1 §Pattern B.
- `strategies/extract_align_link.py` — **P2 (GPU, полная, Pattern A).** Bertalign (LaBSE) выравнивает предложения RU↔EN → SimAlign/awesome-align (mBERT/XLM-R) даёт слово-в-слово → маппит RU-спан термина в EN-спан → сверяет EN-спан с каноничным эквивалентом QID → verdict. Из research Doc 1 §Pattern A.
- `strategies/llm_judge.py` — **P3.** Инъектируемый `judge` (субагент `model: sonnet`): вход — RU-термин + контекст-предложение + EN-перевод + каноничные эквиваленты QID; выход structured `{target_surface, verdict, recommended, reason}`. Стратегия НЕ импортирует LLM-клиент.
- `strategies/term_consistency.py` — **P4 (stretch/baseline).** Term Consistency (Semenov & Bojar, WMT 2022) для доменных терминов, которых нет в Wikidata: проверяет, что перевод рендерит один и тот же RU-термин единообразно по всем вхождениям. Помечать «не Wikidata-grounded».
- `runner.py` — прогон любой стратегии по списку `PairRequest`; сбор `PairResult` + trace.
- `eval_harness.py` — **проектируется первым** (§2.12): читает `results_<strategy>.jsonl` + golden → все метрики §4 → `metrics.json`. Один харнесс на все стратегии.

**Данные (committed под LFS в `reports/pairing/` и `data/seed/`):**
- `data/seed/pairing_gold.jsonl` — golden-set (Opus): `{paragraph_id, source_surface, char_start, char_end, gold_qid, gold_target_surface, gold_pair_accuracy ∈ {green,yellow,red,null}, gold_recommended, category, source_url, notes}`. ≥ **40** записей на 16 seed-абзацах, non-circular (§2.8). Термины с difficulty=red → `gold_pair_accuracy=null`.
- `reports/pairing/wikidata_cache.jsonl` — кеш ответов API.
- `reports/pairing/results_<strategy>.jsonl` — строка на (термин × стратегия): target_surface/pair_accuracy/recommended/latency/n_api_calls.
- `reports/pairing/extract_eval.json` — P/R/F1 экстрактора vs golden-спаны.
- `reports/pairing/metrics.json` — все метрики §4.
- `reports/pairing/audit_<strategy>.md` — вердикт независимого audit-агента (§2.11): PASS/FAIL + пересчёт метрик + замечания.
- `reports/pairing/vs_glossary.json` — сравнение с `feat/glossary-overnight` (§2.13).

**Docs:**
- `docs/stages/term-pairing.md` — по формату CLAUDE.md (Purpose, Design decisions, Interface, Subtleties, Status), ссылка на контракт и research.
- `docs/pipeline.md` — раздел «Term pairing (pairAccuracy)» + линк.
- CLAUDE.md routing — строка «Пара терминов | docs/stages/term-pairing.md».
- `docs/known_issues.md` — грабли: word-alignment на дальних парах RU↔EN, транслитерация vs перевод, морфология EN, термин опущен в переводе, многословные термины.

**Tests:**
- unit на `verdict.py` (все ветки + null-правило при difficulty=red), Jaro-Winkler порогах, `extract.py` (спаны на синтетике).
- integration: каждая стратегия на 5 «якорных» парах даёт ожидаемый verdict (Месопотамия↔Mesopotamia→green; лугаль↔"lugal" транслит→yellow; термин опущен→red+recommended).

**E2E (обязательно, руками осмотреть):**
- прогнать **лучшую** стратегию (+ grounding-стаб из golden) на всех 16 seed-абзацах → записать `targetSurface/pairAccuracy/recommended` в `Term`-строки (`data/seed/pairing_out.json`), подгрузить в демо и **открыть в браузере** (`#/a` — точки пары на RU↔EN + `TermPopover` с pairAccuracy): убедиться глазами, что 🟢🟡🔴 и `recommended` осмысленны. ≥ **6 скриншотов** в `reports/pairing/shots/`. Провенанс — только seed-данные.
- замерить и показать **скорость** (латентность/термин, p50/p95) и **точность** (vs golden) — прямое требование Артёма.

### OUT — НЕ делать
- grounding/поиск QID из текста — QID дан из golden (это grounding-ветка).
- `difficulty`-сигнал — чужая половина `Term`.
- Произвольные языковые пары на реальных данных: архитектура язык-агностична, но e2e на RU→EN. В отчёте — раздел «как обобщается».
- Локальный дамп Wikidata (живой API разрешён).
- Не применять к прод-сайту, не трогать `feat/demo` кроме мёрджа.

## 4. R&D-эксперимент: стратегии + метрики

### Экстрактор + 4 стратегии пары, прогоняются на ВСЕХ seed-абзацах
- Экстрактор — один, общий, оценивается P/R/F1 (§3 `extract_eval.json`).
- **P1 link_locate** (дефолт), **P2 extract_align_link** (GPU, полная), **P3 llm_judge** (полная, субагент), **P4 term_consistency** (stretch/baseline).
- Если P2 (нейро-выравниватель) не поднимается за разумное время — задокументировать причину, оставить P1/P3 полными + P4, НЕ выкидывать молча.

### Метрики (в `reports/pairing/metrics.json`)
- **Extraction P/R/F1** vs golden-спаны (один раз, общий экстрактор).
- **Locate/alignment accuracy**: доля, где предсказанный `target_surface`-спан совпал с golden (exact + overlap≥0.5) — per strategy.
- **pairAccuracy verdict accuracy**: confusion-matrix 🟢🟡🔴(+null) vs `gold_pair_accuracy` + macro-F1 — per strategy.
- **recommended correctness**: на 🟡/🔴 — доля, где `recommended` совпал с каноничным EN (Jaro-Winkler≥0.9) — per strategy.
- **Coverage**: доля терминов с non-null `target_surface` — per strategy.
- **Латентность**: p50/p95/max мс на термин + среднее `n_api_calls` — per strategy (кеш прогрет/холодный отдельно).
- **Pairwise agreement** по `pair_accuracy` между стратегиями.
- **Per-category breakdown** по `category`.

### Golden-set: как Opus строит
Для каждого термина из seed-абзацев: найти в EN-переводе, что реально использовано (`target_surface` или пусто), решить verdict (🟢 верная адаптация; 🟡 нестандартно-но-ок; 🔴 неверно/потеряно), записать каноничный EN как `recommended`, сверить независимым источником. Golden НЕ совпадает с выводом одной стратегии by construction.

### Порядок: сначала контракт, потом стратегии (§2.12)
1. Заморозить `base.py` + `extract.py`-контракт + `runner.py` + `eval_harness.py` + формат `results_*.jsonl` + audit-контракт (Opus спека → Sonnet каркас → быстрый прогон на 2-3 терминах). 2. Только после — стратегии, каждая своим Sonnet-агентом, параллельно и независимо.

### Per-approach gate (§2.11) — каждый подход проходит сам
Подход **P_i принят** ⇔ ОБА:
- **e2e/тесты зелёные:** unit + integration (5 якорных пар) + прогон на всех seed-терминах без падений, схематически валиден.
- **audit-агент = PASS:** отдельный субагент (`model: sonnet`, fresh context, ≠ автор) по коду + `results_<strategy>.jsonl` + golden проверяет 4 оси:
  1. **Метрики** — пересчитывает locate/verdict-F1/recommended/coverage/latency, сверяет с `metrics.json` (расхождение → FAIL).
  2. **Качество кода** — идиоматичность, изоляция через интерфейс, обработка ошибок (alignment вернул пусто, API-таймаут/429, term не найден), нет прямых `openai`-импортов.
  3. **Сложные/edge-кейсы** — термин опущен в переводе (→red+recommended), множественные вхождения (per-occurrence), транслитерация vs перевод (→yellow), морфология EN (kings/king's), difficulty=red→pairAccuracy=null, многословный термин.
  4. **Документация** — стратегия в стейдж-доке, интерфейс совпадает с кодом, subtleties не пусты.
- FAIL по любой оси → подход НЕ зелёный: Opus чинит (шаг 7) или обрезает с записью причины → `audit_<strategy>.md`.

### Сравнение с `feat/glossary-overnight` (§2.13)
Загрузить `glossary/main.json` из ветки `feat/glossary-overnight`, сматчить по RU-термину: совпал ли наш `recommended` с глоссарным `en`; согласуется ли `target_surface` перевода с глоссарным эквивалентом; сколько терминов наш модуль разметил сверх глоссария. Результат → `vs_glossary.json` + раздел HTML. Глоссарий — reference, не golden.

## 5. Acceptance criteria — что Артём проверяет утром

### 5.1 Модуль и интерфейс
- [ ] `python -c "from palimpsest.terminology.pairing.base import PairingStrategy, PairRequest, GroundedTerm, PairResult; print('ok')"`.
- [ ] Все 4 стратегии импортируются и реализуют `pair()`; `python -c "from palimpsest.terminology.pairing import runner, extract; print('ok')"`.
- [ ] `verdict.py`: null-правило — тест, что difficulty=red ⇒ pair_accuracy=None (и наоборот pair_accuracy не None ⇒ difficulty≠red).

### 5.2 Данные и golden
- [ ] `data/seed/pairing_gold.jsonl` ≥ 40 записей, каждая с `gold_target_surface` (или пусто), `gold_pair_accuracy` ∈ {green,yellow,red,null}, `gold_recommended`, `category`, `source_url`. Auto-check: `python -c "import json; r=[json.loads(l) for l in open('data/seed/pairing_gold.jsonl')]; assert len(r)>=40 and all(x.get('source_url') and x.get('gold_pair_accuracy') in ('green','yellow','red',None) for x in r), 'gold invalid'; print(len(r))"`.
- [ ] Golden non-circular: в отчёте раздел «как строился golden» + независимый источник.

### 5.3 R&D эксперимент
- [ ] `reports/pairing/metrics.json` содержит ВСЕ метрики §4 для 4 (или задокументированно 3) стратегий + `extract_eval.json`. Auto-check: `python -c "import json; m=json.load(open('reports/pairing/metrics.json')); assert {'locate_accuracy','verdict_f1','recommended_correctness','coverage','latency','pairwise_agreement','per_category'} <= set(m), set(m); print('ok')"`.
- [ ] `results_<strategy>.jsonl` для каждой стратегии на всех терминах.
- [ ] Выбрана **лучшая стратегия** с письменным обоснованием (accuracy × латентность × стоимость); слабые удалены или помечены `# BASELINE — not default` с причиной. Решение — Opus, в отчёте.

### 5.3b Per-approach gate + аудит (§2.11)
- [ ] Для КАЖДОЙ принятой стратегии — `reports/pairing/audit_<strategy>.md` с PASS от независимого агента (≠ автор), 4 оси: метрики (пересчёт), код, edge-кейсы, документация.
- [ ] Ни одна «принята/дефолт» стратегия не имеет audit=FAIL. Обрезанные — с записанной причиной.
- [ ] Общий интерфейс/харнесс заморожены ДО стратегий (видно по коммитам: `base.py`/`runner.py`/`eval_harness.py`/`extract.py` раньше `strategies/*`).

### 5.3c Сравнение с прошлой веткой (§2.13)
- [ ] `reports/pairing/vs_glossary.json` существует; в HTML раздел «vs feat/glossary-overnight»: N пересечений, % совпадения `recommended`↔глоссарный `en`, что нашли сверх. Auto-check: `python -c "import json; d=json.load(open('reports/pairing/vs_glossary.json')); assert 'overlap' in d and 'recommended_match' in d; print('ok')"`.

### 5.4 E2E
- [ ] `data/seed/pairing_out.json` — `Term`-строки (targetSurface/pairAccuracy/recommended) для всех 16 абзацев от лучшей стратегии, подгружены в демо.
- [ ] ≥ 6 скриншотов браузера (`reports/pairing/shots/`): пара RU↔EN 🟢🟡🔴 + `recommended` в `TermPopover`; таблица «термин → target → verdict → recommended → скрин».
- [ ] Латентность и accuracy лучшей стратегии на реальном прогоне — числа в отчёте.

### 5.5 Docs
- [ ] `docs/stages/term-pairing.md` по формату; `docs/pipeline.md` + CLAUDE.md routing обновлены; `docs/known_issues.md` пополнен.

### 5.6 Report + PR
- [ ] HTML `docs/reports/2026-07-01-pairing.html` (тёмная тема, 360-радар, таблица сравнения стратегий, embed скриншотов, artifacts, раздел vs-glossary) + поднят локально на порту 8096+.
- [ ] Один PR `feat/term-pairing` → `feat/demo`; body на русском в стиле владельца (`feedback_pr_body_style`): таблица метрик locate/verdict-F1/latency по стратегиям + вывод «какая победила и почему».

## 6. Порядок исполнения (8 шагов сценария B)
1. Спека (Opus) в `docs/superpowers/specs/` из этого goal + research Doc 1 → `/verify-spec` (≥3 аспекта). 2. План (`writing-plans`). 3. Ветка+воркти `feat/term-pairing` от `feat/demo`. 4. **Заморозить каркас** (§2.12): `base.py`+`extract.py`-контракт+`runner.py`+`eval_harness.py`+audit-контракт (Opus спека → Sonnet код) — коммит РАНЬШЕ стратегий. 5. Golden-set (Opus, руками, с источниками). 6. Экстрактор + стратегии — параллельно, каждая своим Sonnet-агентом под замороженный интерфейс; сразу за каждой — **per-approach gate** (§2.11): тесты + independent audit-агент → `audit_<strategy>.md`. 7. `/verify-pr` (≥5 аспектов) + e2e-tester (браузер) + аудит e2e-отчёта. 8. Fix (`systematic-debugging`) провалов gate/verify. 9. Сравнение с `feat/glossary-overnight` (§2.13) + финальный e2e + docs-keeper + HTML-отчёт + PR. Не успел стратегию — честно в known-issues. Закончил рано — расширяй golden, гоняй больше кейсов, добавляй стратегию.
