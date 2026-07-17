# T2 — Китайский язык: пределы языковой агностичности (прод glossa-mt.com)

Дата: 2026-07-17 · Агент: e2e-tester (Fable) · Сессия: playwright-cli `-s=t2` (эфемерный клон БД, golden не тронут) · Спека: [2026-07-17-e2e-mega-campaign.md § T2](../../superpowers/specs/2026-07-17-e2e-mega-campaign.md)

## Вердикт: PASS-WITH-FINDINGS

Минимальная планка PASS выдержана: **ни одного крэша, ни одного вечного спиннера, 0 JS-ошибок за весь прогон** (консоль проверялась после каждого крупного шага), CJK рендерится везде корректно, офсеты подсветки идеальны (55/55 терминов на двух документах), export валиден побайтово. При этом найдено **1 CRITICAL, 2 HIGH, 2 MEDIUM и 4 LOW** — все воспроизведены и задокументированы ниже. Кейс статьи Figure 1b (秦朝 → Q7183) работает в ¶1, **но тот же термин в ¶3 уходит в телесериал Q999148 с зелёным статусом — детерминированно, 2/2 прогона**.

## План сценария и статус

| Подшаг спеки | Статус |
|---|---|
| Upload pair zh→en (paste, 5 CJK-абзацев) | ✅ выполнен |
| (а) термы распознаны, CJK-офсеты верные | ✅ выполнен (программная сверка всех офсетов) |
| (б) грундинг 秦朝→Q7183, 长城→Q12501 | ✅ выполнен; Q7183 подтверждён в ¶1/¶4, **长城 непроверяем — не извлечён (находка F2)** |
| (в) попап/глоссарий рендерят CJK | ✅ выполнен |
| (г) судьи: скоры + осмысленные issues | ✅ выполнен (warming 5/5 на zh→en; live Evaluate на zh→ru) |
| (д) второй заход zh→ru | ✅ выполнен (file-upload источника + paste перевода) |
| (е) export .md, CJK не побит | ✅ выполнен (оба документа, побайтовая сверка с фикстурами) |
| Удаление своих документов через UI | ✅ выполнен (осталась только golden «World History») |

Не выполнялось: xlsx-export (вне контракта T2), проверка Ranking/Settings (принадлежат T4/T7), server-side верификация причин пропуска ¶2 (нет доступа к прод-логам из этой роли — зафиксировано как клиентски наблюдаемый факт).

## Таблица шагов

| Шаг | Данные (provenance) | Ожидание | Факт | Вердикт | Артефакт |
|---|---|---|---|---|---|
| 1. Открыть прод | — | лендинг отвечает | заголовок + пикер документов, консоль 0 ошибок | pass | [01-landing.png](../shots/campaign/t2/01-landing.png) |
| 2. Blank document, paste zh + языки Chinese/English | `docs/testing/e2e-campaign/t2-zh-source.txt`, `t2-en-translation.txt` (манифест § Campaign fixtures) | счётчики честные | Source «5 ¶ · 345 chars», Translation «5 ¶ · 1498 chars» | pass | [02-upload-form-filled.png](../shots/campaign/t2/02-upload-form-filled.png) |
| 3. Next → выравнивание | те же | 5 строк, CJK-пунктуация цела | 5 согласованных строк, 。「」《》 отрисованы | pass | [03-alignment-preview.png](../shots/campaign/t2/03-alignment-preview.png) |
| 4. Create + warming | warming checkbox ON | прогресс без зависаний | «warming 1/5…4/5» → done; §-скоры появились; «Extracting terminology…» → chip Terms | pass | [04-warming-progress.png](../shots/campaign/t2/04-warming-progress.png) |
| 5. (а) Подсветка терминов | документ id=18 | спаны ровно на сущностях | 27 терминов; DOM-сверка: каждый спан = точная surface-форма; полный текст абзацев побайтово равен фикстуре; API-сверка `context[charStart:charEnd]==sourceSurface` — **27/27 OK** | pass | [05](../shots/campaign/t2/05-terms-highlight-overview.png), [07-cjk-offsets-para1.png](../shots/campaign/t2/07-cjk-offsets-para1.png) |
| 6. (б) Глоссарий: QID | сверка с Wikidata API (wbgetentities, 2026-07-17) | 秦朝→Q7183, 长城→Q12501 | ¶1: 秦朝→Q7183 ✅ (Figure 1b работает); ¶4: 秦→Q7183 ✅; **¶3: 秦朝→Q999148 «The Qin Empire Ⅰ» (телесериал!) — зелёный «unambiguous · label match»**; **长城 в глоссарии отсутствует** | **FAIL → F1, F2** | [06-glossary-cjk.png](../shots/campaign/t2/06-glossary-cjk.png) |
| 7. (в) Попап CJK | клик по 秦朝 в ¶3 и ¶1 | CJK рендерится, трейс читается | оба попапа корректны; ¶3 показывает Source lemma **«династия Цинь»** и телесериал; ¶1 — lemma 秦朝 и Q7183 | pass (рендер) / **BUG F1, F3** (содержимое) | [08](../shots/campaign/t2/08-popover-qinchao-wrong-qid.png), [09](../shots/campaign/t2/09-popover-qinchao-correct-q7183.png) |
| 8. (б) Трейс глоссария 秦朝 | expand строки Q999148 | путь грундинга виден | «SEARCH: prefix·lemma династия Цинь 1 hit → EXACT: 1 exact match — label_ru → resolved_by: exact_label, chosen Q999148, no LLM call»; Q7183 был среди 4 кандидатов | **BUG F1** (полная причинная цепочка) | [10-glossary-trace-qinchao.png](../shots/campaign/t2/10-glossary-trace-qinchao.png) |
| 9. (г) Судьи zh→en | warming-скоры doc 18 | скоры + осмысленные issues | §1 9.3 / §3 10.0 …, aggregate 9.7; issues цитируют идиому 车同轨, предлагают «uniform carriage gauges»; per-criterion summaries содержательные | pass | [07](../shots/campaign/t2/07-cjk-offsets-para1.png), [11-scores-panel.png](../shots/campaign/t2/11-scores-panel.png) |
| 10. (е) Export .md doc 18 | скачан через UI | плоский текст (контракт P1), не побит | `# título + 5 абзацев`, 0 таблиц, 0 U+FFFD, все 5 абзацев **побайтово равны** `t2-en-translation.txt` | pass | [t2-files/qin-and-han-dynasties-t2-18.md](t2-files/qin-and-han-dynasties-t2-18.md) |
| 11. (д) Второй заход zh→ru | `t2-zh-source.txt` (file-upload), `t2-ru-translation.txt` (paste) | документ создаётся | «Chinese → Russian · 5¶», выравнивание 5 строк | pass | [12-t2b-alignment-zh-ru.png](../shots/campaign/t2/12-t2b-alignment-zh-ru.png) |
| 12. Warming T2b | checkbox ON | прогресс или честная ошибка | API: `precompute {status: stopped, done 0/5, errorReason: budget_exhausted}`; **UI: Score «—», ни бейджа, ни тоста, ни текста ошибки** (проверено DOM-поиском /budget\|error\|failed/) | **BUG F4** | [13-t2b-budget-exhausted-ui.png](../shots/campaign/t2/13-t2b-budget-exhausted-ui.png) |
| 13. Live Evaluate §1 (zh→ru) | кнопка Evaluate ↻ | скор или честная ошибка | POST /evaluate → 200; Score 8.2; accuracy 9 / fluency 8 / style 8, issues с русскими предложениями («систему мер и весов», «на последующие два тысячелетия») | pass (но подчёркивает F4: бюджет уже вернулся, а precompute не ретраится) | [14-t2b-evaluate-zh-ru.png](../shots/campaign/t2/14-t2b-evaluate-zh-ru.png) |
| 14. Термы T2b | API doc 19 | воспроизводимость | 28 терминов, офсеты **28/28 OK**; ¶2 снова **0 терминов**; 秦朝(¶3) снова **Q999148 green exact_label**; 16/28 русских лемм; 1 термин `judge_unavailable` (честное состояние) | **BUG F1, F2, F3 воспроизведены 2/2** | [15-t2b-popover-repro.png](../shots/campaign/t2/15-t2b-popover-repro.png) |
| 15. Export .md doc 19 | через UI | RU-текст не побит | 5 абзацев побайтово = `t2-ru-translation.txt`, 0 U+FFFD | pass | [t2-files/qin-and-han-zh-ru-t2b-19.md](t2-files/qin-and-han-zh-ru-t2b-19.md) |
| 16. Удаление обоих документов | 🗑 + confirm | документы удалены | оба удалены; остался только golden «World History»; **на каждый confirm — 2 запроса DELETE** (77/79 для id 19, 84/86 для id 18, все 204) | pass + **BUG F5** | [16-cleanup-final.png](../shots/campaign/t2/16-cleanup-final.png) |
| 17. Финальная консоль | — | 0 ошибок | «Total messages: 0 (Errors: 0, Warnings: 0)» за весь прогон | pass | вывод `playwright-cli console` в шагах выше |

## Термы → ожидаемый QID → фактический QID → состояние

Сверка фактических QID с Wikidata `wbgetentities` (live, 2026-07-17). Полная таблица по ключевым терминам обоих прогонов:

| Термин (¶) | Ожидание | Факт zh→en (doc 18) | Факт zh→ru (doc 19) | Состояние UI | Вердикт |
|---|---|---|---|---|---|
| 秦朝 ¶1 | Q7183 Qin dynasty | **Q7183** ✅ (lemma 秦朝) | **Q7183** ✅ | 🟡 context-resolved · AI, pairAccuracy 🟢 | pass — кейс Figure 1b |
| 秦朝 ¶3 (×2) | Q7183 | **Q999148 «The Qin Empire Ⅰ» — телесериал** (lemma «династия Цинь») | **Q999148** — то же | 🟢 **unambiguous · exact label match**, pairAccuracy 🔴 «Term absent from translation» | **CRITICAL F1** |
| 秦(朝) ¶4 | Q7183 | Q7183 ✅ (lemma «Цинь») | Q7183 ✅ | 🟡 | pass |
| 长城 ¶2 | Q12501 Great Wall | **термин не извлечён** | **не извлечён** | — (¶2 вообще без терминов) | **HIGH F2** |
| 汉朝 ¶3/¶4 | Q7209 Han dynasty | Q7209 ✅ | Q7209 ✅ | 🟡 | pass |
| 司马迁 ¶5 | Q9372 Sima Qian | Q9372 ✅ | Q9372 ✅ | 🟡 | pass |
| 秦始皇 ¶1 | Q7192 | Q7192 ✅ | — (в T2b ¶1 набор чуть другой) | 🟡 | pass |
| 刘邦 ¶3 | Q7210 (= Emperor Gaozu) | Q7210 ✅ (lemma «Лю Бан») | Q7210 ✅ | 🟢 label match | pass |
| 咸阳 ¶3 | Q497341 | Q497341 ✅ (lemma «Сяньян») | ✅ | 🟢 | pass |
| 项羽 ¶3 | Q182266 | Q182266 ✅ | ✅ | 🟢 | pass |
| 长安 ¶3 | Chang'an | Q6501000 ✅ (ancient capital — верный) | ✅ | 🟡 | pass |
| 汉武帝 ¶4/¶5 | Q7225 | Q7225 ✅ | ✅ | 🟡 | pass |
| 丝绸之路 ¶4 | Q36288 | Q36288 ✅ | ✅ | 🟢 | pass |
| 儒学 ¶4 | Q9581 | Q9581 ✅ | ✅ | 🟢 | pass |
| 史记 ¶5 | Q272530 | Q272530 ✅ | ✅ | 🟡 | pass |
| 黄帝 ¶5 | Q29201 | Q29201 ✅ | ✅ | 🟡 | pass |
| 郡县制 ¶1 | junxian system | Q5360871 ✅ (zh-label 郡县制; en-label нет) | ✅ | 🟡; в глоссарии отображается «Q5360871Q5360871» | pass + LOW F7 |
| 纪传体 ¶5 | jizhuanti | Q1619411 ✅ | ✅ | 🟡 | pass |

Итог грундинга: **из 26 фактически заземлённых поверхностей неверен ровно один QID (秦朝 ¶3), но он единственный подписан максимальной уверенностью**; 1 термин в T2b — честный `judge_unavailable`.

## Проверка CJK-офсетов (явная)

1. **Визуально**: [07-cjk-offsets-para1.png](../shots/campaign/t2/07-cjk-offsets-para1.png) — рамки лежат ровно на 秦朝/秦始皇/分封制/郡县制/中央集权制度, границы не съезжают ни на символ; [05](../shots/campaign/t2/05-terms-highlight-overview.png), [15](../shots/campaign/t2/15-t2b-popover-repro.png).
2. **DOM-сверка**: текст каждого `va-term-span-source` (после удаления индекс-бейджа) в точности равен surface-форме; конкатенация абзаца побайтово равна фикстуре (5/5 абзацев, скрипт в прогоне).
3. **API-сверка**: `context[charStart:charEnd] == sourceSurface` для **27/27 (doc 18) и 28/28 (doc 19)** терминов — офсеты считаются в Unicode code points, мультибайтность не ломает. Пример: 秦朝 ¶1 = [8:10] после «公元前二二一年，» (8 символов).

## Находки

| # | Severity | Находка | Репро | Артефакт |
|---|---|---|---|---|
| F1 | **CRITICAL** | 秦朝 (¶3, ×2 mentions) заземлён в **Q999148 «The Qin Empire Ⅰ» (телесериал)** со статусом 🟢 «Unambiguous (exact label match)». Причинная цепочка из трейса: NER выдал **русскую** лемму «династия Цинь» → wbsearchentities prefix по лемме → ровно 1 exact match **по ru-label телесериала** («Династия Цинь», проверено Wikidata API; у Q7183 ru-label «Цинь») → `resolved_by: exact_label`, LLM-дизамбигуация **пропущена**, хотя Q7183 был в кандидатах. Каскад: recommended translation = «The Qin Empire Ⅰ», pairAccuracy 🔴 «Term absent from translation» — при том что «Qin dynasty» в переводе есть. Воспроизведено 2/2 (doc 18 и 19). | Загрузить t2-zh-source zh→en или zh→ru, дождаться термов, открыть 秦朝 в ¶3 | 08, 10, 15; Wikidata-вывод в прогоне |
| F2 | **HIGH** | **¶2 (长城/Great Wall) — 0 терминов, 2/2 прогона.** Абзац с 长城×2, 秦始皇, 城墙 полностью пропущен экстракцией; `termsStatus: done`, никакой индикации сбоя на абзаце. Ожидаемый референс 长城→Q12501 из-за этого непроверяем. Клиентски неотличимо «LLM не нашёл сущностей» от «per-paragraph вызов упал и был проглочен» — нужен серверный лог. | тот же, смотреть ¶2 / Glossary | 05, 06; API `paraTerms=[5,0,9,7,7]` |
| F3 | **HIGH** (системная) | **Русские леммы у CJK-терминов: 15/27 (doc 18) и 16/28 (doc 19)** («династия Цинь», «Лю Бан», «Сяньян», «Великий шёлковый путь»…) — NER/лемматизатор заточен на русский и на китайском тексте недетерминированно переводит леммы на русский (¶1/¶5 — сурфейсы, ¶3/¶4 — русский). Обычно ru-label-поиск всё равно находит верную сущность, но это прямая причина F1 и бомба замедленного действия для любых не-ru пар. Плюс бейдж контекста «RU» в трейсе глоссария на китайском тексте (см. 10). | API traceJson обоих документов | 10; выборка лемм в прогоне |
| F4 | **MEDIUM** | **Warming остановился по `budget_exhausted` абсолютно молча**: doc 19 создан с включённым чекбоксом скоринга, `precompute {status: stopped, 0/5, errorReason: budget_exhausted}`, а в UI — Score «—» и ноль сообщений (DOM-поиск /budget\|exhaust\|error\|failed/ пуст). Через ~7 минут ручной Evaluate прошёл (200, скор 8.2) — бюджет вернулся, но precompute не ретраится и не сообщает, что сдался. Не «вечный спиннер», но и не «честное состояние». | создать документ при исчерпанном бюджете кампании | 13, 14; API-вывод в прогоне |
| F5 | MEDIUM-LOW | **Двойной DELETE на одно подтверждение** — на каждый confirm удаления документа уходит 2 × `DELETE /api/documents/{id}` (оба 204). Известный открытый баг (памятка 2026-07-16), теперь воспроизведён на прод-документах. Идемпотентно, вреда нет. | удалить документ через 🗑 | network-лог: 77/79 (id 19), 84/86 (id 18) |
| F6 | LOW | Бейдж языка контекста в трейсе глоссария — «RU» на китайском источнике (жёстко зашитый source=RU). | expand любой строки глоссария | 10 |
| F7 | LOW | Термин без en-label (Q5360871, 郡县制) отображается в колонке Wikidata как «Q5360871Q5360871» (label-фоллбэк = QID, визуальное дублирование). | Glossary, строка 郡县制 | 06 |
| F8 | LOW | Счётчик символов зависит от пути ввода: file-upload того же файла = «346 chars», paste (без хвостового \n) = «345 chars» — хвостовой перевод строки считается символом. | сравнить paste и upload одного файла | шаги 2 и 11 |
| F9 | SUSPECTED-LOW | Первый клик по чипу «Terms» сразу после завершения экстракции не включил оверлей (класс `on` не появился, 0 спанов); второй клик отработал. Единично, целенаправленно не воспроизводилось. | клик по Terms сразу после появления чипа | вывод eval в прогоне |

Позитив, который важно зафиксировать: офсеты на мультибайтных строках — образцовые (55/55); попапы и глоссарий рендерят CJK без артефактов; выравнивание/счётчик абзацев на тексте без пробелов честные; судьи осмысленно работают и с en-, и с ru-target (цитируют 车同轨, предлагают правки на языке перевода); export-контракт P1 (плоский .md) выполняется побайтово; `judge_unavailable` — пример честной деградации.

## Provenance данных

| Значение | Источник |
|---|---|
| Китайский исходник (5 абзацев) | `docs/testing/e2e-campaign/t2-zh-source.txt` (манифест § Campaign fixtures) |
| Английский перевод | `docs/testing/e2e-campaign/t2-en-translation.txt` |
| Русский перевод | `docs/testing/e2e-campaign/t2-ru-translation.txt` |
| Названия документов «Qin and Han dynasties (T2)», «Qin and Han zh-ru (T2b)» | GENERATED: технические заголовки прогона (метка сценария), контент-значений не несут |
| Языковые поля «Chinese»/«English»/«Russian» | задание T2 (free-text поля) |
| Ожидаемые QID Q7183, Q12501 | спека кампании § T2 |
| Верификация фактических QID (21 сущность) | WEB: https://www.wikidata.org/w/api.php (wbgetentities, 2026-07-17) |

GENERATED-файлов данных не создавалось.

## LLM-операции (бюджетный учёт)

Клиентски наблюдаемое + серверные счётчики из API:
- doc 18 (zh→en): warming **5/5 succeeded** (полный evaluate по 3 критериям на абзац); термы: 27, из них **19 × llm_disambiguation** + 8 exact_label (без LLM); плюс серверные extraction (~5 вызовов, по абзацу) и pairAccuracy-судья (~27) — точное число вызовов извне не видно.
- doc 19 (zh→ru): warming **0/5** (budget_exhausted); термы: 28 — **19 × llm_disambiguation**, 8 exact_label, 1 judge_unavailable; **1 ручной evaluate** (200).
- Итого понесённых LLM-операций: измеримо — 6 evaluate-циклов и 38 llm-дизамбигуаций; с учётом extraction/pairAccuracy оценка **~100–115 вызовов flash-lite** на весь сценарий — в рамках бюджета кампании (сотни вызовов; ~$0.06 стоил один warming-пакет).

## Покрытие: что не тестировалось и почему

- xlsx-export, Ranking, Settings, Refine — принадлежат сценариям T4/T6/T7 кампании.
- Серверная причина пустого ¶2 (упавший вызов vs честный пустой ответ LLM) — нет доступа к прод-логам в этой роли; зафиксирован клиентский факт 2/2.
- Misaligned-создание (source ≠ target ¶) — контракт T1(г), не дублировался.
- AI-translate путь для zh — сознательно не запускался (T2 задан как Upload pair; и бюджет в середине прогона уже падал в exhausted).
