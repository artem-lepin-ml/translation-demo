# T4 — «Своя модель с ломаными параметрами» — отчёт прогона

Прод: https://glossa-mt.com. Основная сессия: playwright-cli именованная
сессия `-s=t4` (эфемерный клон БД по cookie `glossa_sid`, golden не
тронут). Скриншоты: `docs/reports/e2e/shots/campaign/t4/` (18 шт, включая
3 добавленных при аудиторской ремедиации — см. ниже). Спека:
`docs/superpowers/specs/2026-07-17-e2e-mega-campaign.md` § T4.

**Прерывание сессии.** Прогон был прерван на середине транзиентной ошибкой
харнесса (`ConnectionRefused`), не связанной с приложением. Именованная
сессия `t4` пережила прерывание (тот же процесс браузера, тот же cookie) —
продолжил в НЕЙ ЖЕ, без новой baseline-переснимки: та же эфемерная БД,
никакого расхождения данных. Единственный побочный эффект прерывания —
два клика по Refine (см. шаг 8) улетели с `net::ERR_NETWORK_CHANGED` на
стороне инструмента, но, как выяснилось при ретрае, один из них реально
дошёл до сервера и был обработан.

**Ремедиация по независимому аудиту (эта же дата, после первичной сдачи).**
Аудитор нашёл 6 проблем evidence-hygiene в первой версии отчёта (искажённый
network-лог шага 12, отсутствующий артефакт для шага 14, дубль-скриншот,
неверная цитата для Н4, пропущенная находка про UI-лейбл, недостаточно
аккуратная формулировка Н6). Пункты 1, 2 и частично 6 закрыты ЖИВОЙ
пересъёмкой в НОВОЙ именованной сессии `-s=t4b` (свежий клон БД,
собственный baseline/restore/GET-дифф-цикл — см. блок ниже); пункты 3-5 —
правкой текста/цитат без пересъёмки (не требовали новых прод-вызовов).
Все правки отмечены пометкой **[ремедиация]** в соответствующих разделах.

## Вердикт

**PASS-WITH-FINDINGS.** Ни одного «тихого успеха» на пути (а)/(б)/(г)/(д) —
все честные отказы с внятными сообщениями. НО найден один настоящий тихий
успех на пути (в)/партиального отказа: полный (не частичный) отказ судей
из-за поломки параметров/ID модели **скрыто** маскируется под старые
кэш-скоры с флагом «нет ошибок» в API-контракте (`failedCriterionIds: []`
при `cached: true`, хотя ВСЕ судьи реально упали) — см. Н1, HIGH.
Байтовое восстановление конфигов подтверждено GET-диффом (все 5 секций
идентичны байт-в-байт).

## План сценария и статус выполнения

| Подшаг спеки | Что делали | Статус |
|---|---|---|
| (а) добавить дубль-модель с `max_tokens:10`, Test | выполнено, плюс bonus: попытка добавить ТОЧНУЮ тёзку (409) | executed |
| (а, честный провал) | Test на дубле с невалидным ID модели у провайдера | executed |
| (г) params реально доехали → Test ≤10 токенов | выполнено на РЕАЛЬНОЙ модели (не дубле) | executed |
| (б) назначить рефайнером → Refine, честный отказ | executed (на дубле: 502, честно; на реальной модели с mt=10 в реестре: рефайнер её НЕ использует — см. Н2) |
| (в) назначить accuracy-судьёй → Evaluate, частичный отказ | executed — оба варианта: 100% отказ (Н1) и честный 1-из-3 (штатно) |
| (д) 422 max_tokens=32769, temperature=-1 | executed, плюс bonus 422 (params как массив) |
| (е) вернуть конфиги, удалить дубль, GET-диф | executed, байт-идентично |

Не тестировалось: (в) сценарий «2 из 3 судей упали, 1 жив» отдельно от
«1 упал, 2 живы» — не было практической необходимости (архитектура судей
симметрична, код обработки одинаков для любого N упавших из M; см. §
«Что не тестировалось»).

## Таблица шагов

| # | Шаг | Ожидание | Факт | Вердикт | Артефакт |
|---|---|---|---|---|---|
| 1 | Открыть прод, скриншот landing | страница отвечает | 200, "Glossa-MT — interpretable translation evaluation", 0 console errors | pass | `01-landing.png` |
| 2 | Baseline GET моделей/конфигов/бюджета | зафиксировать до-состояние | `google/gemini-3.1-flash-lite` params `{max_tokens:20000, temperature:0.7, reasoning:{effort:"medium"}}`; refiner/grounding/translator-config все на flash-lite; budget $0.39/533 вызовов | pass | `scratchpad/t4/baseline/configs-pretty.json` |
| 3 | Открыть World History → Settings → Model Registry | 4 модели в реестре | подтверждено (deepseek-v4-flash, flash-lite, gemma-3-27b-it, qwen3.6-27b) | pass | `02-settings-registry.png` |
| 4 | Add model с именем **точной тёзкой** `google/gemini-3.1-flash-lite`, params `{max_tokens:10}` | честный конфликт, не тихая перезапись | `POST /api/models → 409 {"error":"UNIQUE constraint failed: model.name"}`; модальное окно показывает сырое сообщение SQLite пользователю | pass (с находкой Н5, LOW) | `03-duplicate-name-409.png` |
| 5 | Add model `google/gemini-3.1-flash-lite-t4` (дубль-двойник, невалидный provider ID), params `{max_tokens:10}` | модель добавлена в реестр | `POST /api/models → 200`, строка появилась в таблице | pass | `04-registry-with-t4dup.png` |
| 6 | Test на `…-t4` | честный провал (модель не существует у провайдера) | `POST …/test → 200 {"ok":false,"message":"BadRequestError: Error code: 400 - {'error': {'message': 'google/gemini-3.1-flash-lite-t4 is not a valid model ID', 'code': 400}, 'user_id': 'user_3DSjOtCFgWsPlqyYKDeAIpsKkPf'}"}` | pass (с находкой Н4, LOW — см. ниже: провайдерский `user_id` утёк в UI) | `05-t4dup-test-failed.png` |
| 7 | Edit **реальной** `google/gemini-3.1-flash-lite`, params → `{"max_tokens":10}`, Save | 200, применилось | `PUT /api/models/... → 200` | pass | `06-edit-flashlite-mt10.png` |
| 8 | Test на реальной модели с `max_tokens:10` | честный провал ИЛИ обрубок, НЕ зелёный успех | `POST …/test → 200 {"ok":false, tokens:{"prompt":136,"completion":6,"reasoning":0}, "message":"could not parse model output as a JSON list"}` — модель реально прислала 6 токенов ответа (усечённый JSON), парсер честно отклонил как невалидный | **pass** — усечение доказано (`completion:6 ≤ 10`), тихого успеха нет | `07-flashlite-mt10-test-failed.png` + сырой network-лог ниже |
| 9 | Edit модели, `max_tokens:32769` (>32768), Save | 422 | `PUT → 422 {"detail":"max_tokens must be an int in 1..32768"}`, показано в модалке | pass | `08-422-maxtokens-32769.png` |
| 10 | Edit модели, `temperature:-1` (params `{"max_tokens":10,"temperature":-1}`), Save | 422 | `PUT → 422 {"detail":"temperature must be a number in 0..2"}` | pass | `09-422-temperature-neg1.png` |
| 10b (bonus) | params как JSON-массив `[1,2]` вместо объекта | честная валидация типа | `PUT → 422 {"detail":"params must be a JSON object"}` | pass (bonus) | included in `/tmp` snapshot, текст в отчёте |
| 11 | Назначить `…-t4` рефайнером (select в Settings → 5. Refiner) | сохранено | `PUT /api/refiner-config → 200, modelName:"google/gemini-3.1-flash-lite-t4"` | pass | `10-refiner-t4dup-assigned.png` |
| 12 | Refine paragraph (§1 «В Лагаше…», 6 open issues, pid=58) с рефайнером = дубль | честный провал, ревизия не создана / данные не тронуты | `POST /paragraphs/58/refine → 502 {"detail":{"detail":"refine_failed","error":"BadRequestError: ... invalid model ID ..., 'user_id':'[REDACTED]'"}}`; проверено: `target`/`aggregate`/6 open issues **не изменились** после отказа | pass | `11-refine-502-mislabeled-evaluate.png` (первичный) + `15-refine-502-redacted-recapture.png` (ремедиация, сессия t4b) + JSON ниже |
| 12b | Реассайн рефайнера на реальную `flash-lite` (у которой в РЕЕСТРЕ всё ещё `max_tokens:10`), Refine снова | ожидание: либо тоже усечение/провал (если params реестра доезжают до рефайнера), либо успех (если рефайнер использует свои параметры) | `POST /refine → 200` (успех!), issues → `accepted`, текст переписан. Причина: `_client_for(conn, model_name, params_override)` для рефайнера ВСЕГДА подставляет `params_override = refiner_config.params_json` (свой независимый bag, дефолт `{"max_tokens":4096,"temperature":0.2}`), а НЕ параметры строки реестра модели. Т.е. **параметры реестра модели не долетают до Refine/Evaluate** — это архитектурное решение (см. докстринг `_client_for`, `app.py:878-888`, комментарий "owner call 2026-07-11: params visible there only"), не баг | **см. находку Н2, MEDIUM** | `11b-refine-succeeded-flashlite-realparams.png` |
| 13 | Assign Accuracy-судью на `…-t4` (Settings → 3. Judges → Accuracy → Model) | сохранено | `PUT /api/criteria/accuracy → 200` | pass | `12-accuracy-judge-broken-model.png` |
| 14 | Evaluate (все 3 критерия), при этом Accuracy=дубль (сломан по ID), Fluency/Style=реальная модель, но у реальной модели В РЕЕСТРЕ ЕЩЁ `max_tokens:10` (не восстановлена с шага 7-10) | ожидание: частичный отказ (1 из 3) с явным `failedCriterionIds` | **ВСЕ 3 критерия упали** (Accuracy — невалидный ID; Fluency/Style — усечение на `max_tokens:10` в реестре, т.к. `_judge_live` НЕ переопределяет params — использует `model.params_json` реестра напрямую, в отличие от рефайнера); ответ: `{"cached":true,"failedCriterionIds":[]}` — сервер тихо подставил СТАРЫЕ precompute-скоры и заявил «ничего не упало» | **FAIL — находка Н1, HIGH (тихий успех)** | **[ремедиация]** JSON ниже (изначально было только текстом в отчёте, без сохранённого файла/скриншота — исправлено живой пересъёмкой в сессии `t4b`: сырой JSON `scratchpad/t4b/evaluate-allfail-cached-raw.json`, скриншот `16-evaluate-allfail-silent-cached-recapture.png` — на нём чётко виден бейдж «cached» рядом с §1 и ПОЛНОЕ отсутствие какого-либо баннера отказа, притом что реально упали все 3 судьи) |
| 15 | Восстановить params реестра `flash-lite` до baseline (`max_tokens:20000, temperature:0.7, reasoning:{effort:medium}`) | 200 | `PUT → 200`, подтверждено GET | pass | — |
| 16 | Evaluate снова (Accuracy=дубль, Fluency/Style=реальная модель с восстановленными params) | ожидание: ЧЕСТНЫЙ частичный отказ 1-из-3 | `POST /evaluate → 200 {"cached":false,"failedCriterionIds":["accuracy"]}`, `fluency`/`style` получили СВЕЖИЕ оценки (style 7→9, живой пересчёт), `accuracy` осталась на последнем известном значении (6.0); UI: баннер **«Failed: accuracy» + кнопка «Retry failed ↻»** — честно, без маскировки | **pass** — штатный, информативный путь частичного отказа | `13-partial-judge-failure-scrolled.png` (**[ремедиация]** второй файл `13-partial-judge-failure-inspector.png`, ранее упомянутый как отдельный артефакт, оказался байт-идентичен этому — MD5 совпал; дубль удалён из `shots/`, ссылка на него нигде больше не используется) |
| 17 | Восстановить Accuracy-судью на реальную модель | 200 | `PUT /api/criteria/accuracy → 200, modelName:"google/gemini-3.1-flash-lite"` | pass | — |
| 18 | Удалить `…-t4` через UI (Remove → confirm dialog → Accept) | 204, строка исчезает | `DELETE /api/models/...-t4 → 204` **дважды** подряд на один confirm (см. Н6, известный паттерн) | pass (с известной находкой) | `14-registry-restored-final.png` |
| 19 | GET-дифф всех 5 конфиг-секций (models/refiner-config/grounding-config/translator-config/criteria) до/после | байт-идентично | **все 5 секций EQUAL=true** (сравнение через `JSON.stringify` нормализованных проекций) | **pass** | `scratchpad/t4/baseline/configs.json` vs `configs-after.json` |
| 20 | Бюджет до/после | здоровый | до: `$0.39031 / 533 вызова`; после: `$0.435199 / 568 вызовов` (Δ=$0.0449, 35 вызовов — все наши LLM-операции) | pass | см. ниже |

## Truncation-доказательство (шаг 8) — сырой network-лог

```
PUT /api/models/google%2Fgemini-3.1-flash-lite → 200
POST /api/models/google%2Fgemini-3.1-flash-lite/test → 200
Response body:
{
  "ok": false,
  "extracted": [],
  "reference": ["нижняя месопотамия","плодородного полумесяца",
                "верхняя месопотамия","ассирия","ашшур","среднем тигре"],
  "matched": 0, "total": 6, "share": 0.0,
  "tokens": {"prompt": 136, "completion": 6, "reasoning": 0},
  "costUsd": 0.000043, "latencyMs": 954,
  "message": "could not parse model output as a JSON list"
}
```
`completion:6` при запрошенных `max_tokens:10` — модель реально была урезана
провайдером, ответ не сформировал валидный JSON-список, честно
классифицирован как отказ (`ok:false`), в UI — красная плашка «FAILED».
Тихого зелёного успеха на усечении **нет**.

## Refine honest-failure (шаг 12) — сырой network-лог

**[ремедиация]** Версия ниже до правки содержала НЕВЕРНЫЙ текст: сырое
тело ответа было по ошибке скопировано с шага 6 (Test-провал), у которого
`user_id` действительно не редактируется (см. Н4) — тот блок ошибочно
выдавал себя за лог `refine`-провала. Код (`app.py:1710-1715`) безусловно
вызывает `redact_error()` перед тем, как поднять `HTTPException(502, ...)`
для этого пути — это подтверждает и собственный скриншот
`11-refine-502-mislabeled-evaluate.png`, который с самого начала показывал
`'user_id': '[REDACTED]'` (несоответствие между текстом отчёта и
собственным же скриншотом не было замечено при первой сдаче).

Живая пересъёмка (сессия `-s=t4b`, свежий клон, минимальная воспроизводящая
конфигурация: дубль-модель `google/gemini-3.1-flash-lite-t4b` с невалидным
provider ID → назначена рефайнером → Refine на §1/pid 58 с 6 open issues):

```
PUT /api/refiner-config → 200 {"modelName":"google/gemini-3.1-flash-lite-t4b", ...}
POST /api/paragraphs/58/refine → 502
Response body (реально полученный, redact_error применён сервером):
{"detail":{"detail":"refine_failed",
 "error":"BadRequestError: Error code: 400 - {'error': {'message':
  'google/gemini-3.1-flash-lite-t4b is not a valid model ID', 'code': 400},
  'user_id': '[REDACTED]'}"}}
```
Сырое тело сохранено: `scratchpad/t4b/refine-502-raw.json`. Скриншот этого
конкретного повторного захвата: `15-refine-502-redacted-recapture.png`.

Проверка целостности данных ПОСЛЕ отказа (прямой GET параграфа, та же
сессия `t4b`):
```json
{"target200":"In Lagash, one of the most economically advanced city-states...",
 "aggregate":6.89, "issueOpen":6}
```
Идентично состоянию ДО вызова Refine — ревизия не создана, ни один score/issue
не тронут. Соответствует hard invariant «Never delete/corrupt LLM
predictions» и требованию PASS-критерия T4 «данные абзаца нетронуты после
каждого отказа». Оригинальный скриншот `11-refine-502-mislabeled-evaluate.png`
(из первичной сессии `t4`, тоже с корректным `[REDACTED]`) остаётся в
качестве второго независимого подтверждения того же поведения — см. также
новую находку Н7 ниже, которая разбирает именно ЭТОТ скриншот (лейбл
«Evaluate failed:» на баннере Refine-ошибки).

## GET-дифф конфигов (шаг 19) — полный вывод

```
models: EQUAL=true
refiner-config: EQUAL=true
grounding-config: EQUAL=true
translator-config: EQUAL=true
criteria: EQUAL=true
budget before: {"spentUsd":0.39031,"capUsd":100000,"calls":533,"callCap":1000000}
budget after : {"spentUsd":0.435199,"capUsd":100000,"calls":568,"callCap":1000000}
```
Полные тела сохранены: `scratchpad/t4/baseline/configs-pretty.json` (до),
`configs-after-pretty.json` (после) — в этой копии отчёта не инлайнятся
(временная директория сессии), значения сверены построчно скриптом,
результат воспроизведён выше текстом.

**[ремедиация] Независимый повторный GET-дифф в сессии `t4b`:**
```
models: EQUAL=true
refiner-config: EQUAL=true
grounding-config: EQUAL=true
translator-config: EQUAL=true
criteria: EQUAL=true
budget before: {"spentUsd":0.475674,"capUsd":100000,"calls":669,"callCap":1000000}
budget after : {"spentUsd":0.49349,"capUsd":100000,"calls":679,"callCap":1000000}
```
Полные тела: `scratchpad/t4b/baseline/configs.json` (до), `configs-after.json`
(после). Второй независимый цикл byte-restore подтверждает, что
конфиг-инварианты держатся не только для конкретной последовательности
мутаций первичного прогона, но и для отдельного, заново собранного
minimal repro.

## Находки

### Н1 — HIGH — Тихий успех при ПОЛНОМ отказе судей маскируется под кэш без единого сигнала об ошибке

**Что происходит.** Когда `POST /paragraphs/{pid}/evaluate` вызывает
`asyncio.gather` по всем включённым критериям и **ни один** судья не
завершается успешно (в нашем случае: Accuracy — невалидный provider ID,
Fluency/Style — усечены `max_tokens:10` в реестре), эндпоинт (app.py,
функция `evaluate`, ветка `if not succeeded:`) молча вызывает
`_cache_response()` — читает СТАРЫЕ precompute-скоры (`kind='cache'`) и
возвращает их клиенту с явным `"failedCriterionIds": []`. Комментарий в
коде это подтверждает как намеренное поведение:
> `# cache supplied a value for every criterion → nothing failed from the consumer's view (the live judges that raised are an internal detail)`

**Почему это баг, а не фича.** Контракт ответа буквально врёт: consumer
(фронтенд) получает `cached:true` (UI покажет плашку «cached» — это
смягчает эффект, см. ниже), НО `failedCriterionIds:[]` одновременно
подавляет отдельный баннер «N criteria failed» (см.
`InspectorPanel.tsx:144`: `evalState.failedCriterionIds.length > 0 &&
!evalState.cached` — то есть если `cached`, предупреждение о конкретных
упавших критериях никогда не показывается). Пользователь видит только
generic-подсказку «Cached: offline fallback estimate, not a live
judgment» — это ВВОДИТ В ЗАБЛУЖДЕНИЕ: подсказка звучит как «нет API-ключа»
/ «фича оффлайн-режима», а реальная причина — сломанная модель/параметры,
которые пользователь сам только что назначил. Ни в UI, ни в теле ответа
НЕТ информации о том, что accuracy использует несуществующий ID модели,
а fluency/style получили усечённый вывод. Это ровно тот класс находки,
который спека прямо называла целью теста: «частичный отказ судьи ...
показывает старые скоры как новые» — только оказалось хуже: **полный**
отказ маскируется точно так же, и `failedCriterionIds` в этом случае
структурно не может нести правду (хардкод `[]` в `_cache_response`).

**Репро:**
1. Settings → Judges → Accuracy → Model = любая модель с невалидным
   provider ID (пример: тёзка реестра с суффиксом).
2. Settings → Model Registry → Edit любой ДРУГОЙ модели, используемой
   Fluency/Style → `params: {"max_tokens": 10}` → Save.
3. Document → Evaluate на любом параграфе.
4. Наблюдать: `200 OK`, `cached:true`, `failedCriterionIds:[]`, скоры
   выглядят полноценными (реальные числа + summary-текст), UI показывает
   только нейтральную плашку «cached», без какого-либо намёка, что live
   evaluation целиком провалилась.

**Артефакт:** сырые ответы `/api/paragraphs/58/evaluate` — см. таблицу,
шаг 14; сравнение с честным частичным путём — шаг 16 (тот же эндпоинт,
другая комбинация параметров даёт `cached:false,
failedCriterionIds:["accuracy"]` и корректный UI-баннер).

**Рекомендация:** когда `_cache_response` вызывается ПОСЛЕ реальных
live-попыток (а не как штатный fallback при отсутствии API-ключа), в ответ
нужно прокинуть `failedCriterionIds` = реальный список упавших id, и
фронтенду показывать ОБА сигнала одновременно (cached-бейдж + баннер про
конкретные причины), а не подавлять второй при первом.

### Н2 — MEDIUM — Параметры Model Registry не долетают до Refine/Evaluate; это неочевидно и никак не документировано в UI

**Что происходит.** `_client_for()` (app.py:878) для Refiner/Translator/
Grounding получает `params_override`, который **всегда** заменяет
собственные параметры модели из реестра параметрами независимого бага
(`refiner_config.params_json`, `translator_config.params_json`,
`grounding_config.params_json`). У Judge (`_judge_live`) — наоборот, params
берутся напрямую из `model.params_json` реестра БЕЗ override. Итог: одна и
та же поломка параметров (`max_tokens:10` в реестре) **ломает Test-кнопку
и Evaluate/Judge**, но **никак не влияет на Refine/Translate/Grounding** —
те продолжают использовать собственные (обычно рабочие) значения по
умолчанию.

**Почему это находка.** Ни Model Registry, ни карточка Refiner/Translator/
Grounding в Settings не дают пользователю понять эту асимметрию: строка
реестра показывает «max_tokens 10» рядом с той же самой моделью, которая
назначена рефайнером — интуитивно ожидаешь, что рефайнер тоже урезан, но
это не так. Комментарий в коде (`SettingsTab.tsx:944`, «owner call
2026-07-11: params visible there only») подтверждает, что это осознанное
решение — параметры Refiner/Translator/Grounding **не редактируются через
UI вообще** (только Model + Prompt в карточках). Значит, кампания T4 в
формулировке «own model with broken params for refiner» технически
недостижима через UI для max_tokens/temperature — только через подмену
самого provider ID (что мы и сделали для честного 502 в шаге 12).

**Репро:** таблица, шаги 7→12b (тот же реестровый `max_tokens:10`
одновременно ломает Test (шаг 8, честный провал) и НЕ ломает Refine
(шаг 12b, тихий успех — потому что рефайнер использует свой отдельный bag
параметров, а не реестровый).

**Рекомендация:** либо явно показать в UI Refiner/Translator/Grounding
карточках эффективные params (read-only, как уже сделано для Model
Registry — «Effective params»), либо синхронизировать источник правды.

### Н3 — SUSPECTED/LOW — `EvaluateBody.criterionIds` позволяет запросить оценку одного критерия напрямую, минуя UI-выбор

При прямом `POST /evaluate {"criterionIds":["fluency"]}` эндпоинт вернул
ПОЛНЫЙ набор из 3 скоров (включая accuracy/style), а не только fluency —
т.е. параметр `criterionIds` фильтрует, КАКИЕ критерии реально
ПЕРЕСЧИТЫВАЮТСЯ, но ответ всегда содержит latest-значения для ВСЕХ
enabled-критериев (ожидаемо по коду — `_para_score_views` возвращает
latest для всех). Через UI эта раздельная фильтрация недостижима (кнопка
Evaluate всегда шлёт все enabled criteriaIds) — так что риск на прод
UI-путь не распространяется, оставлено как SUSPECTED/дока-заметка, не баг.

### Н4 — LOW — Провайдерский `user_id` попадает в текст ошибки Test-эндпоинта (только этот путь, не Refine)

**[ремедиация: исправлена цитата.]** Ответ `Test` (`POST
/api/models/{name}/test`) на невалидный provider ID содержит НЕотредактированный
`'user_id': 'user_3DSjOtCFgWsPlqyYKDeAIpsKkPf'` — это внутренний
идентификатор аккаунта OpenRouter/провайдера, который прокидывается
как есть в `message` и рендерится прямо в карточке результата теста
(единственный корректный артефакт — `05-t4dup-test-failed.png`, где текст
`user_id` виден полностью и без маскировки). Причина: `test_model()`
(`app.py:1888`) пробрасывает `f"{type(e).__name__}: {e}"` напрямую, БЕЗ
`redact_error()`.

Ранее эта находка ошибочно ссылалась ещё и на `11-refine-502-mislabeled-evaluate.png`
как на второй пример утечки — это неверно: тот скриншот относится к
СОВСЕМ ДРУГОМУ эндпоинту (`/refine`, не Test) и на нём `user_id` УЖЕ
корректно замаскирован (`'[REDACTED]'`) — `redact_error()` там
применяется (`app.py:1710-1715`, подтверждено живой пересъёмкой, см. шаг
12 выше). Находка Н4 сужена строго до пути Test — он единственный, где
утечка реально есть.

Не секрет уровня API-ключа (проект хранит правило «никогда не логировать
секреты», это не совсем то), но это внутренний identifier провайдерского
аккаунта — потенциально полезен для фингерпринтинга/абузы, если демо
публично доступно. Стоит завести такую же `redact_error()`-фильтрацию и
для error-тела `test_model()` (единственного пути, где её сейчас нет —
у `/refine` и у judge-эндпоинта она уже есть).

### Н5 — LOW — Дубль-имя модели: 409 с сырым SQLite-текстом в UI

`POST /api/models` с уже существующим `name` возвращает
`409 {"error":"UNIQUE constraint failed: model.name"}` — технически
честный отказ (не тихая перезапись), но текст ошибки — сырое сообщение
SQLite, а не человекочитаемое «A model with this name already exists».
Показано пользователю дословно (см. `03-duplicate-name-409.png`).
Косметическая находка, не блокер.

### Н6 — известный паттерн (DRIVER ARTIFACT по независимой RCA, не app-баг) — двойной DELETE на один confirm

**[ремедиация: причинная формулировка исправлена по указанию аудитора.]**
При удалении модели через UI (Remove → confirm dialog → Accept) в сеть
ушло ДВА идентичных `DELETE /api/models/...-t4` запроса подряд (оба
`204`) — и в первичной сессии `t4`, и повторно в ремедиационной `t4b`
(тот же паттерн: `28. DELETE ... 204`, `29. DELETE ... 204`).

Это тот же паттерн, что уже неоднократно фиксировался в предыдущих
прогонах кампании (`translation-demo-bugs.md`, «double-DELETE N-й раз
подряд»). Независимое RCA-расследование
[`docs/reports/debugger-double-delete-rca.md`](../../debugger-double-delete-rca.md)
(2026-07-16, verdict: **DRIVER ARTIFACT — not a real app bug**) установило
через контролируемую четырёхвариантную репродукцию, что:
- на странице нет дублирующихся React-mount'ов и нет дублирующихся
  обработчиков (`querySelectorAll` по кнопке Remove/по `#root` — везде 1);
- два независимых code path (`VariantA.tsx` doc-delete, `SettingsTab.tsx`
  model-delete) НЕ разделяют общий код, но оба демонстрировали удвоение —
  то есть общий фактор НЕ в app-коде;
- корреляция 100%: удвоение возникает ТОЛЬКО на действиях, защищённых
  `window.confirm()` (блокирующий синхронный диалог), и ни разу — на
  действиях без него;
- эндпоинт `DELETE` безусловно идемпотентен (проверено отдельно) — второй
  вызов на уже удалённую строку тоже отдаёт `204`, так что «оба 204» не
  требует гонки/дубликата строки.

Вывод RCA: это артефакт автоматизации/драйвера, взаимодействующего с
блокирующим нативным `confirm()`, а не пропущенный клиентский guard в
самом приложении. **Убираю прежнюю причинную формулировку «фронтенд явно
не гасит повторный клик/эффект»** — она приписывала причину app-коду,
что RCA прямо опровергает.

**Честная нестыковка, которую стоит зафиксировать, а не скрывать.** RCA
метод (d) — «playwright-cli click + реальный нативный `confirm()` +
`dialog-accept`» — в контролируемом прогоне RCA дал ровно 1 DELETE и был
явно назван «чистым». Оба моих прогона T4 (`t4` и `t4b`) использовали
БУКВАЛЬНО ТУ ЖЕ последовательность (`playwright-cli click` на Remove →
нативный confirm → `dialog-accept`) и ОБА дали 2 DELETE. Это не
противоречит общему вердикту RCA (driver-artifact, не app-баг — корреляция
с `confirm()` подтверждается и в моём прогоне тоже), но ставит под
сомнение конкретное узкое утверждение RCA, что метод (d) сам по себе
всегда чист на `playwright-cli`. RCA сама помечает это открытым вопросом
(«retry BUG-4's exact e2e scenario a few more times to check flake rate
before closing it as "understood"») — эти два прогона T4 (t4, t4b) можно
засчитать как два дополнительных повтора именно этого сценария, оба
воспроизводящих удвоение. Не новая находка, не новая причинная гипотеза —
дополнительные данные к уже открытому вопросу RCA.

### Н7 — LOW/MEDIUM — новая находка [ремедиация] — Refine-отказы рендерятся под захардкоженным лейблом «Evaluate failed:»

Обнаружено при повторном разборе собственного скриншота
`11-refine-502-mislabeled-evaluate.png` (имя файла ещё в первичной сдаче
намекало на проблему суффиксом «-mislabeled-evaluate», но сама находка не
была оформлена текстом — упущение первой версии отчёта).

**Что происходит.** Баннер отказа на скриншоте 11 буквально гласит:
> `Evaluate failed: Error: POST /paragraphs/58/refine → 502: {"detail":{"detail":"refine_failed",...}}`

То есть ошибка Refine-запроса (`POST .../refine`) показана пользователю
под лейблом «Evaluate failed» — хотя Evaluate не вызывался. Причина —
общий код-путь: `InspectorPanel.tsx:166-169`

```tsx
{evalState.error && evalState.failedCriterionIds.length === 0 && !isCollapsed && (
  <div className="va-inspector-warning">
    Evaluate failed: {evalState.error}
  </div>
)}
```

рендерит `evalState.error` под ЖЁСТКО зашитым текстом «Evaluate failed:»
независимо от того, какой запрос реально его установил. А
`store.ts:562-596` (`refineParagraph`) на любой не-409 ошибке своего
собственного `apiRefineParagraph()`-вызова пишет ровно в то же поле:

```ts
} catch (e) {
  if (!String(e).includes('→ 409')) {
    set((s) => ({
      paraEvalState: {
        ...s.paraEvalState,
        [paraIdx]: { ...(s.paraEvalState[paraIdx] ?? defaultParaEval()), error: String(e) },
      },
    }));
  }
}
```

`refineParagraph` и `evaluateParagraph` используют ОДНО общее поле
`paraEvalState[idx].error`, а UI-компонент не различает источник — отсюда
неверный лейбл на любом honest-failure пути Refine (в T4 это шаг 12/шаг 8
воспроизведения в `t4b`, но баг общий, не специфичен для broken-model
сценария).

**Почему это находка, а не просто опечатка.** Пользователь, честно
получивший отказ Refine, читает «Evaluate failed» и может решить, что
проблема в Evaluate/судьях (Settings → Judges), а не в Refiner (Settings →
Refiner) — прямое противоречие между реальной причиной и подсказанным
местом починки. LOW-MEDIUM: сообщение не теряет данные и не маскирует
факт отказа (в отличие от Н1), просто указывает не на тот компонент.

**Артефакт:** `11-refine-502-mislabeled-evaluate.png` (оригинал, шаг 12) +
`15-refine-502-redacted-recapture.png` (ремедиационная пересъёмка,
подтверждает тот же лейбл на независимом повторе).

**Рекомендация:** параметризовать лейбл (`{refineStage ? 'Refine' : 'Evaluate'} failed:`
или завести отдельное поле `refineError`/`evaluateError` вместо одного
общего `error`).

## Провенанс данных

Все значения — реальные ответы прод-API (`GET`/`POST`/`PUT`/`DELETE
https://glossa-mt.com/api/*`), полученные через `fetch()` внутри
playwright-cli сессий `t4` (первичный прогон) и `t4b` (**[ремедиация]**
аудиторская пересъёмка, отдельный клон БД) или через клики в реальном
UI. Имена дубль-моделей `google/gemini-3.1-flash-lite-t4` /
`-t4b` и их параметры `{"max_tokens": 10}` — заданы напрямую по спеке T4
(владелец: `max_tokens=10`), не из manifest — это ЧАСТЬ сценария, не
тестовые «данные». Текст параграфа (§1, pid 58, «В Лагаше…») и его issues
— реальные seed-данные документа «World History — Selected Passages» (см.
`docs/testing/e2e-data.md`), идентичные в обеих сессиях (обе стартуют от
одного и того же golden). Никаких `GENERATED`/`WEB` данных в этом прогоне
не потребовалось. RCA-цитата в Н6 — из
`docs/reports/debugger-double-delete-rca.md` (2026-07-16, тот же репозиторий,
не внешний источник).

## LLM-операции (счётчик)

**Сессия `t4` (первичный прогон).** Бюджет до: `$0.39031 / 533 вызова`.
После: `$0.435199 / 568 вызовов`. **Δ = 35 вызовов, $0.0449** — все
реальные (Test×2 успешных + несколько ретраев/ошибочных попыток,
Refine×2 честных попытки (1 провал 502 + 1 успех), Evaluate× несколько
прогонов с разными комбинациями судей).

**[ремедиация] Сессия `t4b` (аудиторская пересъёмка).** Бюджет до:
`$0.475674 / 669 вызовов`. После: `$0.49349 / 679 вызовов`. **Δ = 10
вызовов, $0.0178** — Refine×1 (честный 502), Evaluate×1 (все 3 судьи
упали → cache-fallback), плюс несколько $0-терминальных попыток той же
природы.

**Итог по кампании T4 (обе сессии):** 45 LLM-операций, $0.0627 суммарно.
Общий кампанейский бюджет на момент старта `t4b` уже был на `$0.475674`
(накоплен другими параллельными сценариями кампании, не только T4) — в
пределах общего капа $5 без проблем. Правило «честный провал не тратит
бюджет впустую» подтвердилось и во второй сессии: почти все
$0-стоимостные попытки (`costUsd:null`/`0.0`) — терминальные ошибки
(`budget.settle(est, 0.0, gen)`), реально списаны деньги только за
успешные вызовы (Test truncated $0.000043, живые Fluency/Style
пересчёты).

## Восстановление — итог

**Сессия `t4`:**
- **Model Registry**: 4 модели (без дубля), params byte-identical baseline.
- **refiner-config / grounding-config / translator-config**: modelName +
  params byte-identical baseline (все указывают на
  `google/gemini-3.1-flash-lite` с исходными params).
- **criteria**: все 3 (`accuracy/fluency/style`) снова на
  `google/gemini-3.1-flash-lite`, `enabled:true`.
- **Параграф 58** (§1, «В Лагаше…») — единственное НЕ восстановленное:
  содержит РЕАЛЬНУЮ ревизию от успешного Refine (шаг 12b) — issues
  `accepted`, target переписан. Это НЕ входит в скоуп восстановления по
  спеке T4 (е) — там речь только о конфигах моделей, не о содержимом
  документа; и по hard invariant «Never delete LLM predictions» откатывать
  ревизию удалением было бы само по себе нарушением. Сессия эфемерна
  (собственный клон БД по `glossa_sid`) — golden-документ не затронут в
  принципе, это подтверждается архитектурой сессионной изоляции
  (`docs/testing/e2e-data.md` § Session isolation), отдельная сверка
  md5 golden не требуется на уровне T4-агента (входит в оркестраторскую
  сверку по всей кампании).

**[ремедиация] Сессия `t4b`** (собственный отдельный клон, независимый
baseline/restore цикл): те же 5 конфиг-секций (models/refiner-config/
grounding-config/translator-config/criteria) сверены `JSON.stringify` до
и после — **все 5 EQUAL=true**, байт-идентично своему собственному
baseline. Модель `google/gemini-3.1-flash-lite-t4b` удалена через UI
(Remove → confirm → Accept). Полные тела: `scratchpad/t4b/baseline/configs.json`
(до) и `configs-after.json` (после). Финальный скриншот реестра:
`17-registry-restored-t4b-recapture.png` — этот файл байт-идентичен
`14-registry-restored-final.png` (MD5 совпадает), но, в отличие от пары
13-inspector/13-scrolled (которая была случайным дублем одного и того же
незменившегося момента и была удалена), здесь совпадение ОЖИДАЕМО и само
по себе является доказательством: оба скриншота — это Model Registry
ПОСЛЕ восстановления в двух НЕЗАВИСИМЫХ сессиях (`t4` и `t4b`), и оба
показывают одну и ту же корректную baseline-конфигурацию (4 модели, те же
params) — то, что они визуально неразличимы, подтверждает, а не
дискредитирует claim о byte-restore. Оставлен как есть (не удалён).

## Что не тестировалось

- **Сравнение 2-из-3 vs 1-из-3 упавших судей** — не выполнено: код
  обработки в `evaluate()` симметричен по количеству элементов `failed`
  (единственная развилка — `if not succeeded` = ВСЕ упали vs частично),
  так что 1-из-3 и 2-из-3 прошли бы по одной и той же ветке; проверка
  1-из-3 уже покрывает эту логику. Не вижу дополнительной ценности для
  бюджета времени/LLM-вызовов кампании.
- **`grounding-config` с ломаными params** — не тестировалось напрямую (в
  UI нет отдельного шага в T4-спеке для grounding; открыт сам факт
  архитектурной идентичности grounding/refiner/translator по параметрам
  через код, но живого прогона Term-grounding с битой моделью не делал —
  вне явного скоупа T4, зафиксировано в Н2 как общий паттерн).
- **budget_exhausted-путь** (упомянутый в контексте задачи как known
  investigation) — не воспроизведён: бюджет на протяжении всего прогона
  оставался далеко от капа ($0.39→$0.44 из $100000), классификатор
  `budget_exhausted` не сработал ни разу; ничего добавить к существующему
  расследованию нет.
