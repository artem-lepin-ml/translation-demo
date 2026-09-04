# E2E: прод-стабилизация, итерация 1 — 2026-07-16

Адверсариальный прогон на LIVE PROD https://glossa-mt.com сразу после деплоя стабилизационной волны. Инструмент: `playwright-cli` (сессия `-s=stability-iter1`), напрямую в браузере, без API-шорткатов для действий пользователя (API использовался только для чтения baseline/финального состояния и верификации персиста).

Рабочая копия: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`. Манифест данных: `docs/testing/e2e-data.md` (прочитан первым действием).

## 1. Вердикт

**PASS-with-findings.** Все 7 заявленных «свежих фиксов» подтверждены живьём в браузере — красная точка на заземлённых терминах пропала, трассировка глоссария реальна, копия диалога Reset говорит «archived», Refine доступен со вкладки Scores, гонка переключения документов не даёт «протухшего» контента, паника из 184 console-ошибок при удалении документа не воспроизводится, кэш-клон корректно отличает точный дубликат от вайтспейс-правки. Но найдено 5 новых проблем (2 из них — реальные баги записи данных, не косметика), внутри которых расследование одной («adversarial dblclick») вскрыло, что мой собственный брутфорс-грид случайно принял реальную (не hidden) кнопку Accept и тем самым живьём прогнал весь improvement-loop — это не баг, а бесплатное подтверждение journey 4.

Итоговое состояние стенда полностью восстановлено до baseline (см. §6) — ни один seed-документ не тронут, все временные документы и тестовая registry-модель удалены, все настройки (6 ролей, веса судей, промпты) побайтово совпадают с исходными.

## 2. План сценариев и статус выполнения

| # | Сценарий | Статус |
|---|---|---|
| 1 | Picker: 3 карточки + Blank document, открыть каждый seed-документ | executed |
| 2a | Red-dot fix: заземлённый термин не красный | executed |
| 2b | Glossary trace: Matched + Grounding path stepper реальны | executed |
| 2c | Reset dialog copy: "archived", не "lost" | executed |
| 2d | Refine доступен со вкладки Scores | executed |
| 2e | Doc-switch race 1→13→10 x3 | executed |
| 2f | Upload + delete polling (без шторма 404) | executed |
| 2g | Clone-cache fallback: whitespace-правка идёт через реальный пайплайн | executed |
| 3 | Адверсариальный dblclick-репро скрытой Dismiss-кнопки | executed — не воспроизводится |
| 4 | Money shot: Refine §4 doc10 → Sealand, rescore, Restore, double-submit guard | executed |
| 5 | Evaluate + double-click guard | executed |
| 6 | Settings: все контролы (registry, judges, translator, grounding, refiner) | executed |
| 7 | Ranking: рендер, сортировка, консоль чистая | executed |
| 8 | Полный прогон: console sweep + клик по всему интерактивному | executed |

Не выполнялось: полноценный live-perf/security аудит (вне периметра задачи), повторный глубокий аудит точности заземления по всем 86 QID (уже задокументирован отдельно в памяти агента, не входил в список fresh-fix для этой волны).

## 3. Таблица шаг → данные → артефакт → вердикт

| Шаг | Данные (provenance) | Артефакт | Вердикт |
|---|---|---|---|
| Landing page | — | shots/01-landing.png | pass |
| Baseline config capture (GET /api/criteria, /translator-config, /grounding-config, /refiner-config, /models) | source: сам прод API до любых действий | текстовый вывод curl в тулинге | pass — совпадает с ожидаемым baseline из задания (6 ролей = gemini-3.1-flash-lite, refiner 4096/0.2, translator 2048/0.3, grounding 512/0, registry temp 0.7) |
| 1. Открыть doc1 (Mesopotamia) | source_file: docs/testing/e2e-data.md (seed doc) | shots/02-doc1-open.png | pass |
| 2a. Термин «Месопотамия» (QID Q11767) — попап | source: сам прод (термин из seed) | shots/03-doc1-term-mesopotamia-popover.png | pass — Difficulty = 🟡 Ambiguous (жёлтый), НЕ красный, при наличии QID |
| 1. Открыть doc13 (Qin State) | source_file: манифест, seed upload doc | shots/04-doc13-open.png, 04b-doc13-top.png | pass — рендер корректный; doc13 без scores (aggregate: null) — легитимное состояние (upload doc, живой Evaluate не запускался ранее), не баг |
| 2b. Glossary doc13, разворот жёлтой строки «Цинь» (QID Q7183) | source: сам прод | shots/06-doc13-glossary-expanded.png | pass — Matched=«label» (реальное значение), Grounding path SEARCH→CANDIDATES→EXACT→DECISION с реальными данными («wbsearchentities», «5 candidates found», «5 exact matches», «llm disambiguation») |
| 2c. Reset confirm dialog (doc1) | — | текст диалога в выводе тулинга (нативный confirm(), скриншот невозможен) | pass — «Reset the document to its seed state? Live scores and issues will be archived (hidden, not deleted); every paragraph reverts to its seed text.» Диалог отменён (Cancel), doc1 не тронут |
| 2d. Refine доступен со вкладки Scores (doc1 §1) | — | shots/10-scores-tab.png | pass — кнопка «Refine paragraph ✦» видна независимо от активной вкладки (Issues/Scores) |
| 2e. Doc-switch race 1→13→10 x3, быстрые select() | — | shots/11-docswitch-race-final.png + `console` = 0 errors | pass — финальный рендер соответствует выбранному doc10 (§1 Lagash, счёт 6.9), протухшего контента нет |
| 2f. Upload andrey_source_ru.txt/andrey_translation_en.txt (точный дубль doc10) | source_file: data/seed/demo_docs/andrey_upload_source_ru.txt, andrey_upload_translation_en.txt | shots/12,13,13b,14,14b,15 | pass — мгновенный клон из кэша (все 8¶ со scores «just now») |
| 2f. Удаление doc14 во время открытой страницы | — | `requests` лог (2× DELETE /api/documents/14, оба 204) | BUG-4 (LOW): двойной DELETE-запрос на одно нажатие подтверждения (см. §4) |
| 2g. Upload изменённая копия (двойной пробел в начале source) | GENERATED: rationale — манифест не содержит готовой «wайтспейс-варианта» фикстуры; правка получена детерминированно из andrey_upload_source_ru.txt вставкой одного пробела; файл сохранён в scratchpad, использован разово и удалён вместе с тестовым документом | shots/16,17 | pass — НЕ мгновенный клон («Extracting terminology…», «warming k/8 ¶…»), реальный асинхронный пайплайн, термины легли на верные символы |
| 2f/2g. Удаление doc15 во время активного warming | — | console.log: 2× `Failed to load resource 404 @ /api/documents/15`, застыло на 2 (не растёт) | BUG-5 (LOW): не «шторм 184», старый баг подтверждённо ПОЧИНЕН, но не идеально чисто — 2 фоновых 404 при удалении в процессе warming |
| 3. Адверсариальный dblclick-грид (357 точек, x:960-1280 y:95-400 на doc1 §1) | GENERATED координатная сетка на основе bounding box реальных элементов | shots/18,19 | SUSPECTED/расследовано — сетка задела РЕАЛЬНУЮ (не скрытую) кнопку Accept issue-1 → applied fix → rescore до 10.0/10.0/10.0. DOM-инспекция (elementFromPoint по сетке 5px, поиск нулевых/hidden кнопок) не нашла ни одной скрытой Dismiss-кнопки в зоне Refine/tabs. Репро НЕ воспроизводится |
| 3. Восстановление doc1 через document Reset | — | shots/20,21 | pass — текст/scores/issues побайтово вернулись к baseline (8.6/9.0/9.0/8.0, Accept all 55, все issues open) |
| 3-side. Revision History не обновился сразу после Reset (CURRENT показывал старую 10.0-ревизию) | — | shots/20 vs 21 (после reload) | SUSPECTED (LOW) — тот же паттерн staleness, что уже задокументирован для Restore в wave5-run.md §4.1, здесь распространяется и на Reset; лечится обновлением страницы |
| 4. Money shot: doc10 §4 baseline (Accuracy 5.0/Fluency 7.0/Style 9.0, agg 6.4) | source: сам прод, seed upload doc | shots/22,23,24 | pass |
| 4. Refine §4 (double-click guard) | — | `requests`: ровно 1× POST /paragraphs/61/refine, 1× /evaluate несмотря на 2 клика подряд | pass — inFlight guard держит |
| 4. Результат Refine | — | shots/25 | pass — «Primordial Lands» → «Sealand» (точно как предлагал accuracy-issue), Accuracy 5→7 (▲2.0), Fluency 7→8 (▲1.0), Style 9 (не менялся), agg 6.4→7.7 с бэйджем «prev 6.4» |
| 4. Restore к более старой ревизии | — | shots/26 | pass — текст вернулся к «Primordial Lands», показан баннер «Scores are for a previous version — press Evaluate» (см. SUSPECTED ниже) |
| 4. Reset doc10 (после Restore) | — | shots/27 | pass — §4 вернулся к 5.0/7.0/9.0, agg 6.4 (base 6.4), Accept all 19 — идентично baseline |
| 5. Evaluate §4 (double-click guard) | — | `requests`: ровно 1× POST /evaluate несмотря на 2 клика | pass |
| 5. Результат Evaluate | — | shots/28 | pass — 3 живых judge-скора (5.0/6.0/6.0), agg 5.1 (было 6.4, дельта красная — корректно, снижение) |
| 5. Финальный Reset doc10 (cleanup) | — | API GET agg=8.3, §4=6.44 | pass — восстановлено к исходному |
| 6. Settings overview, 5 секций | — | shots/29 | pass — Model Registry с 4 моделями, все temp 0.7, совпадает с baseline |
| 6. Judges: смена модели Accuracy → gemma → verify → revert | — | shots/30,31,32; GET /api/criteria до/после | pass — персист подтверждён, откат точный |
| 6. Judges: edit prompt (+trailing space) → save → verify → revert (побайтово) | — | shots/33; GET показывает len 7328→7329→7328, последние 5 символов идентичны исходным | pass |
| 6. Translator: смена модели → verify → revert; prompt edit → save → revert | — | shots/34; GET /api/translator-config | pass |
| 6. Grounding: смена модели → verify → revert | — | shots/35; GET /api/grounding-config | pass (модель) |
| 6. Grounding: prompt edit → **отсутствует Save/autosave** | — | shots/36 — нет кнопок Save/Revert рядом с textarea, GET после blur+3s показывает старый текст без изменений | **BUG-1 (MEDIUM-HIGH)** — см. §4 |
| 6. Refiner: смена модели → verify → revert; prompt edit → save → revert | — | GET /api/refiner-config до/после | pass |
| 6. Judges: Enabled-чекбокс Style off→on | — | GET /api/criteria enabled True/False/True | pass |
| 6. Judges: Weight spinbutton 0.4→0.5→0.4 | — | GET /api/criteria weight | pass |
| 6. Model Registry: Add с невалидным JSON в Params | GENERATED: строка "not json{{{" — намеренно битый JSON | shots/38 | pass — «Params must be valid JSON.», без креша |
| 6. Model Registry: Add с ПУСТЫМ Name + валидными Params | — | shots/39; GET /api/models — `{"name": ""}` | **BUG-2 (MEDIUM)** — см. §4 |
| 6. Cleanup: удаление nameless-модели | — | confirm-диалог «Delete ""?»; GET подтверждает удаление | pass (после фикса №2 будет недостижимо) |
| 6. Model Registry: Add валидной тестовой модели (дубликат gemini + суффикс) | GENERATED: `google/gemini-3.1-flash-lite-e2etest` — намеренно невалидный OpenRouter model ID для проверки реального провала Test | shots/40 | pass — создана, видна в таблице |
| 6. Edit params тестовой модели | — | shots/41,42; GET подтверждает {"max_tokens":256,"temperature":0.5} | pass сохранения; **BUG-3 (LOW, косметика)** — «Effective Params» превью в диалоге не обновляется при вводе |
| 6. Test-кнопка на тестовой модели (1 живой вызов) | — | shots/43 | pass — FAILED, реальная ошибка OpenRouter «not a valid model ID», Test действительно шлёт живой запрос |
| 6. Remove тестовой модели | — | GET /api/models — обратно 4 модели | pass |
| 7. Ranking: рендер | — | shots/45 | pass |
| 7. Ranking: сортировка по Aggregate | — | shots/46 | pass — стрелка, корректный порядок (null-строка §3 первая) |
| 7. Ranking: клик по строке → переход в Document + открытие параграфа | — | shots/47; console 0 errors | pass |
| 8. Export → Excel (.xlsx) | — | скачанный файл — валидный zip/xlsx (проверен структурой архива) | pass — имя файла `world-history-selected-passages-draft-translation-10.xlsx` |
| 8. Export → Markdown (.md) | — | скачанный файл — валидная GFM-таблица, 8 строк + заголовок | pass |
| 8. Terms chip toggle (вкл/выкл подсветку терминов) | — | shots/49 | pass |
| 8. Wikidata-ссылка (Lagash → Q207330) | WEB: https://www.wikidata.org/wiki/Special:EntityData/Q207330.json — подтверждено label=Lagash | — | pass — ссылка ведёт на корректный QID |
| 8. Escape закрывает Upload pair modal | — | shots/50 | pass |
| 8. Финальный console sweep за весь прогон | — | только benign `[VERBOSE] Password field is not contained in a form` (API Key поле в Model Registry) + два инцидента из BUG-4/5 | pass — реальных JS-ошибок ноль |

## 4. Найденные баги

### BUG-1 (MEDIUM-HIGH) — Grounding-промпт не сохраняется вообще
**Где:** Settings → 4. Grounding → Prompt.
**Репро:**
1. Открыть Settings, перейти в секцию Grounding.
2. Изменить текст в textarea Prompt (например, добавить пробел в конец).
3. Кликнуть в любое другое место (blur) или подождать несколько секунд.
4. `GET /api/grounding-config` — текст промпта не изменился.

**Причина по DOM:** `data-testid="grounding-editor"` содержит только `<select>` (Model) и `<textarea data-testid="grounding-prompt">` — никакой кнопки Save/Revert и никакого onChange-автосейва рядом нет (сравнить с соседней секцией Refiner, у которой есть «Save prompt»/«Revert»/счётчик символов/«Unsaved changes»). Пользователь визуально видит свою правку в textarea, думает, что она применилась (никакого предупреждения нет), но она никогда не долетает до сервера — тихая потеря данных.
**Влияние:** нельзя кастомизировать промпт дисамбигуации терминологии через UI вообще — единственная из 4 промпт-секций (Translator/Judges×3/Refiner все работают), где это не работает.

### BUG-2 (MEDIUM) — Model Registry принимает пустое имя модели
**Где:** Settings → 1. Model Registry → + Add model.
**Репро:**
1. Открыть форму Add model.
2. Оставить поле Name пустым, заполнить Params валидным JSON (например `{"max_tokens": 1536}`).
3. Save.

**Результат:** запись создаётся успешно (`POST` возвращает успех), в таблице появляется строка с пустым именем; `GET /api/models` подтверждает `"name": ""`. Диалог удаления такой записи показывает сломанный текст `Delete ""?`. Валидация JSON для Params работает («Params must be valid JSON.»), но для Name — нет.
**Влияние:** пользователь может создать «мусорную», неотличимую от других строку в реестре моделей, которая не соответствует ни одному реальному провайдер-ID и не может быть осмысленно идентифицирована в UI.

### BUG-3 (LOW, косметика) — «Effective Params» не обновляется вживую в диалоге Edit model
**Где:** Settings → Model Registry → Edit (любая модель).
**Репро:** открыть Edit, изменить Params JSON в textarea — блок «Effective Params» снизу продолжает показывать значения, актуальные на момент открытия диалога, даже после blur/Tab.
**Влияние:** только визуальное введение в заблуждение — реальное сохранение работает корректно (подтверждено через API), значения после Save правильные.

### BUG-4 (LOW) — Двойной DELETE-запрос на одно подтверждение удаления документа
**Где:** любой upload-документ, кнопка 🗑 в топ-баре.
**Наблюдение:** один клик по иконке удаления + одно подтверждение нативного confirm() → в network-логе видно ДВА последовательных `DELETE /api/documents/{id}` запроса, оба вернули 204. Не создаёт видимого вреда (идемпотентно), но указывает на двойную привязку обработчика/двойной вызов confirm-колбэка.

### BUG-5 (LOW) — Остаточные 404 при удалении документа в процессе warming
**Где:** удаление upload-документа, пока его фоновая задача scoring/warming ещё не завершена.
**Наблюдение:** после удаления в консоли появляются РОВНО 2 ошибки `Failed to load resource: 404 @ /api/documents/{id}` (poll-цикл догоняется и сам себя останавливает — не растёт дальше). Это НЕ регресс старого бага (184 ошибки, шторм, зависание UI) — тот баг подтверждённо починен. Но 0 ошибок было бы чище: poll-луп стоило бы обрывать сразу по успешному ответу DELETE, а не по следующему неудачному GET.

## 5. SUSPECTED / потенциальные проблемы (не баги, но стоит держать в поле зрения)

1. **Revision History не обновляется сразу после Document Reset** (не только после Restore, как уже задокументировано в `docs/reports/e2e/wave5-run.md` §4.1). После Reset строка CURRENT какое-то время показывает старую (уже неактуальную) ревизию с её старым скором; ручной reload страницы показывает корректный порядок. Расширяет уже известный «not always refresh immediately» баг с Restore на Reset — та же первопричина, вероятно, тот же фикс закроет оба случая.
2. **Формат числа с запятой** в Weight-поле судьи (визуально «0,4» вместо «0.4») в одном из скриншотов — вероятно, локаль браузера/рендера. Значение сохраняется и читается корректно (проверено через API), это не сломало функциональность в моих тестах, но стоит перепроверить на разных локалях/раскладках клавиатуры при ручном вводе.
3. **«Scores are for a previous version»** баннер после Restore — по манифесту (`e2e-data.md`, journey «AI-translate»/wave-5) ожидается, что скор «resets to not scored»; фактическое поведение — скор остаётся видимым (последнее известное значение) с явным предупреждающим баннером вместо простого прочерка. Это, вероятно, УЛУЧШЕНИЕ относительно документированного поведения (более информативно для пользователя), а не регресс — отмечаю на случай, если документация должна быть обновлена под фактическое поведение.
4. Ambiguous-senses блок в попапе термина (список кандидатов при жёлтой сложности) визуально показывает не более одного кандидата в моих наблюдениях — это уже задокументированная в памяти агента (`palimpsest-term-grounding-bugs.md`) непроверенная-заново проблема, не входила в список fresh-fix этой волны, отдельно не расследовалась глубоко.

## 6. Данные: provenance и восстановление финального состояния

### Provenance использованных данных
- Тексты seed-документов (1, 10, 13), их термины, критерии, промпты — `docs/testing/e2e-data.md` (манифест) + сам живой прод (единственный источник для этой демки, seed грузится через `seed.py`/`load_terms.py`).
- Файлы для upload-тестов 2f: `source_file: data/seed/demo_docs/andrey_upload_source_ru.txt`, `data/seed/demo_docs/andrey_upload_translation_en.txt` — прямо названы в задании.
- Вайтспейс-вариант для 2g: `GENERATED:` детерминированная правка andrey-файлов (вставлен один пробел после первого слова источника) — манифест не содержит готовой фикстуры для этого конкретного теста; сохранено разово в scratchpad, НЕ в `data/seed/` (одноразовый тест-инпут, не переиспользуемый корпус), удалено вместе с тестовым документом в конце сценария.
- Названия тестовых документов/моделей («E2E test upload — polling check», «E2E clone-cache whitespace test», «google/gemini-3.1-flash-lite-e2etest»): `GENERATED:` — произвольные ярлыки, требуемые формой создания, не влияют на исход теста.
- Проверка Wikidata QID Q207330: `WEB: https://www.wikidata.org/wiki/Special:EntityData/Q207330.json` — подтверждено, что это официальная запись Lagash.

### Верификация финального состояния (GET-диффы против baseline)

| Параметр | Baseline (до прогона) | Финал (после прогона) | Совпадает |
|---|---|---|---|
| documents | 1 (seed), 10 (upload), 13 (upload) | 1 (seed), 10 (upload), 13 (upload) | ✅ |
| models (registry) | 4 модели, все temp 0.7 | те же 4 модели, те же params | ✅ |
| accuracy judge | gemini-3.1-flash-lite, w=0.4, enabled, prompt 7328 симв. | идентично | ✅ |
| fluency judge | gemini-3.1-flash-lite, w=0.3, enabled, prompt 8469 симв. | идентично (не редактировался) | ✅ |
| style judge | gemini-3.1-flash-lite, w=0.3, enabled, prompt 5781 симв. | идентично (не редактировался) | ✅ |
| translator-config | gemini-3.1-flash-lite, 2048/0.3, prompt 675 симв. | идентично | ✅ |
| grounding-config | gemini-3.1-flash-lite, 512/0, prompt 526 симв. | идентично (модель возвращена; текст промпта и не мог измениться — см. BUG-1) | ✅ |
| refiner-config | gemini-3.1-flash-lite, 4096/0.2, prompt 643 симв. | идентично | ✅ |
| doc1 aggregate / §1 | 8.9 / 8.6 (9.0/9.0/8.0), 7 issues open | 8.85 / 8.56 (округление те же 8.9/8.6), 7 issues open | ✅ |
| doc10 aggregate / §4 | 8.3 / 6.4 (5.0/7.0/9.0) | 8.3 / 6.44 (5.0/7.0/9.0) | ✅ |
| doc13 | без scores (aggregate null) | без scores (не трогался) | ✅ |
| временные документы (14, 15) | — | удалены | ✅ |
| тестовая модель registry | — | удалена | ✅ |

Ни одна строка `score`/`issue` не удалялась (инвариант проекта) — везде использовался задокументированный Reset (архивирует, не удаляет) либо чтение через GET.

## 7. Что не тестировалось и почему

- Полный повторный аудит точности заземления по всем ~86-124 терминам во всех документах (сверка каждого QID) — не входил в список «свежих фиксов» этой волны; уже отдельно задокументирован в памяти агента как известная проблема (6/86 неверных QID в одном абзаце).
- Нагрузочное/конкурентное тестирование нескольких параллельных пользовательских сессий — вне периметра одиночного адверсариального прогона.
- Полная regression-прогонка Judges/Translator/Grounding/Refiner под РЕАЛЬНО другими моделями (proof-of-concept ограничился одним циклом смены+отката на каждую секцию, чтобы не тратить лишние живые вызовы, как и просило задание «keep it to what the scenarios need»).
- AI-translate / DE→FR journey из wave-5 — не входил в список сценариев этого задания.

## 8. Скриншоты

50 файлов, `docs/reports/e2e/shots/prod-stability-iter1/` (полный список см. §3, инвентарь: 01–50, все просмотрены лично перед описанием в отчёте). Плюс 2 скачанных экспорт-файла как текстовый артефакт (`.playwright-cli/world-history-selected-passages-draft-translation-10.{xlsx,md}`).

## Итоговый счёт багов

| Severity | Кол-во |
|---|---|
| MEDIUM-HIGH | 1 (BUG-1: Grounding prompt не сохраняется) |
| MEDIUM | 1 (BUG-2: пустое имя модели проходит валидацию) |
| LOW | 3 (BUG-3 косметика, BUG-4 двойной DELETE, BUG-5 остаточные 404) |
| SUSPECTED | 4 (см. §5) |

Все 7 заявленных fresh-fix пунктов (2a–2g) подтверждены как ПОЧИНЕННЫЕ. Адверсариальный репро п.3 не воспроизведён (со честной попыткой брутфорса и DOM-инспекцией).
