# T3 — Шторм конкурирующих правок (e2e mega-campaign, prod glossa-mt.com)

- Дата: 2026-07-17, ~10:55–11:25 MSK
- Исполнитель: e2e-tester (Fable), playwright-cli, именованная сессия `-s=t3` (свежая cookie `glossa_sid` → собственный клон БД; golden не затрагивался, `X-Golden-Session` не использовался ни разу — в network-логе только стандартные same-origin запросы).
- Объект: документ **«World History — Selected Passages»** (id 10, единственный в пикере), §1 = paragraph id 58, в черновике 6 open issues (131–136).
- Спека: `docs/superpowers/specs/2026-07-17-e2e-mega-campaign.md` § T3. MANIFEST: `docs/testing/e2e-data.md` (прочитан до старта; T3 не требует загрузочных фикстур — работает по seeded-документу из манифеста).
- Артефакты: скрины `docs/reports/e2e/shots/campaign/t3/` (19 шт., включая 3 из аудит-довёрки), полный network-лог `t3-network-log.txt`, дифф §1 `t3-diff-step-a.txt`, тексты до/после `t3-p1-target-baseline.txt` / `t3-p1-actual-after-a.txt`, довёрочные `t3-verify-console-dump.txt` и `t3-verify-revision-after-refine.json` (все рядом с этим отчётом).
- **Аудит-довёрка (2026-07-17, после независимого аудита):** аудитор вернул FAIL по 4 пунктам — арифметика в шаге (б) и в итоговой раскладке, недоказанное «Best переехал» на скрине `15-final-refine-best-moved.png` (сам скрин противоречил тексту), два claim'а без файлового артефакта. Ниже все 4 исправлены; новый браузерный проход (свежий клон `-s=t3`) подтвердил находку F4.

## Вердикт: **PASS-WITH-FINDINGS**

Все guard'ы держат шторм (10 кликов → ровно 1 POST, дважды доказано network-логом); текст после оверлап-последовательности детерминированно объясним (побайтовое совпадение с симуляцией); история ревизий на бэкенде связна после каждого из 5 раундов (ровно 1 CURRENT, 1 BEST, ни одной осиротевшей записи) — данные API никогда не портились и не терялись ни в одном сценарии. Найдены 4 проблемы: F1 MEDIUM (молчаливое исчезновение issues после 422 в Accept all), F2 LOW (Reset не блокируется во время Refine; хвостовой auto-evaluate пере-оценивает уже сброшенный документ), F3 INFO (консольный шум 422), F4 MEDIUM (панель истории ревизий не рефетчится после Refine без reload — подтверждено в аудит-довёрке 2026-07-17).

## План сценария (зафиксирован до прогона)

| # | Подшаг | Ожидание | Статус |
|---|---|---|---|
| 0 | Прекондиция: лендинг, док, baseline §1 | отвечает; 6+ issues | ✅ выполнен |
| а | Принять issues §1 в обратном порядке | оверлапы → «outdated»; текст не портится | ✅ выполнен (с оговоркой: в §1 оверлапов нет — см. шаг) |
| б | Accept all по оставшимся | применение + честные outdated | ✅ выполнен (глобальный Accept all 13, с реальными оверлапами в p61/p63/p65) |
| в | 10 синхронных кликов Refine | ровно 1 POST | ✅ выполнен |
| г | Во время Refine: Accept/Dismiss/Evaluate/Reset | блок или честная очередь | ✅ выполнен (2 захода: с реальным Reset-race и «чистый» замер) |
| д | 10× Evaluate на другом абзаце | ровно 1 POST | ✅ выполнен (§2/p59) |
| е | 5× (Refine → Restore → Refine → Reset) | история связна после каждого раунда | ✅ выполнен |
| — | JS-консоль после каждого шага | 0 непойманных ошибок | ✅ (0 uncaught, agent-narrated для основного прогона + file-backed 0/0 для аудит-довёрки; 2 сетевых 422-записи — см. F3) |
| — (довёрка) | Аудит-фикс F4: History-панель после Refine, с/без reload | панель отражает новый Best/Current без ручного reload | ❌ выполнен, баг подтверждён → F4 |

## Таблица шагов: шаг → данные (provenance) → факт → вердикт → артефакт

| Шаг | Данные (provenance) | Факт | Вердикт | Артефакт |
|---|---|---|---|---|
| 0. Лендинг + открытие дока | прод live: `GET /api/documents` → `[{"id":10,"title":"World History — Selected Passages",…}]` | пикер с 1 карточкой; док открылся; §1 «6 active issues» | pass | `00-landing.png`, `01-baseline-p1-issues.png` |
| 0. Baseline §1 | live: `GET /api/documents/10`, `GET /api/paragraphs/58/revisions` | target 961 зн.; issues 131–136 open; спаны фрагментов ПОПАРНО НЕ ПЕРЕСЕКАЮТСЯ (позиции 62–115, 212–263, 374–425, 496–557, 612–621, 651–691); история: 1 seed-ревизия (279) + унаследованные от клона (126 upload BEST, 277/278 refine) | pass | `t3-p1-target-baseline.txt`; расчёт спанов в отчёте агента |
| а. Обратный порядок: Accept 136→135→134→133→132→131 (через UI-кнопки карточек) | live UI | все 6 приняты по одному; статусы через API после каждого клика: `open→accepted` строго по одному; длина текста 961→941→937→909→906→907→909 | pass | `02-after-reverse-accepts.png`; network-лог зап. 17–27 (6× `POST /api/paragraphs/58/apply-edit` → 200) |
| а. Проверка детерминизма | симуляция: baseline + 6 замен (fragment→suggestion) | **expected == actual: True** (побайтово) | pass | `t3-diff-step-a.txt` (word-diff ниже) |
| а. Оговорка | — | в pristine-§1 оверлапов нет ⇒ «outdated»-путь на этом подшаге физически недостижим; перенесён на (б), где оверлапы есть | honest deviation | расчёт спанов |
| б. Accept all (13 оставшихся по 5 абзацам) | live UI, кнопка «Accept all 13», confirm-диалог «Accept 13 issues across 5 paragraphs? All suggestions are applied…» | итог: **7 accepted, 6 outdated**. Прогноз до клика: p61 оверлапы (141,144),(142,139) + 143 fragment-not-in-text; p63 оверлап (145,146); p65 148/149 not-in-text — ровно эти 6 стали outdated. Текст всех 5 абзацев побайтово = симуляции («ALL deterministic: True») | pass | `03-after-accept-all.png`; network зап. 32–42: **7× apply-edit 200** + **2× apply-edit 422** (p65) + 2× `PATCH /api/issues/{148,149}` (клиент честно пометил outdated) — пересчитано из `t3-network-log.txt` при аудит-довёрке (7×200 согласуется с «7 accepted»; было ошибочно написано «9×») |
| б. UI-сообщение о 422 | live UI | **молчание**: карточки исчезли («0 active issues», «No active issues»), баннера/тоста нет; отличить outdated от accepted в UI невозможно | **FAIL → F1** | `04-p8-outdated-issues.png` |
| Reset до pristine (для в–д) | live UI, confirm «…Live scores and issues will be archived…» | p1 = 961 зн. (= baseline), 19 issues снова open | pass | `05-after-reset-baseline.png` |
| в. Шторм Refine: 10× `el.click()` за 0.5 мс + dblclick | live UI §1 | network-лог: **ровно 1** `POST /api/paragraphs/58/refine` (зап. 47) + 1 парный auto-evaluate (зап. 48); refine выполнился, 5/6 issues сняты | pass | network-лог; JSON-ответ клик-цикла `{"clicks":10,"dblclick":true,"ms":0.5}` |
| г-1. Race: клики Accept/Dismiss/Evaluate/Reset во время Refine | live UI | Accept/Dismiss/Evaluate → **0 лишних POST**; Reset → confirm-диалог ОТКРЫЛСЯ (кнопка не заблокирована), после подтверждения: сервер сериализовал (refine-ревизия 309 → reset-ревизия 310 seed CUR), хвостовой auto-evaluate (зап. 51) отработал ПОСЛЕ reset по seed-тексту — все 7 новых фрагментов issues (183–189) найдены в текущем seed-тексте, скоры описывают именно seed-ошибки (Ur-Nanshe и т.д.). Порчи нет, но после «Reset к исходному состоянию» пользователь без нажатия Evaluate получает свежие live-скоры и НОВЫЙ набор из 7 issues вместо 6 архивных | **quirk → F2** | network зап. 49–51; `06-post-race-state.png`; JSON-проверка фрагментов |
| г-2. Чистый замер состояний mid-refine (без Reset) | live UI, probes на 100/500/1400 мс | во время Refine: кнопки Refine/Evaluate заменены на loading (не найдены по тексту), карточки issues скрыты (0 Accept-кнопок), Dismiss disabled, Reset — **enabled**; адверсариальные клики → 0 POST | pass (+ подтверждение F2) | probes-JSON в отчёте агента; network зап. 56–57; `07-after-g-round.png` |
| д. Шторм Evaluate: §2 (p59), 10× click + dblclick | live UI | network-лог: **ровно 1** `POST /api/paragraphs/59/evaluate` (зап. 58) | pass | network-лог; `08-p2-evaluate-storm.png` |
| е. 5 раундов Refine→Restore→Refine→Reset (§1) | live UI (Restore через `history-restore-{id}` на вкладке Scores) | каждый раунд даёт каноническую цепочку `refine → restore → refine → seed(reset)`: р1: 319/320/321/322; р2: 330/331/332/333; р3: 341/342/343/344; р4: 352/353/354/355; р5: 363/364/365/366. После КАЖДОГО раунда: nCurrent=1, nBest=1, все id уникальны, осиротевших нет. Скачки id по 8 = reset пишет seed-ревизию каждому из 8 ¶ — объяснимо. UI-история (35 строк после «+27 more») 1:1 с API | pass | `09…13-round{1..5}-history.png`, `14-history-expanded-final.png` |
| е. Контроль связки score↔revision (API) | live: контрольный Refine БЕЗ последующего Reset, `GET /api/paragraphs/58/revisions` | API отдаёт корректно и сразу: новая ревизия (374 в первом прогоне; 287 в аудит-довёрке) с `aggregate` заполнен, `isCurrent=true`, `isBest=true` — Best на бэкенде корректно переезжает с ревизии 126 (6.89) на новую. «Not scored» у раундовых ревизий = следствие анонсированного архивирования live-скоров при Reset, НЕ баг | pass | `t3-verify-revision-after-refine.json` (файловый артефакт аудит-довёрки, см. F4) |
| е. Контроль связки score↔revision (UI, без перезагрузки) | live UI, тот же Refine, скрин снят СРАЗУ после завершения пайплайна, БЕЗ reload | панель «REVISION HISTORY» в инспекторе **противоречит** API: заголовок всё ещё «▤ BEST 6.9», верхняя строка списка — старая CURRENT-ревизия «12 hours ago · not scored», новой ревизии (287, agg 9.67) в списке нет вовсе. Верхний блок агрегата над панелью при этом обновился корректно («9.7 (prev 6.9)»). | **FAIL → F4** | `17-verify-after-refine-noreload.png` |
| е. Контроль F4: полная перезагрузка страницы | live UI, `reload` → переоткрыть документ → §1 → Scores tab | после полного reload панель ИСПРАВЛЯЕТСЯ: «▤ BEST 9.7», CURRENT-строка = «9.7 · 2 min ago» — совпадает с API. Т.е. проблема — не порча данных, а чисто фронтовый рассинхрон: History-панель не рефетчится после refine в той же SPA-сессии, только по hard reload | **F4 confirmed (MEDIUM)** | `18-verify-after-reload-history.png` |
| Финальная консоль (основной прогон) | — | 0 uncaught JS-ошибок за весь прогон; 2 записи «Failed to load resource: 422» (ожидаемые apply-edit p65) — **agent-narrated, НЕ файловый артефакт**: `console`-вывод читался из tool-транскрипта после каждого крупного шага, но не сохранялся в файл; исходная браузерная сессия закрыта и невоспроизводима 1:1 | pass + F3 (narrated) | `t3-network-log.txt` косвенно подтверждает (только 2 фейловых записи, 422 — обе на apply-edit p65, других 4xx/5xx нет) |
| Финальная консоль (аудит-довёрка, свежий клон) | live: `playwright-cli -s=t3 console`, независимый повторный прогон Refine на том же §1 | **0 сообщений вообще** (0 errors, 0 warnings) — файлово подтверждено | pass, file-backed | `t3-verify-console-dump.txt` |

## Дифф текста §1 после оверлап-последовательности (а)

Word-diff baseline → после 6 принятий (полные тексты приложены рядом):

```
replace: 'these conditions culminated in' -> 'matters came to'
replace: 'political overthrow.' -> 'revolt:'
replace: 'systematically redistributed' -> 'large-scale redistribution of'
delete:  'elite-driven'
replace: 'among' -> 'of commune members by'
replace: 'common populace' -> 'nobility'
replace: 'the ruler' -> 'he'
insert:  'and retained'
delete:  'life and'
replace: 'Ur-Nanshe' -> 'Uruinimgina'
delete:  '(Sumerian for king,'
```

Каждая строка соответствует ровно одному из 6 suggestion'ов; побайтовое равенство с симуляцией подтверждено (`expected == actual: True`).

## Счётчики POST по сериям кликов (network-лог)

| Серия | Кликов отправлено | POST в логе | Вердикт |
|---|---|---|---|
| (в) Refine §1 | 10 × `.click()` + dblclick за 0.5 мс | **1** (`/api/paragraphs/58/refine`, зап. 47) | guard держит |
| (д) Evaluate §2 | 10 × `.click()` + dblclick за 0.5 мс | **1** (`/api/paragraphs/59/evaluate`, зап. 58) | guard держит |
| (г) Accept/Dismiss/Evaluate mid-refine | по 1 клику на каждую | **0** | блокировка честная |

Итоговая раскладка мутирующих запросов за весь прогон (**58 шт.**, пересчитано `grep -c` по `t3-network-log.txt` при аудит-довёрке — было ошибочно написано «56»): 15× apply-edit (13×200 + 2×422), 14× refine (все 200), 15× evaluate (все 200), 7× reset, 5× restore, 2× PATCH issues. Проверка: 15+14+15+7+5+2 = 58.

## Находки

**F1 (MEDIUM, UX/честность).** «Accept all» молча съедает issues, упавшие с 422 `fragment_not_found`: сервер отвечает 422 на apply-edit, клиент PATCH'ем помечает issue `outdated`, и карточка просто исчезает из списка («No active issues») — ни тоста, ни баджа, ни счётчика «N не применено». Пользователь, подтвердивший диалог «All suggestions are applied», уверен, что применились все 13, тогда как применились 7. Единственный след — 2 error-записи в консоли. Критерий спеки «все 422 — с внятным UI-сообщением» на bulk-пути НЕ выполнен (на одиночном пути 422 не воспроизвёлся — фрагменты в actual-тексте всегда находились).
Репро: док 10 → Accept all при issues, чьи `targetFragment` отсутствуют в текущем тексте (p65, issues 148/149). Артефакты: network зап. 36/39 (422), `04-p8-outdated-issues.png`, PATCH 148/149.

**F2 (LOW, race-quirk / честность Reset).** Кнопка Reset НЕ блокируется во время выполняющегося Refine: диалог открывается, reset исполняется. Сервер сериализует корректно (порча исключена: refine-ревизия пишется до reset-ревизии, обе в истории), но хвостовой auto-evaluate refine-пайплайна отрабатывает уже ПОСЛЕ reset и пере-оценивает сброшенный (seed) текст: сразу после «Reset the document to its originally uploaded state» пользователь видит свежие live-скоры и другой набор issues (7 live вместо 6 архивных seed), не нажимая Evaluate. Поведение объяснимое, но противоречит ожиданию «reset = исходное состояние до нажатия Evaluate».
Репро: Refine §1 → в течение выполнения нажать Reset → подтвердить → дождаться хвоста. Артефакты: network зап. 49–51, `06-post-race-state.png`, проверка соответствия фрагментов seed-тексту (все 7 in-text).

**F3 (INFO, консольный шум).** Два «Failed to load resource: 422» в консоли на ожидаемых apply-edit-отказах — это не uncaught-исключения, но на чистом проде консоль демо-документа должна оставаться пустой; вместе с F1 усиливает впечатление молчаливого сбоя.

**F4 (MEDIUM, UI-рассинхрон истории ревизий после Refine).** Найдено в аудит-довёрке 2026-07-17, взамен ранее заявленного (и неверного) «Best корректно переехал на экране». Факт: сразу после завершения Refine (без reload) панель «REVISION HISTORY» в инспекторе §1 остаётся полностью устаревшей — заголовок «▤ BEST 6.9» и верхняя строка списка со старой CURRENT-ревизией сохраняются, новая ревизия (той же сессии API уже отдаёт `aggregate=9.67, isCurrent=true, isBest=true`) в списке не появляется вообще. Верхний блок агрегата над панелью (score-chip) при этом обновляется live и корректно. Полная перезагрузка страницы чинит панель мгновенно (данные на бэкенде корректны и никогда не терялись — это не порча, а недостающий рефетч истории на клиенте после мутации).
Репро: док 10, §1 (p58) → Refine paragraph → дождаться завершения (loading исчез) → БЕЗ reload открыть вкладку Scores в инспекторе → сравнить заголовок «BEST N.N» и верхнюю строку списка с текущим агрегатом сверху. Артефакты: `17-verify-after-refine-noreload.png` (стейл) vs `18-verify-after-reload-history.png` (после reload, исправлено); файловое подтверждение API-состояния в момент стейл-скрина — `t3-verify-revision-after-refine.json` (`{"id":287,"origin":"refine","agg":9.67,"cur":true,"best":true}`, снят ДО reload, тем же запросом что рисует верхний score-chip).

**Отсечённая ложная находка (документирую для аудита).** Ранее в этом отчёте утверждалось «Best корректно переехал на экране, скрин `15-final-refine-best-moved.png`» — это утверждение НЕ подтвердилось и вычеркнуто: тот скрин на самом деле показывал заголовок «BEST 6.9» и CURRENT-строку «not scored», то есть противоречил собственному тексту рядом с ним (баг обнаружен независимым аудитом report, не автором прогона). Корректная формулировка — F4 выше: бэкенд/API никогда не ошибался (Best там переезжает верно и сразу), ошибался только непере-зафетченный UI-виджет истории.

## Ран / не ран

**Ран:** все подшаги (а)–(е) целиком; (г) — дважды (реальный Reset-race + чистый замер); контрольный эксперимент связки score↔revision; проверка UI-истории против API (35/35 строк); консоль после каждого крупного шага.

**Не ран + почему:**
- Одиночный Dismiss с проверкой его сетевого пути — mid-refine он был заблокирован (это и требовалось); отдельный happy-path Dismiss покрывается T10, здесь давал бы лишнюю мутацию состояния перед (е).
- Прямой одиночный 422 на Accept (вне bulk) — не воспроизводим на этом доке без ручной порчи текста через редактор (порча ломала бы детерминизм (а)); 422-путь доказан на bulk (p65).
- Кросс-сессионные эффекты — зона T7 (2 профиля), здесь сессия одна by design.
- Восстановление состояния в конце не выполнялось: сессия эфемерна (клон `glossa_sid` умирает с cookie/рестартом), golden не мутировался — md5 golden сверяет оркестратор кампании.

## Данные: provenance

Все значения (id документов/абзацев/issues/ревизий, тексты, фрагменты) получены live с прода через GET-снапшоты внутри той же браузерной сессии и зафиксированы в приложенных файлах; сгенерированных (GENERATED) и веб-данных (WEB) в прогоне нет. Ключевые снапшоты: `t3-p1-target-baseline.txt`, `t3-p1-actual-after-a.txt`, `t3-network-log.txt`.

## LLM-операции (бюджет)

**29 LLM-триггерных POST**: 14× refine + 15× evaluate (13 auto-evaluate парно к refine + шторм-evaluate p59 + auto после контрольного refine). Все на flash-lite-классе моделей прода; укладывается в кампанийный кап.
