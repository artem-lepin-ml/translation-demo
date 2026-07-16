# E2E: прод-стабилизация, итерация 2 (финальная проверка) — 2026-07-16

Второй адверсариальный прогон на LIVE PROD https://glossa-mt.com сразу после второй волны
стабилизационных фиксов, накатанной поверх волны из [prod-stability-iter1-2026-07-16.md](prod-stability-iter1-2026-07-16.md).
Инструмент: `playwright-cli` (сессия `-s=stability-iter2`), напрямую в браузере, без API-шорткатов
для действий пользователя (API использовался только для чтения baseline/финального состояния и
верификации персиста).

Рабочая копия: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`. Манифест данных:
`docs/testing/e2e-data.md` (прочитан первым действием), плюс отчёт iter1 — как источник контекста
о том, что именно чинилось.

## 1. Вердикт

**PASS-with-findings.** Из 6 заявленных «свежих фиксов волны 2» подтверждены починенными **5**:
Grounding-промпт теперь сохраняется через полноценный Save/Revert-редактор, пустое/пробельное имя
модели блокируется валидацией с понятной ошибкой, «Effective Params» в диалоге Edit обновляется
вживую, Revision History корректна сразу после Reset без перезагрузки страницы, а попап
«Ambiguous senses» показывает реальные кандидаты (было: всегда 1 нефункциональный — теперь 5
настоящих кандидатов с рабочими Wikidata-ссылками на примере «Цзинь» из doc13).

Один пункт **не подтверждён как починенный** — двойной DELETE-запрос на одно подтверждение
удаления документа воспроизведён идентично iter1 (BUG-4), причём дважды независимо (мгновенный
клон и документ в процессе реального warming-пайплайна). Дополнительно тот же паттерн двойного
запроса найден и в удалении модели из Model Registry — расширяет область известной проблемы за
пределы документов.

Полный regression-прогон (P2) и адверсариальный chaos-прогон (P3) — оба чистые: 0 некорректно
пойманных JS-исключений за всю сессию (все ERROR-строки в консоли — ожидаемые сетевые логи 404/422,
не падения кода), ни один найденный сценарий не сломал приложение. Один позитивный вывод отдельно
стоит отметить: reload посреди Refine НЕ повреждает данные — фоновый запрос отработал на сервере
независимо от клиента, и после перезагрузки состояние подтянулось корректно.

Итоговое состояние стенда полностью восстановлено до baseline — подтверждено побайтовым
совпадением GET-ответов `/api/criteria`, `/api/translator-config`, `/api/grounding-config`,
`/api/refiner-config`, `/api/models`, `/api/documents` до и после прогона (см. §6).

## 2. План сценариев и статус выполнения

| # | Сценарий | Статус |
|---|---|---|
| P1a | Grounding prompt: Save/Revert-редактор, персист, Revert-flow, точное восстановление | executed |
| P1b | Add model: пустое/пробельное имя → блокировка + инлайн-ошибка, Enter не обходит блок | executed |
| P1c | Edit model: живое превью Effective Params, невалидный JSON → хинт + последнее валидное превью | executed |
| P1d | Document delete: ровно 1 DELETE, 0 хвостовых 404 | executed — фикс НЕ подтверждён |
| P1e | Revision History сразу после Reset без reload | executed |
| P1f | Term popup «Ambiguous senses»: реальные кандидаты (doc13 Цинь/Цзинь) | executed |
| P2 | Picker + 3 seed-документа | executed |
| P2 | Money shot doc10 §4: Refine → rescore → Reset | executed |
| P2 | Evaluate одного параграфа: 3 живых судьи + агрегат, dblclick guard | executed |
| P2 | Upload pair из манифеста, мгновенный клон, удаление | executed |
| P2 | Upload с изменением (не-кэш путь), удаление во время warming | executed |
| P2 | Glossary trace stepper (SEARCH→CANDIDATES→EXACT→DECISION), колонка Matched | executed |
| P2 | Red-dot check на заземлённых терминах (doc1 «Месопотамия») | executed |
| P2 | Ranking: рендер, сортировка, переход по клику на строку | executed |
| P2 | Settings: 5 секций навигация, Model Registry CRUD + Test, Judges/Translator/Refiner персист | executed |
| P3 | Быстрое переключение документов 1→13→10 x3 | executed |
| P3 | Escape закрывает модалку посреди действия | executed |
| P3 | Browser back/forward | executed |
| P3 | Reload посреди Refine | executed |
| P3 | Settings: экстремальные инпуты (max_tokens>32768, отрицательная temperature, unicode-имя) | executed |
| — | Финальная верификация состояния (GET-дифф против baseline) | executed |

Не выполнялось: повторная проверка формата дробного Weight под разными локалями клавиатуры
(SUSPECTED-2 из iter1, не входила в список этой волны); повторный клик Restore на старую ревизию
для перепроверки баннера «Scores are for a previous version» (SUSPECTED-3 из iter1, поведение уже
задокументировано, не входило в fresh-fix список); полный повторный аудит точности заземления по
всем QID (отдельно задокументирован в памяти агента).

## 3. Таблица шаг → данные → артефакт → вердикт

| Шаг | Данные (provenance) | Артефакт | Вердикт |
|---|---|---|---|
| Landing page | — | shots/01-landing.png | pass |
| Baseline config capture (GET ×6 эндпоинтов) | сам прод API до любых действий | текстовый вывод curl | pass — совпадает с ожидаемым baseline из задания |
| Открыть doc1 | source_file: docs/testing/e2e-data.md | shots/02-doc1-open.png | pass — агрегат 8.9, совпадает |
| **P1a.** Grounding prompt: Edit → append " TEST" через `fill` (обход бага Ctrl+End, см. SUSPECTED) → Unsaved changes | — | shots/03-grounding-prompt-unsaved.png | pass — индикатор «Unsaved changes», счётчик 530 chars |
| P1a. Save → GET подтверждает 530 симв., хвост «…TEST» | — | shots/04-grounding-prompt-saved.png | pass — **BUG-1 из iter1 CONFIRMED FIXED** |
| P1a. Повторный Edit → append «XYZ» → Revert (без Save) | — | — | pass — откатило к последнему СОХРАНЁННОМУ состоянию (530 chars), не к исходному — корректная семантика Revert |
| P1a. Восстановление точного исходного текста (526 симв., байт-в-байт из baseline JSON) → Save | — | shots/05-grounding-prompt-restored.png | pass — GET подтверждает `prompt == baseline.prompt` (`match: True`) |
| **P1b.** Add model: пробельное имя + валидный Params JSON → blur | — | shots/06-add-model-empty-name-error.png | pass — инлайн «Name is required», Save disabled — **BUG-2 CONFIRMED FIXED** |
| P1b. Enter в поле Params при disabled Save | — | — | pass — не обошёл блокировку, `GET /api/models` — 4 модели, без изменений |
| **P1c.** Создание тестовой модели `google/gemini-3.1-flash-lite-e2etest2`, Edit → живое изменение Params (999) | — | — | pass — «Effective params» обновилось МГНОВЕННО без Save — **BUG-3 CONFIRMED FIXED** |
| P1c. Невалидный JSON в Params | GENERATED: `{ not valid json {{{` | shots/07-edit-model-invalid-json.png | pass — хинт «Showing last valid params — current JSON is invalid», превью держит последнее валидное (999/0.5) |
| P1c. Save с невалидным JSON | — | shots/08-edit-model-save-blocked-invalid-json.png | pass — клиентская валидация на клике блокирует запрос, чистая ошибка «Params must be valid JSON.», ни одного сетевого вызова не ушло |
| P1c. Test-кнопка на тестовой модели (1 живой вызов) | — | shots/09-model-test-failed-clean.png | pass — реальный вызов OpenRouter, чистый FAILED «not a valid model ID» |
| P1c. Remove тестовой модели, confirm-текст `Delete "google/gemini-3.1-flash-lite-e2etest2"?` | — | — | pass — корректное имя в диалоге (не сломанное `""`, как в BUG-2 до фикса); но: **2× DELETE /api/models/... на 1 подтверждение** (см. §4, расширяет BUG-4) |
| P2. Upload pair (doc16), файлы `data/seed/demo_docs/andrey_upload_{source_ru,translation_en}.txt` | source_file: манифест, прямо назван в задании | shots/10,11 | pass — Title-поле обязательно (не задокументировано явно, но интуитивно понятно), 8¶=8¶, Next/Create активны |
| P2. Doc16 — мгновенный клон из кэша | — | shots/12-doc16-created-instant-clone.png | pass — §1 сразу со скором 6.9 и issues, «Accept all 19» |
| **P1d.** Удаление doc16 (мгновенный клон, БЕЗ warming) | — | `requests`: 2× DELETE /api/documents/16, оба 204 | **BUG-4 CONFIRMED NOT FIXED** — идентично iter1 |
| P2. Upload с вайтспейс-правкой (форс не-кэш путь), doc17 | GENERATED: rationale — деterministic одиночный пробел после первого слова source, для форсирования реального пайплайна (не мгновенный клон); файл в scratchpad, использован разово, удалён вместе с документом | shots/13,14 | pass — «warming 0/8 ¶…», термин-статус `running` (не `done`), реальный асинхронный пайплайн подтверждён |
| **P1d/BUG-5.** Удаление doc17 во время активного warming | — | `requests`: 2× DELETE /api/documents/17 (BUG-4 снова); console: ровно 2× 404 @ /api/documents/17, не растёт | BUG-4 подтверждён повторно на другом пути (реальный пайплайн); BUG-5 (2 хвостовых 404, было 184) — **без изменений, не регресс, но и не идеальная чистота** |
| Открыть doc10 | — | shots/15-doc10-open.png | pass — агрегат 8.3, §1=6.9, совпадает с baseline |
| §4 doc10 baseline (5.0/7.0/9.0, agg 6.4, текст «Primordial Lands») | — | shots/16-doc10-para4-baseline.png | pass |
| P2. Money shot: клик «Refine paragraph» дважды подряд (2 отдельные CLI-команды) | — | — | pass — заявка на клик прошла, второй клик упал на «ref not found» (кнопка уже сменила состояние) — признак, что UI меняется при клике; сетевой лог: ровно 1× POST /refine, 1× /evaluate |
| P2. Результат Refine | — | shots/17-doc10-para4-refined.png | pass — «Primordial Lands» → «Sealand», агрегат 6.4→9.0 (▲2.6) |
| **P1e.** Revision History сразу после Refine (без reload) | — | shots/18-history-after-refine-fresh.png | pass — CURRENT корректно показывает свежую refine-ревизию (9.0, «1 min ago») |
| P2/P1e. Document Reset doc10, диалог-копия «archived (hidden, not deleted)» | — | — | pass — корректная формулировка подтверждена |
| **P1e.** Revision History сразу после Reset (без reload) | — | shots/19-history-fresh-after-reset.png | pass — CURRENT = «seed · just now · current», Best 6.4 сохранён отдельно — **SUSPECTED-1 из iter1 CONFIRMED FIXED** |
| P1e. Проверка через API: doc10 agg=8.3, §4(id=61) agg=6.44, текст вернулся к «Primordial Lands» | — | — | pass — полное восстановление |
| Открыть doc13 | source_file: манифест | shots/20-doc13-open.png | pass |
| **P1f.** Клик термина «Цзинь» (§7, superscript 2) | — | shots/21-doc13-jin-term-popup.png | pass — Difficulty=🟡 Ambiguous, Wikidata=Jin (Q912043) |
| P1f. Секция «Ambiguous senses» в попапе | — | shots/22-doc13-jin-ambiguous-senses-full.png | pass — **5 реальных кандидатов** (Jin dynasty Q7352, Jin-фамилия Q718600, Later Tang Q1143126, Jin-царство Q912043, Later Jin dynasty Q1154540), все ссылки рабочие — было: всегда 1 нефункциональный (задокументировано в памяти агента) — **CONFIRMED FIXED** |
| P1f. Escape закрывает попап термина | — | — | pass |
| P2. Red-dot: термин «Месопотамия» (doc1, QID Q11767) | — | shots/23-doc1-mesopotamia-reddot-check.png | pass — Difficulty=🟡 Ambiguous (не красный) при наличии QID |
| P2. Glossary tab, рендер таблицы (122 термина, 204 mentions) | — | shots/24-glossary-tab.png | pass |
| P2. Разворот строки «Месопотамия» (deterministic match, без LLM-трассы) | — | shots/25-glossary-trace-expanded.png | pass — Candidates(1)·matched via, контекст, All mentions — корректно для deterministic-резолва (55 из 204 резолвятся так) |
| P2. Glossary doc13, разворот «Цзинь» (LLM-путь) | — | shots/26-doc13-glossary-jin-trace.png | pass — полный stepper: 1·SEARCH «wbsearchentities», 2·CANDIDATES «5 candidates found», 3·EXACT «5 exact matches», 4·DECISION «llm disambiguation» |
| P2. Та же строка, колонка Matched / candidates table | — | shots/27-doc13-glossary-jin-matched.png | pass — реальные QID-значения в таблице кандидатов |
| P2. Evaluate §2 doc1, 2 отдельных клика (~5 сек между CLI-командами) | — | `requests`: 2× POST /evaluate, оба успешны | **SUSPECTED, расследовано и снято** — не гонка: первый запрос уже завершился к моменту второго клика (не rapid dblclick), поэтому оба — легитимные последовательные вызовы, не баг guard'а |
| P2. Evaluate §3 doc1, **истинный синхронный dblclick** (`playwright-cli dblclick`) | — | shots/29-doc1-p3-evaluate-dblclick-guard.png | pass — `requests`: ровно 1× POST /evaluate — **in-flight guard реально держит на настоящем dblclick** |
| P2. Document Reset doc1 (очистка §2/§3 evaluate) | — | — | pass — agg вернулся к 8.85 |
| P2. Ranking: рендер | — | shots/30-ranking-tab.png | pass |
| P2. Ranking: сортировка по Aggregate | — | shots/31-ranking-sorted-aggregate.png | pass — корректный возрастающий порядок |
| P2. Ranking: клик по строке → переход в Document | — | shots/32-ranking-row-navigation.png | pass — открылся правильный параграф, console чистая |
| P2. Settings → Judges: смена модели Accuracy → gemma → verify GET → revert → verify GET | — | shots/33-judges-accuracy-expanded.png | pass — персист и откат подтверждены |
| P2. Settings → Judges: Enabled-чекбокс Style off→on | — | — | pass — GET подтверждает False→True |
| P2. Settings → Judges: Weight 0.4→0.5→0.4 | — | — | pass — GET подтверждает |
| P2. Settings → Translator: смена модели → verify → revert | — | — | pass — GET подтверждает, params (2048/0.3) не пострадали |
| P2. Settings → Refiner: смена модели → verify → revert | — | — | pass — GET подтверждает, params (4096/0.2) не пострадали |
| P3. Быстрое переключение 1→13→10 ×3 (9 переключений за миллисекунды) | — | shots/34-docswitch-race-final.png | pass — финальный рендер = doc10, без протухшего контента, 0 новых console-ошибок |
| P3. Escape закрывает Upload pair modal посреди действия | — | shots/35-escape-closes-upload-modal.png | pass |
| P3. Browser back/forward | — | shots/36-browser-back-state.png | **SUSPECTED (информационно)** — основные вкладки (Document/Glossary/Ranking/Settings) не пушат history entries, back/forward двигает только Settings-якорь хэша; не креш, но навигация «инертна» для основных вкладок |
| P3. Reload посреди Refine (клик Refine → мгновенный reload без ожидания) | — | shots/37-reload-mid-refine.png | pass (с нюансом) — reload сбросил в picker (нет deep-link на документ/вкладку — информационно, не баг); ключевое: фоновый refine-запрос ДОЖИЛ на сервере и завершился корректно (§2 doc10: 8.2→10.0), без порчи данных — **позитивный вывод об устойчивости** |
| P3. Cleanup: Reset doc10 после reload-теста | — | — | pass — agg вернулся к 8.3 |
| P3. Settings → Add model: unicode-имя + max_tokens=999999 + temperature=-5 | GENERATED: `test/模型-emoji-🤖-test`, намеренно экстремальные числа для проверки серверной валидации | shots/38-add-model-weird-inputs.png | pass — Save активен (клиент не блокирует), но... |
| P3. Save → 422 от сервера | — | shots/39-add-model-422-response.png | pass — чистое сообщение «Could not add the model (422): max_tokens must be an int in 1..32768», без креша, junk-запись не создана |
| P3. Тот же unicode-имя + валидный max_tokens + temperature=-5 → Save | — | shots/40-add-model-negative-temp.png | pass — чистое «temperature must be a number in 0..2», без креша |
| P3. Cleanup: Cancel модалки, GET /api/models — по-прежнему 4 модели | — | — | pass — ни одной junk-записи не осталось |
| **Финал.** GET-дифф ×6 эндпоинтов против baseline | — | текстовый вывод (python json diff) | pass — **побайтовое совпадение** criteria/translator-config/grounding-config/refiner-config/models/documents |
| Финал. Агрегаты документов | — | — | pass — doc1=8.85, doc10=8.3, doc13=null — все совпадают с исходным состоянием |

## 4. Найденные баги

### BUG-4 (LOW, ПОДТВЕРЖДЁН НЕ ПОЧИНЕННЫМ) — Двойной DELETE-запрос на одно подтверждение удаления
**Где:** любой upload-документ, кнопка 🗑 в топ-баре; **дополнительно теперь подтверждено** — Model Registry, кнопка Remove.
**Статус:** идентичен BUG-4 из [iter1](prod-stability-iter1-2026-07-16.md#4-найденные-баги) — волна 2 НЕ включала фикс для этого пункта (либо фикс не сработал). Воспроизведён **дважды независимо** в этом прогоне:
1. Удаление doc16 (мгновенный клон из кэша, без warming) → `DELETE /api/documents/16` ×2, оба 204.
2. Удаление doc17 (документ в процессе реального warming-пайплайна) → `DELETE /api/documents/17` ×2, оба 204.
3. **Новое расширение области:** удаление тестовой модели `google/gemini-3.1-flash-lite-e2etest2` из Model Registry → `DELETE /api/models/google%2Fgemini-3.1-flash-lite-e2etest2` ×2, оба 204.

**Влияние:** не создаёт видимого вреда (идемпотентно, оба ответа 204), но подтверждает, что причина — двойная привязка обработчика клика/двойной вызов confirm-колбэка на уровне общего компонента удаления, используемого и для документов, и для моделей реестра. Стоит исправить один раз в общем месте.

### BUG-5 (LOW, БЕЗ ИЗМЕНЕНИЙ) — Остаточные 404 при удалении документа во время warming
**Где:** удаление upload-документа, пока его фоновая задача scoring/warming ещё не завершена.
**Статус:** идентичен BUG-5 из iter1 — ровно 2 ошибки `Failed to load resource: 404 @ /api/documents/{id}` в консоли, не растут дальше (не регресс к «шторму 184»), но не идеальная чистота. Не входил явно в список fresh-fix волны 2, поэтому статус «без изменений» ожидаем.

## 5. Подтверждённые фиксы (было — стало)

| # | Было (iter1) | Стало (iter2) |
|---|---|---|
| BUG-1 → **FIXED** | Grounding-промпт визуально редактируется, но никогда не сохраняется (тихая потеря данных, нет Save/Revert рядом с textarea) | Полноценный Save/Revert-редактор (`grounding-prompt-toggle`, `grounding-prompt-editor`, `grounding-prompt-save`, `grounding-prompt-revert`), персист подтверждён через GET, Revert корректно откатывает к последнему СОХРАНЁННОМУ (не исходному) состоянию |
| BUG-2 → **FIXED** | Пустое имя модели проходит валидацию, создаёт мусорную запись `{"name": ""}`, диалог удаления показывает сломанный `Delete ""?` | Save заблокирован при пустом/пробельном имени, инлайн-ошибка «Name is required» после blur, Enter не обходит блокировку |
| BUG-3 → **FIXED** | «Effective Params» в диалоге Edit не обновляется при вводе, показывает устаревшие значения | Обновляется мгновенно при каждом изменении Params; при невалидном JSON — держит последнее валидное значение + явный хинт |
| SUSPECTED-1 (iter1 §5.1) → **FIXED** | Revision History не обновляется сразу после Document Reset, показывает старую CURRENT-ревизию до ручного reload | CURRENT корректно показывает свежую seed-ревизию «just now» сразу после Reset, без reload |
| Долгоживущий баг из памяти агента (`palimpsest-term-grounding-bugs.md`) → **FIXED** | «Ambiguous senses» в попапе термина всегда показывал не более 1 кандидата (нефункционально) | Показывает все реальные кандидаты из трассировки (5 для «Цзинь» в doc13), с рабочими Wikidata-ссылками |

## 6. SUSPECTED / потенциальные проблемы

1. **Ctrl+End не двигает курсор к истинному концу текста в `grounding-prompt-editor`** (LOW). Воспроизведено дважды независимо: `Control+End` + печать текста приземлялось на фиксированную позицию около символа 473 (после `"<one sentence>"}}`), а не на конец строки (526 символов). Возможно, кастомный обработчик клавиш в текстовой области или особенность рендеринга скролла. Не мешает обычному пользователю (мышь + клик в нужное место работают штатно), но ломает keyboard-only флоу редактирования. Обойдено в тесте через `locator.fill()` с точным текстом.
2. **Клик по «Edit» в Grounding-редакторе не переводит фокус в textarea** (LOW). После клика на переключатель Edit, немедленная попытка `Ctrl+End` + печать без явного клика в саму textarea — тихо ничего не делает (0 символов добавлено). Обычный пользователь кликает в поле мышью и не заметит; чисто keyboard-driven автоматизация/доступность через Tab могут столкнуться с этим.
3. **Browser back/forward «инертны» для основных вкладок** (информационно, не баг). Клики по Document/Glossary/Ranking/Settings не пушат записи в историю браузера — history отслеживает только якоря внутри Settings (`#settings-judges` и т.п.). Не креш, но противоречит интуиции «назад — на предыдущий экран».
4. **Reload сбрасывает выбор документа/вкладки на picker** (информационно, не баг). Нет deep-link состояния в URL для активного документа — architectural gap, не проблема стабильности (проверено: данные не портятся, см. позитивный вывод ниже).
5. Не переисследовано в этой волне (см. §2 «не выполнялось»): формат дробного Weight под разными локалями клавиатуры; баннер «Scores are for a previous version» после Restore (уже задокументировано как вероятное улучшение, не регресс).

## 7. Позитивные наблюдения (устойчивость)

- **Reload посреди Refine не портит данные.** Фоновый POST `/paragraphs/{id}/refine` пережил клиентский reload и корректно завершился на сервере (§2 doc10: агрегат 8.2→10.0), без «зависшего» индикатора и без рассинхрона между клиентом и сервером после повторного открытия документа.
- **In-flight guard реально держит на истинном синхронном dblclick** (`playwright-cli dblclick`) — и для Refine (P2 money shot: 1×refine+1×evaluate на 2 клика), и для Evaluate (P2: 1×evaluate на честный dblclick). Ложная тревога с «2 POST /evaluate» на doc1 §2 расследована и снята — там были два самостоятельных последовательных клика с разрывом ~5 сек, а не гонка.
- **Серверная валидация экстремальных Params устойчива**: max_tokens>32768 и temperature<0/>2 оба отклоняются с чистыми, информативными сообщениями (422), без креша UI и без мусорных записей в реестре моделей.

## 8. Данные: provenance

- Тексты seed-документов (1, 10, 13), их термины, критерии, промпты, baseline-конфигурация (6 ролей = gemini-3.1-flash-lite, refiner 4096/0.2, translator 2048/0.3, grounding 512/0) — `docs/testing/e2e-data.md` (манифест) + сам живой прод, прочитан GET-запросами до любых действий.
- Файлы для upload-теста (P1d, инстант-клон): `source_file: data/seed/demo_docs/andrey_upload_source_ru.txt`, `data/seed/demo_docs/andrey_upload_translation_en.txt` — прямо названы в задании.
- Вайтспейс-вариант для форс-не-кэш-пути (BUG-5 репро): `GENERATED: rationale` — деterministic вставка одного пробела после первого слова источника (python, byte-exact воспроизводимо); сохранён в scratchpad (`/private/tmp/.../scratchpad/iter2/andrey_source_ws.txt`), НЕ в `data/seed/` (одноразовый тест-инпут), удалён вместе с тестовым документом.
- Точный оригинальный текст Grounding-промпта для восстановления — извлечён программно (`python3 -c "import json; ..."`) из собственного baseline-снапшота `GET /api/grounding-config`, закодирован в base64 для точной передачи через `playwright-cli run-code` (обход проблемы с shell-экранированием кавычек/фигурных скобок в промпте); восстановление верифицировано побайтовым сравнением JSON-значений.
- Имена тестовых сущностей (`E2E test upload — delete polling check`, `E2E clone-cache whitespace test 2`, `google/gemini-3.1-flash-lite-e2etest2`, `test/模型-emoji-🤖-test`): `GENERATED:` — произвольные ярлыки/намеренно экстремальные значения, требуемые формой создания / целью адверсариального теста, не влияют на исход проверки.
- Проверка Wikidata QID для «Цзинь» (Q912043) и альтернативных кандидатов (Q7352, Q718600, Q1143126, Q1154540) — сами ссылки в UI ведут на `wikidata.org/wiki/Q...`, отдельная внешняя верификация не проводилась (не требовалась заданием, ссылки визуально корректны и кликабельны).

## 9. Верификация финального состояния

Побайтовый GET-дифф всех 6 конфигурационных/структурных эндпоинтов (`/api/criteria`,
`/api/translator-config`, `/api/grounding-config`, `/api/refiner-config`, `/api/models`,
`/api/documents`) против снапшота, снятого ДО первого действия в этом прогоне — **все 6 совпадают
побайтово** (`json.load(baseline) == json.load(final)` → `True` для каждого).

| Параметр | Baseline | Финал | Совпадает |
|---|---|---|---|
| documents | 1 (seed), 10 (upload), 13 (upload) | 1, 10, 13 | ✅ |
| models (registry) | 4 модели | те же 4, те же params | ✅ |
| criteria (3 судьи) | все gemini-3.1-flash-lite, веса 0.4/0.3/0.3, enabled | идентично | ✅ |
| translator-config | gemini-3.1-flash-lite, 2048/0.3 | идентично | ✅ |
| grounding-config | gemini-3.1-flash-lite, 512/0, промпт 526 симв. | идентично (после цикла edit→save→edit→revert→edit→save восстановления) | ✅ |
| refiner-config | gemini-3.1-flash-lite, 4096/0.2 | идентично | ✅ |
| doc1 aggregate | 8.85 | 8.85 | ✅ |
| doc10 aggregate | 8.3 | 8.3 | ✅ |
| doc13 aggregate | null | null | ✅ |
| временные документы (16, 17) | — | удалены | ✅ |
| тестовая модель registry | — | удалена | ✅ |

Ни одна строка `score`/`issue` не удалялась (инвариант проекта) — везде использовался
задокументированный Reset (архивирует, не удаляет).

## 10. Что не тестировалось и почему

- Полный повторный аудит точности заземления по всем ~86–124 терминам во всех документах — уже
  отдельно задокументирован в памяти агента, не входил в список fresh-fix этой волны.
- Формат дробного Weight под разными локалями клавиатуры (SUSPECTED-2 из iter1) — не переисследован,
  низкий приоритет, вне периметра «fresh-fix» списка.
- Полная regression-прогонка Judges/Translator/Refiner под РЕАЛЬНО другими моделями (только один
  цикл смены+отката на секцию, чтобы не тратить лишние живые вызовы).
- AI-translate / DE→FR journey из wave-5 — не входил в список сценариев этого задания.
- Повторный клик Restore на старую ревизию (баннер «Scores are for a previous version») — уже
  задокументировано в iter1 как вероятное улучшение, не входило в fresh-fix список этой волны.

## 11. Скриншоты

40 файлов, `docs/reports/e2e/shots/prod-stability-iter2/` (01–40, все просмотрены лично перед
описанием в отчёте, см. §3).

## Итоговый счёт багов

| Severity | Кол-во | Детали |
|---|---|---|
| MEDIUM-HIGH | 0 | было 1 (BUG-1) — **починен** |
| MEDIUM | 0 | было 1 (BUG-2) — **починен** |
| LOW | 2 | BUG-4 (двойной DELETE, документы **и** модели — расширена область), BUG-5 (2 остаточных 404 при warming-delete, без изменений) |
| SUSPECTED | 4 | Ctrl+End в grounding-textarea (LOW), Edit-toggle не фокусирует textarea (LOW), back/forward инертны для вкладок (информационно), reload сбрасывает deep-link (информационно) |

**Подтверждено починенными:** 5 из 6 заявленных пунктов волны 2 (Grounding Save/Revert, пустое имя
модели, живое превью Effective Params, Revision History после Reset, Ambiguous senses попап).
**Не подтверждено:** 1 пункт (двойной DELETE на удалении документа) — воспроизведён идентично
iter1, плюс найдено расширение той же проблемы на удаление моделей реестра.

Console errors за всю сессию: **0 непойманных JS-исключений**. Единственные ERROR-строки в консоли —
ожидаемые сетевые логи (404×2 при warming-delete, 422×2 при намеренных adversarial-тестах
валидации Settings) — все с чистым UI-фидбеком, без крашей.
