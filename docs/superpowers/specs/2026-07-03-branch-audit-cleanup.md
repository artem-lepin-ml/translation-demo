# Аудит и чистка веток — 2026-07-03

Up-link: [CLAUDE.md § Branches & worktrees](../../../CLAUDE.md#branches--worktrees) · [docs/README.md](../../README.md)

Спека по итогам иерархического аудита (5 read-only агентов: reorg-спека, overnight-цели, свип specs/plans, git-форензика зеркала, known issues) + `/verify-spec` (4 аспекта: цель, документация, операции, скоуп; 3 HIGH и 8 MEDIUM закрыты переработкой). Статус: **на решение владельца** — удаления не выполняются до его явного подтверждения.

## Цель и non-goals

**Цель (проверяемое состояние):** локальный репозиторий владельца и GitLab-origin приведены к документированной топологии — живы только `main`, `dev-demo`, `old-gse-translating` и активные `feat/*`; всё удалённое сохранено верифицированными бандлами; решение по `feat/glossary-overnight` исполнено; worktree-раскладка соответствует [CLAUDE.md § Branches & worktrees](../../../CLAUDE.md#branches--worktrees).

**Non-goals:** не трогаем содержимое веток и код; не выполняем операций на GitHub-зеркале (кроме обычной PR-гигиены `claude/*`); не редактируем исторические спеки/цели, упоминающие старые ветки (прецедент: [plans/2026-07-02-audit-fixes.md](../plans/2026-07-02-audit-fixes.md) оставляет архивные упоминания как статический текст); не переносим heavy-данные из GitLab.

## Главное

1. **GitHub-зеркало уже чистое.** Одна долгоживущая ветка `dev-demo` (aec95b7, 3 коммита), ноль PR на момент аудита, ноль тегов. Транзитные `claude/*` ветки облачных сессий (включая ветку этой спеки) — обычная PR-гигиена: удалять после мерджа/закрытия PR.
2. **«Куча веток» живёт локально на Mac (`/Users/a1111/Projects/Work/…`) и в GitLab-origin.** Из облачной сессии они не видны — вердикты собраны из доков репо + сверки содержимого зеркала; каждый требует локальной верификации (§ Процедура, шаг 1).
3. **Импорт на GitHub сделан 2026-07-03 11:57 MSK** — после всех волн 2026-07-02 и после мерджа wave-4. Содержимое почти всех feat-веток подтверждено в дереве зеркала ⇒ локально это смерженный балласт: бандл + удаление ссылки.
4. **Единственная ветка с уникальной несмерженной ценностью — `feat/glossary-overnight`** (глоссарий на 869 записей; в `dev-demo` — заглушка на 1 запись). Рекомендация: импорт артефакта (§ Merge-план, опция b).

## Инвентарь и вердикты

Evidence: `tree` = содержимое найдено в снапшоте зеркала (dev-demo HEAD), `docs` = статус заявлен в спеках/планах. Выборочная перепроверка tree-вердиктов при `/verify-spec` расхождений не нашла.

### Keepers — не трогать

Роли этих веток описаны в [CLAUDE.md § Branches & worktrees](../../../CLAUDE.md#branches--worktrees) (single source of truth, здесь не дублируем): `main`, `dev-demo`, `old-gse-translating`.

### Смерженные feat/* — бандл + удалить ссылку (после верификации и подтверждения владельца)

| Ветка | Фича | Evidence |
|---|---|---|
| `feat/model-registry` | реестр моделей | tree (`/api/models` работает) + docs |
| `feat/terminology`, `feat/term-grounding`, `feat/term-pairing`, `feat/terminology-consolidated` | терминология: extract→ground→pair | tree (`src/palimpsest/terminology/` с `grounding/`, `pairing/`) + docs (консолидация) |
| `feat/terminology-extract` | live-NER extractor | tree (`extract.py`) + docs |
| `feat/upload-polish` (+ pair-upload) | загрузка пары | tree (`upload/UploadModal.tsx`) + docs «merged» |
| `feat/settings-rework` | редизайн Settings | tree (`SettingsTab.tsx`, mockup в docs/) + docs |
| `feat/inspector-fixes` | фиксы Inspector | tree (`InspectorPanel.tsx`) + docs |
| `feat/pair-highlight` | подсветка пар | tree (видна в смоук-скриншоте) + docs |
| `feat/suggestion-guard` | guard принятия правок | docs (spec closed) |
| `feat/seed-refresh` | новый сид | tree (сид «Mesopotamia pilot», 15 абзацев) + docs |
| `feat/audit-fixes` | фиксы аудита сайта | docs |
| `feat/reading-pane` | reading pane redesign | tree (маркеры в `VariantA.tsx`/CSS) + docs |
| `feat/explicit-reeval` | явный re-eval UI | tree (кнопка «Evaluate ↻» на скриншоте) + docs |
| `feat/wave-4` | 5 owner-фиксов + prediction preservation | tree (`superseded/archived` в `webapp/app.py`) + docs «merged 2026-07-03» |

### Легаси реорга 2026-06-30 — бандл + удалить ссылку (после подтверждения владельца)

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

Контекст: инвариант — `glossary/main.json` это single source of truth для RU→EN терминологии; вкладка Glossary в демо сейчас работает поверх заглушки.

Опции:

- **(a) Полный merge ветки.** Тянет в `dev-demo` всё дерево старой ветки (она росла от `feat/project`, не от `dev-demo`) — конфликтная история, мусор в дереве. Не рекомендую.
- **(b) Импорт артефакта (рекомендация, S).** Пока ветка ещё жива (импорт делается ДО её бандла и удаления):

  ```bash
  git worktree add ../worktrees/glossary-import -b feat/glossary-import dev-demo
  cd ../worktrees/glossary-import
  git show feat/glossary-overnight:glossary/main.json > glossary/main.json
  # опционально, если лёгкий и совместимый: так же забрать build-пайплайн из scripts/
  ```

  Если ссылка на ветку уже удалена и остался только бандл:
  ```bash
  git fetch ../worktree-backups/feat-glossary-overnight-<date>.bundle feat/glossary-overnight:refs/tmp/glossary-src
  git show refs/tmp/glossary-src:glossary/main.json > glossary/main.json
  ```

  Дальше: прогнать демо на новом глоссарии (Glossary tab, terminology pairing), коммит `feat(glossary): import real 869-entry glossary from feat/glossary-overnight`, PR → `dev-demo`. После мерджа `feat/glossary-overnight` формально закрыта: бандл + удаление ссылки.
- **(c) Формальный retire.** Если глоссарий в демо не нужен — бандл, удалить ссылку, снять «pending owner decision» в CLAUDE.md.

## Процедура чистки (локально, на Mac)

⚠️ **Гейт:** шаги 1–2 — техническая пред-проверка. Бандл и удаление (шаги 3–4) запускаются только после того, как владелец явно подтвердил итоговый список веток. «Верифицировано как смерженное» ≠ «владелец сказал удалить».

Порядок жёсткий: **verify → worktree remove → bundle → delete**; несбандленное не удаляется (инвариант «never hard-deleted»).

```bash
cd /Users/a1111/Projects/Work/<primary-checkout>
git remote -v                            # определить фактическое имя GitLab-remote (ниже — <gitlab-remote>)
git fetch --all --prune

# 1. Верификация «смерженности»: каждая ветка из таблиц выше
git branch --merged dev-demo             # попавшие сюда — безопасно удалять
git cherry -v dev-demo <branch>          # для не попавших: '-' = патч уже в dev-demo

# 2. Хвост после импорта на GitHub: что не допушено в зеркало
git fetch origin && git log origin/dev-demo..dev-demo --oneline   # непусто → git push origin dev-demo

# 3-4. Для КАЖДОЙ подтверждённой ветки, одним циклом (worktree убирается ДО удаления ветки,
#      иначе git branch -D откажет: "used by worktree"):
git -C ../worktrees/<topic> status       # worktree грязный → разобраться; крайний случай: remove --force
git worktree remove ../worktrees/<topic> && git worktree prune
git bundle create ../worktree-backups/<branch-name>-$(date +%Y%m%d).bundle <branch>
git bundle verify ../worktree-backups/<branch-name>-<date>.bundle
git branch -D <branch>
git push <gitlab-remote> --delete <branch>   # если ветка была запушена в GitLab
```

Целевое состояние worktree после чистки: primary checkout = `old-gse-translating`, выделенный worktree `dev-demo`, каталог `../worktrees/` пуст (создаётся ad-hoc под новые `feat/<topic>`), `../worktree-backups/` — бандлы всего удалённого.

## Doc-parity

- CLAUDE.md § Branches & worktrees: после исполнения решения (b) или (c) убрать строку «Bundled, pending an owner decision: feat/glossary-overnight» — в том же коммите, что исполняет решение.
- ~~Фиксировать в CLAUDE.md список веток зеркала~~ — отклонено на `/verify-spec`: перечень запушенных веток — дрейфующий факт, CLAUDE.md такие не хранит; SSOT — сам `git ls-remote`.
- Отдельный S-пункт вне скоупа чистки (на отмашку владельца, можно отдельным коммитом): [README.md](../../../README.md) «Renders 16 seed paragraphs» → **15**. Направление однозначное: 15 — канон после seed-refresh 2026-07-02 ([docs/testing/e2e-data.md](../../testing/e2e-data.md), [docs/subsystems/webapp.md](../../subsystems/webapp.md) уже говорят 15); «чинить сид назад» нельзя.

## Критерии успеха

1. Локально `git branch -a` показывает только: `main`, `dev-demo`, `old-gse-translating` (+ живые `feat/*` активной работы).
2. Каждая удалённая ветка имеет верифицированный `.bundle` в `../worktree-backups/`.
3. Решение по `feat/glossary-overnight` исполнено: либо PR `feat/glossary-import` смержен в `dev-demo`, либо retire зафиксирован.
4. `git worktree list` — только primary + `dev-demo`.
5. `git log origin/dev-demo..dev-demo` пуст (зеркало несёт полный хвост коммитов).
6. Doc-parity исполнен: строка «pending owner decision» снята из CLAUDE.md в коммите решения; README-фикс 16→15 либо сделан, либо явно отложен владельцем.

## Ограничения аудита (честно)

- **Не запускалось:** локальный/GitLab-репозиторий недоступен из облачной сессии — фактические SHA, ahead/behind и точный список живых веток не проверялись. Вердикты = доки + сверка дерева зеркала; шаг 1 процедуры обязателен перед любым удалением.
- Ветки, не упомянутые в доках (если есть безымянные локальные), аудитом не покрыты — их покажет `git branch -a` на шаге 1.
- Размеры: чистка — S (механика по списку), merge-план (b) — S, доводка доков — S.
