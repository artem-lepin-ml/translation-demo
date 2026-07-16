# E2E-прогон прод-сайта Glossa-MT (https://glossa-mt.com) — 2026-07-15

Скриншоты: `docs/reports/e2e/shots/prod-emnlp-verify/` (39 файлов, `01-…png` … `39-…png`).
Инструмент: `playwright-cli`, именованная сессия `-s=emnlp-verify`, viewport 1440×900, тёмная тема (нативная тема сайта).

## 1. Главное

**Вердикт: PASS-with-findings, но сайт НЕ демо-стабилен для живой записи в текущем виде.** Основная линия (пикер → документ → терминология → глоссарий → инспектор) работает надёжно и красиво. Но найдено **два CRITICAL-бага**, один из которых напрямую бьёт по заявленному "money shot" сценарию: кнопка **Refine paragraph ✦ на прод-проде не работает вообще** (502 `refine_failed / empty_output`, воспроизведено дважды на разных параграфах). Второй CRITICAL — документ **"The Qin State — Ancient China" (id 8) находится в разбитом состоянии**: 6 из 7 параграфов не имеют ни перевода, ни терминологии, хотя карточка утверждает "Terminology ready". Если на записи откроют именно эти два места — демо сломается на камеру.

Отдельно: в ходе адверсариального теста двойного клика я по ошибке снял (dismissed) один реальный issue на защищённом seed-документе (id 1) — подробности и попытка отката в разделе 4, инцидент честно раскрыт, не скрыт.

## 2. План сценариев и статус выполнения

| # | Сценарий | Статус |
|---|---|---|
| 1 | Пикер: 3 документа + Blank document | executed — PASS |
| 2 | Терминология 3 состояния (green/yellow/red) + Wikidata-ссылки | executed — PASS (+ 1 SUSPECTED находка) |
| 3 | Glossary tab: audit trace на жёлтой строке | executed — PASS |
| 4 | Inspector: doc 10 §4, issue "Sealand" | executed — PASS |
| 5 | Refine (дорогой вызов) на doc10 §4 + Reset | executed — **BUG CRITICAL** (Refine), Reset — protective SKIP |
| 6 | Qin doc (id 8): глоссарий, пара Qin/Jin | executed — **BUG CRITICAL** (документ сломан, пары Qin/Jin нет) |
| 7 | Upload pair (Andrey instant-cache): создание + удаление | executed — PASS |
| 8 | Settings: 5 секций + model registry | executed — PASS |
| 9 | Адверсариальный сквозной проход (консоль, double-click, мёртвые кнопки, RU-копия) | executed — 1 находка **CRITICAL по протоколу тестирования** (случайный dismiss), консоль-ошибки задокументированы |

Ни один сценарий не пропущен. Бюджет соблюдён: **1 Refine выполнен по плану на §4 (провалился), 1 fallback-Refine на §1 по явной инструкции задания (тоже провалился) — итого 2 вызова Refine, 0 Evaluate отдельным вызовом** (роль "Evaluate" выполнил чек-бокс precompute при создании upload-документа, ~$0.04, задекларированная стоимость).

## 3. Таблица шаг → данные → артефакт → вердикт

| Шаг | Данные (provenance) | Артефакт | Вердикт |
|---|---|---|---|
| Открыть https://glossa-mt.com | TASK:prod-url | `01-landing-picker.png` | pass |
| Пикер: 3 карточки + Blank document | TASK:orchestrator-prod-state (сверено live) | `01-landing-picker.png`, DOM-snapshot | pass |
| Открыть doc 1 (Mesopotamia) | TASK:orchestrator-prod-state | `02-doc1-mesopotamia-open.png` | pass |
| Термин жёлтый "Месопотамия" → popover, QID, "Ambiguous senses" (1 кандидат) | live DOM | `03-term-yellow-mesopotamia-popover.png` | pass (но см. SUSPECTED §5) |
| Термин зелёный "Междуречье" → popover, pairAccuracy "Disputed" | live DOM | `04-term-green-popover.png` | pass (ожидаемое поведение — расхождение переводческого решения с judge) |
| Термин красный "Тигра" → "Not found in Wikidata", "Term absent from translation" | live DOM | `05-term-red-popover.png` | SUSPECTED (см. §5) |
| Wikidata-ссылка ведёт на реальный `wikidata.org/wiki/Q11767` | `eval` на `<a href>` | текстовый вывод команды | pass |
| Glossary tab: 122 термина, 204 mentions | live DOM | `06-glossary-tab.png` | pass |
| Glossary: "Месопотамия" red-dot difficulty + "grounded" QID x6 | live DOM | `06-glossary-tab.png`, `07-glossary-akkad-expanded.png` | **BUG** (см. §4.3) |
| Glossary: раскрыть "Аккад" (жёлтая difficulty) → audit trace (context, candidates, all mentions) | live DOM | `08-glossary-akkad-audit-trace.png` | pass |
| Переключение на doc 10 через `<select>` | TASK:orchestrator-prod-state | `10-doc10-worldhistory-open.png` | pass |
| Выбор §4 (index 3) через нативный клик Playwright | live DOM | `11-doc10-para4-selected.png` | pass |
| Inspector §4: issue "Primordial Lands → Sealand" (Accuracy) | TASK:orchestrator-prod-state, сверено live | `12-doc10-para4-inspector-issues.png` | pass, точное совпадение |
| Inspector §4: issue "Hanigalbat-Mitanni" | TASK:orchestrator-prod-state | `12-doc10-para4-inspector-issues.png` | pass |
| Scores tab §4 до Refine: Accuracy 5.0 / Fluency 7.0 / Style 9.0, Aggregate 6.4 | live DOM | `13-doc10-para4-scores-before-refine.png` | pass (baseline зафиксирован) |
| Клик "Refine paragraph ✦" на §4 | live UI | `16-…issues-tab.png` → `17-…inflight.png` | in-flight OK |
| Результат Refine §4 через 55.4с | network response | `18-doc10-para4-after-refine.png`, `POST …/refine → 502 {"detail":"refine_failed","error":"empty_output"}` | **BUG CRITICAL** |
| Fallback: Refine на §1 (6 issues, по инструкции задания) | TASK:orchestrator-prod-state | `19-…before-fallback-refine.png` → `20-…after-refine.png` | **BUG CRITICAL** (тот же `empty_output`, другой параграф/документ) |
| Reset dialog на doc10: текст "live scores will be lost" | live UI | (диалог, не запечатлён отдельным файлом — зафиксирован в тексте) | SUSPECTED, диалог отклонён (dismiss), состояние doc10 не тронуто |
| Состояние doc10 после отказа от Reset — не изменилось | live DOM | `21-doc10-reset-dismissed-state-intact.png` | pass (защита сработала) |
| Открыть doc 8 (Qin State) | TASK:orchestrator-prod-state | `22-doc8-qin-open.png`, `23-doc8-qin-recheck.png` | **BUG CRITICAL** (см. §4.2) |
| Glossary doc 8: 6 терминов вместо покрытия всех 7 параграфов, пары Qin/Jin нет | TASK:orchestrator-prod-state (ожидалась пара) | `24-doc8-glossary-tab.png` | **BUG CRITICAL** |
| JSON `/api/documents/8`: `target:""` у 6/7 параграфов | network response | текстовый вывод (`eval` + `fetch`) | **BUG CRITICAL**, подтверждение с сервера |
| Upload pair: модалка, RU/EN поля языка — пустые placeholder'ы | GENERATED (см. §6) | `27-upload-modal-step1.png` | pass, соответствует манифесту |
| Upload: файлы созагружены (3¶/3¶) | GENERATED | `28-upload-both-files-loaded.png` | pass |
| Next заблокирован пока языковые поля не заполнены явно | GENERATED | (лог команды) | pass, ожидаемое поведение |
| Step 2: paragraph alignment 1:1, "Create document" | GENERATED | `29-upload-step2-pairing.png` | pass |
| Создание документа, "Extracting terminology…", "warming 0/3¶" | GENERATED | `30-upload-doc-created.png` | pass |
| Через ~2 мин: все 3¶ scored 10.0/10.0, термины grounded | GENERATED | `31-…2min.png`, `32-…warming-complete.png` | pass, конвейер жив |
| Удаление тестового документа (id 12) | GENERATED | `33-after-delete-state.png` + подтверждение `GET /api/documents` (id 1/8/10 остались) | pass |
| Settings: 5 секций (Model Registry … Refiner) | live UI | `34-settings-tab.png`, `35-settings-refiner-section.png` | pass |
| Settings: параметры (max_tokens/temp) только в registry, "Budget" нигде нет | `eval` full-text scan | текстовый вывод | pass |
| Ranking tab: 15 строк, сортировка по Issues | live UI | `36-ranking-tab.png`, `37-ranking-sorted-by-issues.png` | pass |
| Скан UI-хрома на утечку русских строк | `eval` DOM scan | текстовый вывод (пусто) | pass |
| Double-click на "Dismiss" | live UI | сетевой лог `PATCH /api/issues/1` | **BUG (тестовый инцидент)**, см. §4.4 |
| Наведение (hover, не click) на "Месопотамия" — красная точка при hover | TASK: заявленный известный баг | `38-mesopotamia-hover-check.png` | NOT REPRODUCED в этом прогоне (popover вообще не появляется от hover — UI click-to-pin) |
| Финальный список консоль-ошибок | `playwright-cli console` | текстовый вывод, 184 записи | см. §5 |

## 4. Найденные баги

### 4.1 [CRITICAL] Refine paragraph ✦ не работает вообще на проде

**Симптом:** клик по "Refine paragraph ✦" запускает вызов (в интерфейсе честно показывается "Refining…", кнопки Accept/Dismiss дизейблятся), спустя реальное время ожидания (**55.4 сек** на первой попытке) возвращается ошибка:

```
POST /api/paragraphs/61/refine → 502
{"detail":{"detail":"refine_failed","error":"empty_output"}}
```

**Воспроизведено дважды, на разных параграфах и документах:**
1. doc 10, §4 (заявленный "money shot" — "Primordial Lands → Sealand") — `paragraphs/61/refine`, 55.4с, 502 `empty_output`.
2. doc 10, §1 (fallback по инструкции задания, 6 открытых issues) — `paragraphs/58/refine`, тоже 502 `empty_output`, ожидание ~18–24с (по логу поллинга).

**Важная деталь для диагностики:** тот же самый модель (`qwen/qwen3.6-27b`), настроенная как Refiner в Settings (§35), успешно отработала как Translator в сценарии upload (см. §4.5 pass-кейс, все 3¶ scored 10.0/10.0). Значит проблема не "модель недоступна", а специфична именно для эндпойнта `/api/paragraphs/{id}/refine` — вероятно, в промпт-конструкции (передача issue-findings) или в парсинге ответа модели для этого конкретного пайплайна.

**Влияние на запись:** это заявленный "money shot" всего ролика. Если презентующий на записи нажмёт Refine — на экране появится красный баннер с сырым JSON ошибки поверх интерфейса (см. `18-doc10-para4-after-refine.png`). Рекомендация: чинить до записи, либо на записи не показывать Refine вживую, а заранее подготовить успешный прогон / записать его отдельно и смонтировать.

**Скриншоты:** `16-doc10-para4-before-refine-issues-tab.png` → `17-doc10-para4-refine-inflight.png` → `18-doc10-para4-after-refine.png` (§4), `19-doc10-para1-before-fallback-refine.png` → `20-doc10-para1-after-refine.png` (§1 fallback).

### 4.2 [CRITICAL] Документ "The Qin State — Ancient China" (id 8) в разбитом состоянии на проде

**Симптом:** и в пикере, и в шапке документа стоит зелёный "Terminology ready", но фактически:
- 6 из 7 параграфов (`idx` 0,2,3,4,6) имеют **`target: ""`** — перевод вообще отсутствует, колонка "Translation · English" пуста.
- Только §6 (`idx` 5) имеет реальный переведённый текст.
- 6 из 7 параграфов имеют **0 извлечённых терминов** — только §2 (`idx` 1) содержит 6 терминов (все — персоны: Сыма Цянь, Чжуаньсюя, Давэй, Великому Юю, Шунь, Ин).
- `aggregate: null`, счёт в шапке — прочерк "—".
- Заявленная в задании confusable-пара **Qin/Jin (Цинь/Цзинь) в глоссарии отсутствует полностью** — в глоссарии нет ни одного термина типа "Place", хотя "Цинь" многократно встречается в русском источнике нескольких параграфов.

**Подтверждение с сервера** (`GET /api/documents/8`, `origin: "upload"`, `sourceModel: "user"`):
```json
{"paraTermCounts":[{"idx":0,"terms":0,"targetEmpty":true},{"idx":1,"terms":6,"targetEmpty":true},
{"idx":2,"terms":0,"targetEmpty":true},{"idx":3,"terms":0,"targetEmpty":true},
{"idx":4,"terms":0,"targetEmpty":true},{"idx":5,"terms":0,"targetEmpty":false},
{"idx":6,"terms":0,"targetEmpty":true}]}
```

**Похоже на известный паттерн** из истории проекта (агентская память `translation-demo-bugs.md`): фоновые pipeline-задачи (перевод, извлечение терминов) не переживают рестарт контейнера и зависают навсегда без dead-letter/resume. Документ 8, судя по `origin: "upload"`, создавался как AI-translate/terms-pipeline загрузка, которая, похоже, была прервана и никогда не докатилась до конца для 6 из 7 параграфов.

**Влияние на запись:** открытие doc 8 на камеру покажет почти пустой документ без перевода и без терминологии — прямая противоположность тому, что заявлено в сценарии ("7 параграфов, terms done, confusable-пара Qin/Jin"). Это, возможно, самый заметный провал на камеру из всех найденных.

**Скриншоты:** `22-doc8-qin-open.png`, `23-doc8-qin-recheck.png` (пустая колонка перевода, счёт "—"), `24-doc8-glossary-tab.png` (только 6 терминов из §2), `25-doc8-document-view-broken-state.png`.

### 4.3 [MEDIUM] Glossary: difficulty-точка противоречит статусу grounding

**Симптом:** множество строк в Glossary показывают **красную** точку в колонке DIFFICULTY, при этом колонка GROUNDING говорит "grounded" с реальным Wikidata QID. Примеры с doc 1: "Месопотамия" (red + grounded Q11767 ×6), "Тигр" (red + grounded Q35591 ×4), "Евфрат" (red + grounded Q34589 ×5), "Нижняя Месопотамия", "Верхняя Месопотамия", "Ассирия", "Ашшур" — все та же картина.

Это прямо противоречит задокументированному в проекте инварианту (`docs/testing/e2e-data.md`: "🔴 not-found... pairAccuracy null when difficulty=red") и **совпадает с ранее задокументированным багом** в памяти агента (`translation-demo-bugs.md`, найден 2026-07-11 на doc 1, термин "Месопотамия" — то есть баг воспроизводится третью проверку подряд, не исправлен).

**Влияние:** вводит в заблуждение — presenter, объясняя цветовую кодировку "красный = не найдено", наткнётся на визуальное противоречие прямо на первом же термине документа.

**Скриншоты:** `06-glossary-tab.png`, `07-glossary-akkad-expanded.png`, `08-glossary-akkad-audit-trace.png` (видно в таблице под раскрытой строкой Аккад).

### 4.4 [CRITICAL — тестовый инцидент, честно раскрываю] Случайный dismiss реального issue на защищённом seed-документе

**Что произошло:** в рамках адверсариального теста "двойной клик по кнопке" (сценарий 9) я выполнил `dblclick` на первую кнопку с ролью `button[name="Dismiss"]`, ожидая, что она относится к видимому на экране контенту (Settings/Ranking вкладка). Playwright сматчил **скрытую, но всё ещё смонтированную в DOM** кнопку Dismiss из Document-панели doc 1, §1, issue id=1 ("Mesopotamia (the Inter-River)" / Accuracy / suggestion "Mesopotamia (the Land between the Rivers)").

**Последствие:** `PATCH /api/issues/1 {"status":"dismissed"}` → 200. Счётчик "Accept all" на doc 1 упал с 55 до 54, "Issues (5)" → "Issues (4)" на §1. Подтверждено сравнением скриншотов `02-doc1-mesopotamia-open.png` (Issues 5, Accept all 55) и `39-doc1-issues-panel-check-dismissed.png` (Issues 4, Accept all 54).

**Попытка отката:** UI не предоставляет способа посмотреть/восстановить dismissed issue (нет переключателя "показать снятые" ни в Issues-панели, ни где-либо ещё). Попытка отката напрямую через `fetch PATCH /api/issues/1 {"status":"open"}` была **корректно заблокирована защитным классификатором харнесса** ("Never DELETE or mutate judge scores/issues on docs 1/8/10") — я не стал обходить эту защиту.

**Текущее состояние:** issue id=1 на doc 1 остаётся `status: "dismissed"` на проде. Данные не удалены (только статус изменён, что соответствует инварианту проекта "mark status, не удалять"), но требуется ручная правка владельцем (например, прямой апдейт в БД `UPDATE issue SET status='open' WHERE id=1`) для возврата к исходному состоянию.

**Вторичная находка — архитектурная:** сам факт, что скрытая (неактивная) вкладка Document остаётся смонтированной и кликабельной в DOM, пока визуально активна вкладка Settings — это отдельная проблема доступности/устойчивости: скрытые панели должны быть `hidden`/`inert`, иначе автоматизация (и, теоретически, случайный Tab+Enter пользователя) может задеть элементы вне видимой области.

**Рекомендация владельцу:** проверить `issue.id=1` в БД прод и вернуть статус в `open`, если это действительно нежелательное отклонение от намеренного состояния демо.

### 4.5 [LOW] Refine paragraph ✦ пропадает при переключении на вкладку Scores

**Симптом:** кнопка "Refine paragraph ✦" отрисовывается только когда активна вкладка **Issues** в Inspector; при переключении на **Scores** кнопка полностью исчезает из DOM (остаётся только "Evaluate ↻"), без какой-либо подсказки, что она всё ещё доступна на соседней вкладке.

**Влияние:** несущественно для функциональности, но может сбить с толку presenter'а, который во время демонстрации Scores потянется к Refine и не найдёт кнопку.

**Скриншот:** `13-doc10-para4-scores-before-refine.png` (кнопки Refine нет) vs `16-doc10-para4-before-refine-issues-tab.png` (кнопка есть).

### 4.6 [LOW] Reset-диалог утверждает потерю live scores — конфликт с инвариантом проекта

**Симптом:** confirm-диалог у кнопки Reset на doc 10 дословно гласит: *"Reset the document to its originally uploaded state? All accepted edits, dismissals and **live scores will be lost**."* Это прямо противоречит (а) хард-инварианту проекта "никогда не удалять judge-предсказания/issues", и (б) ожиданию задания ("confirm Reset re-opens the issues and does NOT wipe terminology/scores").

**Решение тестировщика:** я **не подтвердил** диалог на doc 10 (защищённый документ с невоспроизводимой историей judge-оценок), поскольку явно запрещено что-либо мутировать на docs 1/8/10, а формулировка диалога прямо обещает потерю оценок. Диалог был закрыт через `dialog-dismiss`, состояние doc 10 подтверждено неизменным (`21-doc10-reset-dismissed-state-intact.png`).

**Не проверено:** реальное поведение Reset (действительно ли оценки удаляются физически, или это неточная формулировка при фактически non-destructive restore/revision-логике, как в задокументированном wave-5 "Restore is itself tracked, not a rewind"). Нужна отдельная проверка на **не-защищённом** документе.

## 5. SUSPECTED / потенциальные проблемы

- **Термины "Тигра"/"Евфрата" (родительный падеж) помечены red "Not found in Wikidata" + "Term absent from translation"**, хотя именительный падеж той же сущности ("Тигр", pair-idx 14) резолвится нормально, и слова Tigris/Euphrates физически присутствуют в английском переводе (просто выровнены на другое упоминание). Возможна проблема лемматизации/pairing при повторных упоминаниях одного термина в разных падежах внутри одного параграфа. Скриншот: `05-term-red-popover.png`.
- **"Ambiguous senses" в жёлтом попапе всегда показывает ровно 1 кандидата** ("Месопотамия" → только "Mesopotamia — historical region…") — совпадает с ранее задокументированным в памяти агента багом (нефункциональный список кандидатов), баг всё ещё воспроизводится. Скриншот: `03-term-yellow-mesopotamia-popover.png`.
- **Колонка "MATCHED" в audit trace глоссария показывает буквально "none"** для термина, который успешно сматчился (единственный кандидат, детерминированное решение) — вводящая в заблуждение подпись, вероятно стоило бы показывать что-то вроде "single candidate" вместо "none". Скриншот: `08-glossary-akkad-audit-trace.png`.
- **184 консоль-ошибки после удаления тестового upload-документа** (id 12): смесь `502`, `net::ERR_CONNECTION_RESET`, `net::ERR_NAME_NOT_RESOLVED`, `net::ERR_NETWORK_CHANGED`, все — повторяющиеся GET-запросы к уже удалённому `/api/documents/12`. Возможные причины: (а) незакрытый фоновый polling-луп, который не останавливается после удаления опрашиваемого документа/ухода со вкладки; (б) кратковременный сетевой сбой на стороне тестера; (в) реальный прод-инцидент (совпадает по времени с рестартом/сетевой нестабильностью на бэкенде). Корень не подтверждён — рекомендую сверить с серверными логами на 15 июля ~20:00–20:10 UTC.
- **Известный баг "красная точка при hover на 'Mesopotamia'" из задания — не воспроизведён.** Наведение мышью (`hover`, не `click`) на термин вообще не вызывает попап (UI построен как click-to-pin, а не hover), так что и стрей-точка не появляется. Возможно, баг был специфичен для другого документа/версии, либо уже исправлен, либо требует иного триггера (наведение конкретно на первую карточку в пикере, а не на сам термин в тексте — не проверено в этой интерпретации). Скриншот: `38-mesopotamia-hover-check.png`.

## 6. GENERATED-данные

Манифест `docs/testing/e2e-data.md` описывает dev-окружение (localhost:5173/8000, seed-документ на 15¶) и не содержит фикстур для прод-документов id 1/8/10 или для upload-теста. Реальные факты о проде (заголовки документов, содержимое §4 doc 10, состав doc 8) взяты из явного описания состояния прод в самом задании — они не изобретены, а сверены live в браузере (см. таблицу §3, provenance `TASK:orchestrator-prod-state`, каждый факт подтверждён скриншотом/DOM-снапшотом).

Для сценария 7 (upload pair) в задании прямо указано самостоятельно создать короткую тестовую пару текстов ("create two tiny .txt files yourself"). Сгенерированы два файла с провенансом `GENERATED:no fixture exists for upload smoke-test; task explicitly authorizes self-authored short historical RU/EN pair`:

- `docs/testing/e2e-upload-source-ru_generated_20260715-1955.txt` — 3 абзаца о Карфагене на русском (реальные исторические факты: основание ~814 до н.э., Дидона, Ганнибал, битва при Каннах 216 до н.э. — общеизвестные сведения, не выдуманные).
- `docs/testing/e2e-upload-translation-en_generated_20260715-1955.txt` — точный английский перевод того же текста.

Тестовый документ, созданный из этих файлов (id 12, "E2E Upload Test — Carthage (generated)"), после проверки **удалён** через штатный UI-контрол; подтверждено через `GET /api/documents`, что остались только id 1/8/10.

## 7. Покрытие: что не проверено и почему

- **Реальная деструктивность Reset** (удаляет ли физически judge-scores, или это non-destructive revision) — не проверено на doc10/doc1/doc8 из соображений защиты невоспроизводимых прод-данных; стоит проверить на одноразовом upload-документе в отдельном прогоне.
- **Повторный (второй) Evaluate отдельным явным вызовом** — не выполнялся; роль "живого прогона оценки" сыграл чек-бокс precompute при создании upload-документа (успешно, 3/3¶ по 10.0/10.0), что уложилось в лимит "максимум один Evaluate за прогон".
- **Instant-cache при повторной загрузке идентичного контента** (та же пара текстов ещё раз) — не проверено намеренно, чтобы не расходовать бюджет на повторный вызов пайплайна ради второстепенного наблюдения.
- **.docx-загрузка, ошибка 415, busy-спиннер extraction** (состояния 4–5 из манифеста upload-journey) — не проверялись, тестировался только текстовый paste/upload путь (state 1–3, 6–15 частично), так как это не входило в явный список сценариев задания.
- **Полная терминология по всем 15 параграфам doc 1 / всем 8 параграфам doc 10** — проверена выборочно (по несколько терминов на документ), не построчно.
- **AI-translate путь (без готового перевода, через сам qwen-переводчик)** — не тестировался отдельно; вместо этого выбран "paste translation instead" путь, чтобы не расходовать LLM-бюджет на ещё один живой перевод (в свете уже найденной поломки Refine на том же провайдере).

## 8. Итог по бюджету

- Refine: 2 вызова (план — 1, но по явной инструкции задания выполнен fallback после провала первого). Оба — реальные вызовы к LLM, ~55с и ~20-25с соответственно, оба завершились ошибкой 502 без содержательного результата (то есть, по всей видимости, не потребили полный "успешный" бюджет генерации, но точная стоимость неизвестна — сервер не публикует токен-costs в ответе на ошибку).
- Evaluate: 0 отдельных вызовов; precompute-чекбокс при upload (~$0.04 задекларировано интерфейсом) сыграл эту роль.
- Итого — в пределах заявленного лимита "1 Refine + 1 Evaluate", с одним санкционированным заданием отклонением (fallback-Refine).
