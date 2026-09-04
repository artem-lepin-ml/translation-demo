# E2E: финальная верификация session isolation + fresh-trace quality — прод glossa-mt.com

Дата: 2026-07-16. Тестировщик: e2e-tester (адверсариальный прогон). Окружение: **живой прод** `https://glossa-mt.com`, без стейджинга — golden DB не трогалась, все действия жили в эфемерных клонах сессий `glossa_sid`.

Рабочая директория: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint` (ветка `feat/emnlp-demo-sprint`). Инструмент: `playwright-cli`, две именованные сессии `-s=iso-a` / `-s=iso-b`, отдельные in-memory браузерные профили (Chromium), без персистентности между ними.

Манифест данных прочитан первым делом: [docs/testing/e2e-data.md](../../testing/e2e-data.md). Все текстовые значения — из живого прод-приложения или из файлов манифеста; ничего не выдумано без пометки `GENERATED`.

## 1. Главное и вердикт

**ЧАСТЬ 1 (session isolation): ISOLATED.** Все 5 сценариев изоляции (dismiss issue, settings/model params, refine paragraph, upload, чтение из другого профиля) подтверждены раздельными cookie `glossa_sid` и независимым состоянием в обеих сессиях — утечек между A и B не найдено.

**Но в ходе cleanup обнаружен HIGH-severity баг**, не связанный с межсессионной изоляцией, а с самим механизмом **Document Reset**: после dismiss issue + Refine + Reset параграф §1 в сессии A откатился не к своему исходному seed-состоянию (9.7 / 1 issue), а к другой, «плохой» историчной ревизии перевода (6.9 / 6 issues, включая грубую фактическую ошибку с именем "Ur-Nanshe" вместо "Uruinimgina"). Подробности и репро — раздел 4.

**ЧАСТЬ 2 (fresh-trace quality, 5 пунктов владельца): 4 PASS, 1 PASS-с-оговоркой.** Пункты a/b/c/d подтверждены с полной evidence; пункт e (term popover) подтверждён на двух примерах, но ни один не потребовал скролла — это осталось непроверенным.

Итоговый вердикт прогона: **PASS-with-findings** (1 HIGH баг, 1 SUSPECTED минорный баг, 1 методологическое отклонение от буквальной формулировки задания — см. §6).

## 2. План сценариев и статус выполнения

| # | Сценарий | Статус |
|---|---|---|
| 0 | Environment precondition (открыть прод, скриншот) | выполнено |
| P1.1 | Открыть сайт в A и B, убедиться в одной карточке пикера, разные `glossa_sid` | выполнено |
| P1.2 | A dismiss issue §1, B reload видит issue открытым | выполнено |
| P1.3 | A меняет "refiner temperature" → 0.9 + Save, B видит старое значение | выполнено (с отклонением — см. §6) |
| P1.4 | A делает Refine §4 (1 LLM-вызов), B не видит изменений | выполнено |
| P1.5 | B загружает документ (Blank → Upload pair, файлы из манифеста), A не видит его в пикере | выполнено |
| P1.6 | Cleanup: B удаляет свой upload, A делает Reset документа | выполнено (обнаружен баг, см. §4) |
| P1.7 | Консоль: 0 uncaught errors в обеих сессиях | выполнено — 1 ошибка найдена (см. §4, BUG-2) |
| P2.a | Глоссарий «Париж» → Q90, жёлтая сложность, resolved by AI, SEARCH-строки с лейблом стратегии, без дублей | выполнено |
| P2.b | CANDIDATES: кликабельные QID-ссылки на wikidata.org, кандидат без описания → только label | выполнено |
| P2.c | JUDGE DECISION: только цитата, без строки модели/настроек, без жёлтой рамки | выполнено |
| P2.d | Нет кандидатов "Wikinews article" в развёрнутых трейсах, включая «Египтяне» | выполнено |
| P2.e | Term popover: Candidate senses с отмеченным QID, компактные отступы, скролл при длинном списке | выполнено частично — скролл не проверен (не нашлось достаточно длинного списка) |

## 3. Таблица шаг → данные → артефакт → вердикт

| Шаг | Данные (provenance) | Артефакт | Вердикт |
|---|---|---|---|
| Открыть прод в A и B | URL из задания владельца | `shots/01-landing-A.png`, `shots/02-landing-B.png` | pass |
| Cookie `glossa_sid` разные | значение из ответа сервера (Set-Cookie) | `cookie-list` вывод: A=`7a78869c-…`, B=`eeeb6af4-…` | pass |
| A открывает документ, §1 виден с 1 issue | live-данные seed-документа "World History — Selected Passages" (`docs/testing/e2e-data.md` §"Real seed data") | `shots/03-A-doc-open-para1-issue.png` | pass |
| A Dismiss issue §1 | клик по кнопке "Dismiss" в живом UI | `shots/04-A-para1-dismissed.png` (0 active issues) | pass |
| B reload + открыть документ, §1 всё ещё "1 active issue" | то же live-состояние, независимый клон | `shots/05-B-para1-still-1-issue.png` | pass — изоляция подтверждена |
| A Settings → Model Registry → Edit `google/gemini-3.1-flash-lite` → Params temperature 0.7→0.9 → Save | значение "0.9" продиктовано формулировкой задания | `shots/06…`, `07-A-edit-model-modal-before.png`, `08-A-model-temp-0.9-saved.png` | pass (с отклонением, §6) |
| B Settings → тот же реестр моделей всё ещё temp 0.7 | live | `shots/09-B-model-temp-still-0.7.png` | pass — изоляция подтверждена |
| A клик по термину "касситы" (случайно вместо параграфа) → всплывающий popover | live-данные документа | `shots/10-A-term-popover-kassites.png` | pass (заодно закрывает P2.e) |
| A §4 до Refine (6.4, 7 active issues) | live | `shots/11-A-para4-before-refine.png` | pass |
| A Refine §4 → LLM-вызов (~5с) → 9.0, ▲2.6 | live (1 реальный LLM-вызов) | `shots/12-A-para4-refined-9.0.png` | pass |
| B §4 не изменился (6.4, без дельты) | live | `shots/13-B-para4-unchanged-6.4.png` | pass — изоляция подтверждена |
| B Upload pair: title "Session B isolation upload test" (`GENERATED:описательное имя теста, без чувствительных данных`), языки Russian/English, файлы `source_file:data/seed/demo_docs/andrey_upload_source_ru.txt` + `source_file:data/seed/demo_docs/andrey_upload_translation_en.txt` | манифест-файлы, указаны в задании | `shots/14-B-upload-modal-step1-filled.png` (8¶/8¶, точное совпадение) | pass |
| B Step 2: все 8 параграфов автоматически совпали (instant-clone путь, precompute-чекбокс снят вручную для экономии) | live | `shots/15-B-upload-modal-step2-matched.png` | pass |
| B Create document → документ создан мгновенно, 0 LLM-вызовов | live | `shots/16-B-doc-created.png` | pass |
| A reload + пикер: только "World History — Selected Passages", upload B отсутствует | live (после полной перезагрузки с сервера) | `shots/17-A-picker-no-B-upload.png` | pass — изоляция подтверждена |
| B удаляет свой upload (🗑 + confirm) | live | `shots/18-B-after-delete-fallback.png` | **BUG-2** (см. §4) — транзиентная 404 в консоли, но UI откатился корректно |
| A клик Reset документа → confirm | live | `shots/19-A-BUG-para1-after-reset-wrong-score.png`, `20-A-BUG-para1-stale-revision-issues.png` | **BUG-1 (HIGH)** |
| Glossary «Париж»: жёлтая сложность / зелёная pair-accuracy / Q90 / resolved by AI, трейс SEARCH="prefix", CANDIDATES(5) все с описаниями, JUDGE DECISION — только цитата | live | `shots/21…`, `shots/22-B-glossary-paris-candidates.png` | pass (P2.a, P2.b, P2.c) |
| Glossary «Египтяне»: no candidates, 2 разных SEARCH-стратегии (lemma / surface), кандидаты без description → только label, без дублей | live | `shots/23-B-glossary-egyptians-trace.png` | pass (P2.a доп. кейс, P2.b доп. кейс) |
| Glossary «Александр»: 5 кандидатов offered to judge, ни один не "Wikinews article" | live | `shots/24…`, `shots/25…` + текстовый снапшот (grep, ниже) | pass (P2.d) |
| Term popover «номов» (5 candidate senses, ✓ у выбранного, компактные отступы) | live | `shots/26-B-term-popover-nomov.png` | pass (P2.e, полнее чем «касситы») |
| Итоговый консольный тайли по обеим сессиям | live | текстовый вывод `playwright-cli console` | A: 0 ошибок за весь прогон; B: 1 ошибка (404, см. BUG-2) |

## 4. Найденные баги

### BUG-1 (HIGH) — Document Reset может откатить параграф к устаревшей/неверной ревизии перевода вместо seed-baseline

**Где:** `POST /api/documents/{id}/reset` (или эквивалент, вызываемый кнопкой "Reset" в топ-баре), сценарий: dismiss issue на параграфе → (в этом же документе) Refine другого параграфа → Reset всего документа.

**Что наблюдалось:**
- До каких-либо действий §1 сессии A и §1 «чистой» сессии B идентичны: aggregate **9.7**, Accuracy/Fluency/Style = 10.0/10.0/9.0, **1 active issue** (Style minor, "resulted in" → "the situation escalated into a coup"), перевод корректно называет реформатора "Uruinimgina".
- После: A → Dismiss issue §1 → Settings → Refine §4 → Reset документа (подтверждение "Live scores and issues will be archived (hidden, not deleted); every paragraph reverts to its seed text").
- Результат для §1 в A: aggregate **6.9**, Accuracy/Fluency/Style = 6.0/9.0/7.0, **6 active issues**, включая **major Accuracy issue**: "Major factual/naming error. The source explicitly names Uruinimgina (Urukagina)… The translation substitutes him with Ur-Nanshe, an entirely different (earlier) king of Lagash". Сам текст перевода в §1 после Reset действительно содержит "Ur-Nanshe" вместо "Uruinimgina".
- Остальные 7 параграфов документа откатились корректно (§4, единственный подвергнутый Refine, вернулся ровно к дореформенным 6.4/5.0/7.0/9.0 — то есть refine-откат работает правильно). Общий Score документа после Reset = 8.3 (= Baseline), что маскирует локальную порчу §1 на уровне агрегата.

**Почему это баг:** согласно `docs/testing/e2e-data.md`, Journey 5 ("Reset") заявляет: "Reset button → document returns to seed baseline (target text and scores restored...)". Наблюдаемое поведение противоречит контракту: параграф вернулся не к baseline, а к другой, ранее не показанной ревизии с иным (более грубым и грамматически другим) переводом и другим набором issues. Учитывая, что "Ur-Nanshe" — это буквально текст из `data/seed/demo_docs/andrey_upload_translation_en.txt` (тот же исходный корпус, но другая/более ранняя версия перевода §1), похоже, что где-то в БД существует legacy/устаревшая ревизия этого параграфа, и Reset (либо в комбинации с Dismiss) ошибочно "будит" её вместо текущей курированной seed-ревизии.

**Влияние:** golden DB не пострадала (это эфемерный клон A), но если такой же путь Reset задействован где-то для реальных пользовательских документов — это порча данных пользователя: он теряет корректный baseline безвозвратно в рамках своей сессии (Reset — единственная кнопка "вернуть к исходному").

**Репро (детерминированно, на живом проде, изолированная сессия):**
1. Открыть "World History — Selected Passages".
2. §1 → инспектор → Dismiss на единственном issue.
3. Любой другой параграф (например §4) → Refine paragraph → дождаться завершения.
4. Топ-бар → Reset → подтвердить.
5. Открыть §1 → сравнить aggregate/issues с состоянием до шага 2.

**Severity: HIGH** — прямое искажение заявленного в документации контракта Reset + реальная деградация видимого пользователю перевода до заведомо более плохой версии без предупреждения.

**Скриншоты:** `shots/19-A-BUG-para1-after-reset-wrong-score.png`, `shots/20-A-BUG-para1-stale-revision-issues.png`.

### BUG-2 (LOW, cosmetic) — транзиентный 404 в консоли после удаления активного документа

**Где:** удаление текущего активного upload-документа (🗑 в шапке) → confirm.

**Что наблюдалось:** сразу после подтверждения удаления консоль браузера B получает `[ERROR] Failed to load resource: the server responded with a status of 404 () @ https://glossa-mt.com/api/documents/18:0`. Функционально приложение восстанавливается корректно — dropdown сразу показывает только оставшийся seed-документ, Score/Accept-all соответствуют его исходному состоянию (см. `shots/18-B-after-delete-fallback.png`).

**Гипотеза:** какой-то фоновый запрос (poll/refetch), инициированный до удаления, всё ещё "в полёте" и обращается к уже удалённому `document_id=18` после того как фронт уже переключился на другой документ.

**Влияние:** UX не пострадал, но это единственная console-ошибка за весь прогон (обе сессии, ~40 действий) — нарушает заявленный в задании инвариант "0 uncaught errors".

**Severity: LOW.**

## 5. SUSPECTED / потенциальные проблемы

- **SUSPECTED:** после Document Reset суммарный "Accept all" вырос до 19 (был 14 в исходном seed-состоянии до каких-либо действий A). Это тесно связано с BUG-1 — вероятно, тот же механизм "воскрешения" старых issue-рядов затронул подсчёт, но я не выяснял, ограничивается ли аномалия только §1, или "лишние" 5 issues размазаны по нескольким параграфам. Не расследовано глубже из-за бюджета прогона — рекомендую отдельный fix-цикл (`systematic-debugging`) на BUG-1, который заодно объяснит и это.
- **SUSPECTED (низкий приоритет):** пункт P2.e (term popover scroll при длинном списке) проверен только на popover с ≤5 кандидатами — оба реальных примера («касситы» — 1 кандидат, «номов» — 5 кандидатов) уместились без скролла. Не нашёл в документе термина с длинным списком кандидатов, чтобы прогнать overflow-поведение попапа вживую.
- **Не баг, но отмечаю:** SEARCH-строки трейса для одного и того же термина легитимно могут повторяться с разными подписями (например «Египтяне»: `prefix · lemma` и `prefix · surface` — две строки, оба «prefix», но разные ключи). Формально это не «визуальный дубль» (у них разные лейблы атрибутов), поэтому дедуп-требование из задания (P2.a) не нарушено, но стоит иметь в виду при дальнейшем ревью UI — на первый взгляд выглядит как повтор.

## 6. Отклонения от буквальной формулировки задания (W6-style deviation log)

**Задание:** "In A: Settings → change refiner temperature to 0.9, Save."

**Обнаруженный факт:** в разделе Settings → "5. Refiner" нет отдельного поля/слайдера "temperature" — там только выбор модели (combobox) и редактор промпта (Edit/Preview + Save prompt). Температура — атрибут **модели**, а не роли: она редактируется в разделе "1. Model Registry" через модалку "Edit" конкретной модели (`Params (JSON)` → `"temperature": 0.7`), и это значение общее для всех ролей, использующих эту модель (в данном случае `google/gemini-3.1-flash-lite` — модель по умолчанию для Translator/Grounding/Refiner всех сразу).

**Консервативное решение:** отредактировал temperature именно у модели, которую использует Refiner (`google/gemini-3.1-flash-lite`, 0.7→0.9) через Model Registry → Edit → Save. Это функционально эквивалентно "изменить refiner temperature", но затрагивает и другие роли на той же модели — в рамках теста изоляции это не помешало проверке (проверялась только видимость изменения между A и B, а не его ролевая избирательность).

**Почему это не баг, а находка о несоответствии UI ожиданиям:** формулировка задания предполагает per-role temperature control, которого в текущем UI нет. Рекомендую владельцу зафиксировать явно: либо это ожидаемое поведение (temperature — атрибут модели, разделяемый всеми ролями), либо это todo на будущее (per-role override). Сообщаю честно, а не подменяю тихо.

## 7. Данные: provenance

Все текстовые вводы:

| Значение | Источник |
|---|---|
| Документ "World History — Selected Passages" | `source_file:` живой прод-пикер (единственная карточка, соответствует `docs/testing/e2e-data.md` curation-flag) |
| Файлы для upload B (RU/EN) | `source_file:data/seed/demo_docs/andrey_upload_source_ru.txt`, `source_file:data/seed/demo_docs/andrey_upload_translation_en.txt` — явно указаны в задании и физически присутствуют в манифест-директории `data/seed/demo_docs/` |
| Заголовок нового документа "Session B isolation upload test" | `GENERATED:описательное служебное имя для e2e-теста, не содержит PII/секретов, требовалось непустое поле Title` |
| Значение temperature 0.9 | продиктовано буквальным текстом задания владельца (не изобретено самостоятельно) |
| Термины «Париж», «Египтяне», «Александр», «номов» | продиктованы заданием владельца (review items a/d) либо найдены live в глоссарии документа (номов — для доп. проверки P2.e) |

Никаких `WEB:` источников не потребовалось — вся необходимая тестовая нагрузка нашлась в манифест-директории или была прямо задана в задании.

## 8. Покрытие: что не тестировалось и почему

- **Ranking-вкладка** — не проверялась в этом прогоне; не входила явно в задание (Part 1/Part 2), фокус был на session isolation + 5 review items.
- **Export (xlsx/md)** — не проверялся; не упомянут в задании, покрыт предыдущими прогонами (`wave5-run.md`).
- **AI-translate / revision-history UI** (§1 "History" блок) — не открывался явно; при расследовании BUG-1 не успел проверить, показывает ли блок истории ревизий тот факт, что §1 "переключилась" на другую ревизию — это было бы полезно для диагностики корневой причины, но выходит за рамки QA-прогона (передаю в `systematic-debugging`).
- **P2.e overflow/scroll** — не найден достаточно длинный список candidate senses в живом документе для проверки скролла попапа (см. §5).
- **Восстановление dismissed issue в A (буквальный шаг из задания "restore the dismissed issue")** — не выполнено осознанно: как только Reset вскрыл BUG-1, §1 в A оказался в состоянии, не совместимом с "просто отменить dismiss" (весь параграф теперь на другой ревизии перевода с 6 issues вместо 1). Пытаться патчить это через API поверх уже испорченного состояния означало бы уничтожить улику бага. A — эфемерный клон, golden не затронут, поэтому оставил A в этом состоянии как живое репро для последующего fix-цикла, а не "прибрал" его.
- **Password-поле / API Key маскирование** (Journey 6 из манифеста) — увидел мельком в модалке Edit модели (текстовое поле "API Key" с "Clear key" disabled — похоже, что поле не показывает plaintext), но не проверял отдельно намеренно — не было явного пункта в задании.

## 9. Итог по консоли (числа)

- Сессия **A**: 0 console-ошибок за весь прогон (единственное сообщение за весь run было `[VERBOSE]` DOM notice про password field вне `<form>`, не ошибка).
- Сессия **B**: **1 console-ошибка** (404 при удалении активного документа, BUG-2).
- Итого: **26 скриншотов** в `docs/reports/e2e/shots/session-isolation-final/` (требование — ≥14).
