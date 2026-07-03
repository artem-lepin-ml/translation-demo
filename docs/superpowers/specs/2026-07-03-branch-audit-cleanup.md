# Аудит и чистка веток — 2026-07-03

Спека по итогам иерархического аудита (5 read-only агентов: reorg-спека, overnight-цели, свип specs/plans, git-форензика зеркала, known issues). Статус: draft → на решение владельца.

## Главное

1. **GitHub-зеркало (`artem-lepin-ml/translation-demo`) уже чистое.** Ровно одна ветка `dev-demo` (aec95b7, 3 коммита), ноль PR, ноль тегов. Чистить здесь нечего.
2. **«Куча веток» живёт локально на Mac (`/Users/a1111/Projects/Work/…`) и в GitLab-origin.** Из облачной сессии они не видны — вердикты ниже собраны из доков репо + сверки содержимого зеркала, и каждый требует локальной верификации одной командой (см. § Процедура).
3. **Импорт на GitHub сделан 2026-07-03 11:57 MSK** — уже после всех волн 2026-07-02 и после мерджа wave-4. Содержимое почти всех feat-веток подтверждено в дереве зеркала ⇒ локально это смерженный балласт: бандл + удаление ссылки.
4. **Единственная ветка с уникальной несмерженной ценностью — `feat/glossary-overnight`** (реальный глоссарий на 869 записей; в `dev-demo` сейчас заглушка на 1 запись). Рекомендация: merge-forward артефакта.

## Инвентарь и вердикты

Evidence-колонка: `tree` = содержимое найдено в снапшоте зеркала (dev-demo HEAD), `docs` = статус заявлен в спеках/планах.

### Keepers — не трогать

| Ветка | Роль | Действие |
|---|---|---|
| `dev-demo` | активная интеграционная линия | keep |
| `main` | стабильная база | keep |
| `old-gse-translating` | архив исследовательского пайплайна (бывш. `artem`) | keep (reference) |

### Смерженные feat/* — бандл + удалить ссылку (после верификации)

| Ветка | Фича | Evidence |
|---|---|---|
| `feat/model-registry` | реестр моделей | tree (`/api/models` работает) + docs |
| `feat/terminology`, `feat/term-grounding`, `feat/term-pairing`, `feat/terminology-consolidated` | терминология: extract→ground→pair | tree (`src/palimpsest/terminology/` с `grounding/`, `pairing/`) + docs (консолидация) |
| `feat/terminology-extract` | live-NER extractor | tree (`extract.py`) + docs |
| `feat/upload-polish` (+ pair-upload) | загрузка пары | tree (`upload/UploadModal.tsx`) + docs «merged» |
| `feat/settings-rework` | редизайн Settings | tree (`SettingsTab.tsx`, mockup в docs/) + docs |
| `feat/inspector-fixes` | фиксы Inspector | tree (`InspectorPanel.tsx`) + docs |
| `feat/pair-highlight` | подсветка пар | tree (виден в смоук-скриншоте) + docs |
| `feat/suggestion-guard` | guard принятия правок | docs (spec closed) |
| `feat/seed-refresh` | новый сид | tree (сид «Mesopotamia pilot», 15 абзацев) + docs |
| `feat/audit-fixes` | фиксы аудита сайта | docs |
| `feat/reading-pane` | reading pane redesign | tree (маркеры в `VariantA.tsx`/CSS) + docs |
| `feat/explicit-reeval` | явный re-eval UI | tree (кнопка «Evaluate ↻» на скриншоте) + docs |
| `feat/wave-4` | 5 owner-фиксов + prediction preservation | tree (`superseded/archived` в `webapp/app.py`) + docs «merged 2026-07-03» |

### Легаси реорга 2026-06-30 — бандл + удалить ссылку

| Ветка | Что это | Действие |
|---|---|---|
| `artem` | старый пайплайн; уже переименован/сохранён как `old-gse-translating` | если ссылка ещё жива — бандл + удалить |
| `artem-translation-old` | архивный указатель на старый код | бандл + удалить ссылку (архив остаётся бандлом) |
| `feat/demo-skeleton` | скелет демо + первый TipTap UI | поглощён линией `artem-demo`→`dev-demo`; бандл + удалить |
| `artem-demo` | предшественник `dev-demo` | бандл + удалить |
| `feat/demo` | база overnight-веток, предшественник `dev-demo` | бандл + удалить |
| `feat/project` | база glossary-работ | бандл + удалить |

### Особый случай — решение владельца

| Ветка | Ценность | Опции |
|---|---|---|
| `feat/glossary-overnight` | **глоссарий на 869 записей + build-пайплайн**; в `dev-demo` HEAD `glossary/main.json` — заглушка на 1 запись | см. § Merge-план |

## Merge-план: glossary-overnight → dev-demo

Контекст: инвариант — `glossary/main.json` является single source of truth для RU→EN терминологии; вкладка Glossary в демо сейчас работает поверх заглушки.

Опции:

- **(a) Полный merge ветки.** Тянет в `dev-demo` всё дерево старой ветки (ветка росла от `feat/project`, не от `dev-demo`) — конфликтная история, мусор в дереве. Не рекомендую.
- **(b) Импорт артефакта (рекомендация, S).** Новая ветка `feat/glossary-import` от `dev-demo`; скопировать из бандла/ветки только `glossary/main.json` (869 записей) и, если лёгкий и совместимый, build-пайплайн (`scripts/`-часть); прогнать демо на новом глоссарии (Glossary tab, terminology pairing); Conventional Commit `feat(glossary): import real 869-entry glossary from feat/glossary-overnight`; PR → `dev-demo`. После мерджа `feat/glossary-overnight` формально закрыта: бандл + удаление ссылки.
- **(c) Формальный retire.** Если глоссарий владельцу в демо не нужен — бандл уже есть, удалить ссылку, зафиксировать retire в CLAUDE.md (снять «pending owner decision»).

## Процедура чистки (локально, на Mac)

Порядок жёсткий: **verify → bundle → delete**; несбандленное не удаляется (инвариант «never hard-deleted»).

```bash
cd /Users/a1111/Projects/Work/<primary-checkout>
git fetch --all --prune

# 1. Верификация «смерженности»: каждая ветка из таблицы выше
git branch --merged dev-demo            # попавшие сюда — безопасно удалять
git cherry -v dev-demo <branch>         # для не попавших: '-' = патч уже в dev-demo

# 2. Хвост после импорта на GitHub: всё, что закоммичено в dev-demo после
#    2026-07-03 11:57 MSK, должно быть допушено в зеркало
git log --oneline --since="2026-07-03 11:57" dev-demo

# 3. Бандл (по одной на ветку, в существующий каталог бэкапов)
git bundle create ../worktree-backups/<branch-name>-$(date +%Y%m%d).bundle <branch>
git bundle verify ../worktree-backups/<branch-name>-*.bundle

# 4. Удаление ссылок
git branch -D <branch>                  # локальная
git push gitlab-origin --delete <branch>   # если ветка была запушена в GitLab

# 5. Worktrees: снести каталоги завершённых веток
git worktree list
git worktree remove ../worktrees/<topic>   # для каждой смерженной
git worktree prune
```

Целевое состояние worktree после чистки: primary checkout = `old-gse-translating`, выделенный worktree `dev-demo`, каталог `../worktrees/` пуст (создаётся ad-hoc под новые `feat/<topic>`), `../worktree-backups/` — бандлы всего удалённого.

## Doc-parity (в том же PR, что и чистка)

- CLAUDE.md § Branches & worktrees: убрать строку «Bundled, pending an owner decision: feat/glossary-overnight» после исполнения решения (b) или (c).
- CLAUDE.md: зафиксировать одной строкой, что GitHub-зеркало несёт только `dev-demo` (сейчас топология описывает `main`+`dev-demo`+`feat/*`, а в зеркале одна ветка — расхождение доков с фактом).
- README.md: «Renders 16 seed paragraphs» → фактически сид даёт 15 (`seeded 15 paragraphs`); поправить цифру или сид.

## Критерии успеха

1. Локально `git branch -a` показывает только: `main`, `dev-demo`, `old-gse-translating` (+ живые `feat/*`, если есть активная работа).
2. Каждая удалённая ветка имеет верифицированный `.bundle` в `../worktree-backups/`.
3. Решение по `feat/glossary-overnight` исполнено: либо PR с глоссарием смержен в `dev-demo`, либо retire зафиксирован в CLAUDE.md.
4. `git worktree list` — только primary + `dev-demo`.
5. Зеркало на GitHub содержит `dev-demo` с полным хвостом коммитов (ничего локального после 11:57 не потеряно).

## Ограничения аудита (честно)

- **Не запускалось:** локальный/GitLab-репозиторий недоступен из облачной сессии — фактические SHA, ahead/behind и точный список живых веток не проверялись. Вердикты = доки + сверка дерева зеркала; шаг 1 процедуры (verify) обязателен перед любым удалением.
- Ветки, не упомянутые в доках (если есть безымянные локальные), аудитом не покрыты — их покажет `git branch -a` на шаге 1.
- Размеры: чистка — S (механика по списку), merge-план (b) — S, доводка доков — S.
