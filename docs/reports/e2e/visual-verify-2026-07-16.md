# Визуальная верификация wave — прод glossa-mt.com — 2026-07-16

**Вердикт: PASS.** 6 из 7 пунктов подтверждены визуально как задеплоенные корректно; CSS-баг в поповере термина (пункт 3c, "compact spacing"), найденный при первом прогоне, устранён коммитом `5f20c3c` и подтверждён ре-чеком в конце этого документа — теперь все 7 пунктов PASS.

Данные: реальный прод-документ "World History — Selected Passages" (единственный доступный сид на проде, source of truth — сам живой прод, playbook не предполагал использования тестового манифеста для чисто визуального прогона). Никаких мутирующих действий не выполнялось (refine/evaluate/delete/save) — только просмотр, открытие/закрытие модалок и поповеров, раскрытие строк таблицы.

## План и статус выполнения

| # | Сценарий | Статус |
|---|---|---|
| 1 | Picker: ровно одна карточка документа + Blank | Выполнено |
| 2 | Upload modal: purple ✦ glyph убран | Выполнено |
| 3 | Term popover: no Note / Candidate senses / spacing / scroll | Выполнено (4 под-проверки) |
| 4 | Glossary tab: badges / trace SEARCH step / difficulty dots | Выполнено (3 под-проверки) |
| 5 | Settings → Model Registry → Add model: params placeholder | Выполнено |
| 6 | Revision history: ~6 строк, CURRENT + Best | Выполнено |
| 7 | Console: 0 ошибок | Выполнено |

## Таблица шаг → данные → артефакт → вердикт

| Шаг | Данные (provenance) | Артефакт | Вердикт |
|---|---|---|---|
| 1. Picker | прод, живой каталог документов | `shots/01-picker.png` | PASS — ровно одна карточка "World History — Selected Passages" (без "(Draft Translation)", без Mesopotamia/Qin State) + карточка Blank document |
| 2. Upload modal | клик на Blank document | `shots/02-upload-modal.png` | PASS — крупного фиолетового ✦ над "Will be translated by …" нет, сам текст на месте; модалка закрыта через Cancel, ничего не создано |
| 3a. Term popover — Note row | клик термина "Вавилония" (§1, документ World History) | `shots/03-term-popover-babylonia.png` | PASS — строки "Note" нет |
| 3b. Term popover — секция "Candidate senses" | тот же попап | `shots/03-term-popover-babylonia.png` | PASS — заголовок "Candidate senses" (не "Ambiguous senses"), выбранный QID (Q47690 Babylonia) визуально помечен галочкой ✓ |
| 3c. Term popover — компактность отступов | тот же попап + повтор на термине "Гандаша" (§1) | `shots/03-term-popover-babylonia.png`, `shots/04-term-popover-gandash-lowterm.png` | **BUG (см. ниже)** — большой пустой промежуток (~60px) между заголовком "Disambiguating context" и самим текстом контекста, воспроизведён на двух разных терминах |
| 3d. Term popover — скролл при нехватке высоты | вьюпорт принудительно сужен до 1280×550, термин "Гандаша" (§1) | `shots/05-term-popover-scroll-before.png`, `shots/06-term-popover-scroll-after.png` | PASS — `overflow-y:auto`, при `scrollTop→scrollHeight` контент реально прокручивается (шапка попапа уходит за верхнюю границу) |
| 4a. Glossary — бейджи grounding | вкладка Glossary, документ World History (91 term) | `shots/07-glossary-tab.png` | PASS — жёлтые бейджи "resolved by AI" (не "LLM · LLM"), зелёный "label match" и серый "no candidates" не изменились |
| 4b. Glossary — трейс SEARCH-шага | раскрыта строка "Лагаше" (resolved by AI) и "Уруинимгину" (label match) | `shots/08-glossary-trace-expanded.png`, `shots/09-glossary-trace-labelmatch.png` | PASS с оговоркой — оба раскрытых трейса (LLM-путь и deterministic-путь) рендерятся корректно, `kind`+`query` отображаются, `document.body.innerText` не содержит "undefined". **Оговорка**: не удалось предметно проверить именно "старый" трейс, созданный ДО появления поля strategy — единственный доступный на проде документ, похоже, переиндексирован после деплоя (все 91 терм имеют новый формат трейса). Ниже не покрыто. |
| 4c. Glossary — три цвета difficulty dots | та же вкладка | `shots/07-glossary-tab.png` | PASS — зелёный/жёлтый/красный точки видны в таблице |
| 5. Model Registry → Add model | Settings → раздел "1. Model Registry" → "+ Add model" | `shots/10-add-model-modal.png` | PASS — плейсхолдер PARAMS (JSON) = `{"max_tokens": 20000}`; закрыто через Cancel без сохранения |
| 6. Revision history §4 | Document → выбран параграф §4 (клик по score-chip) → вкладка Scores | `shots/12-para4-selected.png`, `shots/14-para4-scores-tab.png` | PASS — 6 строк вместо старых ~10: CURRENT (11h, not scored) + 3× not scored (11h/13h/13h/17h — фактически 4 not-scored) + Best 6.4 (5 дней назад), маркеры CURRENT и Best оба на месте |
| 7. Console errors | весь прогон | вывод `playwright-cli console` | PASS — Total messages: 1 (Errors: 0, Warnings: 0); единственное сообщение — безобидный browser-native verbose про password-field autocomplete |

## Баг: пустой промежуток в поповере термина перед "Disambiguating context"

**Серьёзность: LOW-MEDIUM (визуальный дефект, не блокирует функциональность).**

Задача явно просила проверить "compact spacing (no big empty gaps before 'Disambiguating context')" — эта регрессия НЕ устранена, она просто сдвинулась: раньше промежуток предположительно был перед заголовком, сейчас он между заголовком и самим текстом контекста.

Репро:
1. Открыть документ "World History — Selected Passages".
2. Кликнуть любой сгруппированный термин с непустым `context` (например "Вавилония" в §1 или "Гандаша" в §1).
3. В попапе после секции "Candidate senses" виден заголовок "Disambiguating context", а затем ~60px пустого пространства, и только потом сам текст контекста серым мелким шрифтом.

Корневая причина (по коду, не по догадке):
- `frontend/src/demo/variant-a/TermPopover.tsx:159-160` — строка контекста рендерится как `<div className="va-term-popover-row" style={{ flexDirection: 'column', gap: 3 }}>` с `<span className="va-term-popover-label">Disambiguating context</span>` внутри.
- `frontend/src/demo/variant-a/variant-a.css:1095-1098` — класс `.va-term-popover-label` задаёт `flex: 0 0 80px`, что задумано как ФИКСИРОВАННАЯ ШИРИНА колонки-подписи в обычных row-строках (`display:flex` без `flex-direction` = row).
- Но именно в этой строке контейнер переключён на `flex-direction: column` инлайн-стилем — и в column-контексте `flex-basis` применяется к главной оси, то есть к ВЫСОТЕ. В итоге `<span>"Disambiguating context"</span>` вынужден иметь высоту 80px вместо ~18px, которые нужны для одной строки текста.
- Подтверждено через `getComputedStyle`: `height: "80px"` при `line-height: "18px"` и отсутствии padding/margin.

Воспроизведено дважды на разных терминах (Вавилония, Гандаша) — не флюк.

Рекомендация для фикса: в `TermPopover.tsx:160` заменить класс `va-term-popover-label` на отдельный модификатор без `flex-basis` (например `va-term-popover-label--block`) для этой конкретной колоночной строки, либо обнулить `flex-basis` инлайн-стилем (`style={{ flex: '0 0 auto' }}`) на самом span.

**Ре-чек 2026-07-16 (после деплоя коммита `5f20c3c`): PASS.** `.va-term-popover-label` теперь `flex: 0 0 auto; min-width: 80px` — на том же термине "Вавилония" заголовок "Disambiguating context" сидит прямо над своим текстом (computed height лейбла упал с 80px до 18px), пустой промежуток исчез; row-режим лейблов (Difficulty / Pair accuracy / Source lemma / Wikidata) по-прежнему держит колонку ~80px. Скриншот: `shots/visual-verify/15-popover-gap-fixed.png`.

## Прочие наблюдения / SUSPECTED

- Пункт 4b покрыт не полностью: тест-план требовал проверки именно legacy-трейса (созданного до появления поля `strategy`), но единственный доступный прод-документ, судя по всему, был переиндексирован целиком после сегодняшнего деплоя — все проверенные трейсы (26 deterministic + 43 LLM) в новом формате. Крашей/пустот не найдено ни в одном из проверенных, но это не строго то же самое, что проверка legacy-формата. Если на проде существуют другие документы со старыми трейсами — не обнаружены через picker (там только один документ + Blank).
- Ряд "REVISION HISTORY" содержит 4 строки "not scored" подряд помимо CURRENT и Best — не баг per se (так и должно быть после нескольких неоценённых Refine-проходов), но стоит перепроверить с владельцем, ожидается ли строго "~6" включая эти промежуточные not-scored записи, или они должны схлопываться.

## Что не тестировалось и почему

- Регрессионный проход по остальным разделам Settings (Translator/Judges/Grounding/Refiner) — вне заявленного скоупа визуальной верификации (только Model Registry затронут списком проверок).
- Полный e2e-цикл refine/evaluate/accept — намеренно исключён протоколом задачи (read-only run, "не модифицировать данные").
- Мобильная/узкая раскладка — не входила в скоуп; вьюпорт временно сужался только для целевой проверки скролла поповера (п. 3d), затем восстановлен.

## Провенанс данных

Все использованные значения — из живого прод-состояния (`WEB` в смысле "с самого прод-сайта", не из manifest-файла, так как задача read-only визуальная и явно не требовала сценариев с вводом новых данных). Ничего не сгенерировано, ничего не сохранено.
