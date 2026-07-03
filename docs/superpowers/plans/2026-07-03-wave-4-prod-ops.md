# Wave-4 — prod-ops runbook (для владельца)

Все прод-действия вынесены сюда: они блокируются auto-mode classifier (SSH root / docker / подмена БД) и/или тратят реальные деньги. Claude их автономно НЕ выполнял. Ветка `feat/wave-4` слита в `dev-demo` после verify-pr+e2e (см. финальный отчёт).

Сервер: `root@72.56.109.228`, ключ `~/.ssh/id_ed25519_grader`. Контейнер `gse-demo`, volume `/opt/gse-demo/data:/data`, env-file `/opt/gse-demo/env`.

**Инвариант сохранности (wave-4):** прод-БД `demo.db` НЕ подменять целиком — там судейские предсказания. Деплой кода volume не трогает. Перед любым риском — `cp demo.db demo.db.bak`.

---

## 1. Деплой кода wave-4 (без подмены БД)

Сначала пересобрать фронт (мы меняли frontend):
```bash
WT=/Users/a1111/Projects/Work/worktrees/wave-4
cd $WT/frontend && npm run build      # tsc -b && vite build → frontend/dist
```
Rsync кода + бандла, пересборка образа, пересоздание контейнера (volume/БД переживают):
```bash
KEY=~/.ssh/id_ed25519_grader ; SRV=root@72.56.109.228
rsync -az --delete -e "ssh -i $KEY" --exclude '__pycache__' \
  $WT/pyproject.toml $WT/README.md $WT/Dockerfile $WT/src $WT/prompts $WT/glossary \
  $SRV:/opt/gse-demo/app/
rsync -az --delete -e "ssh -i $KEY" $WT/frontend/dist $SRV:/opt/gse-demo/app/frontend/
ssh -i $KEY $SRV "cd /opt/gse-demo/app && docker build -q -t gse-demo ."
# backup БД перед пересозданием (дёшево, страховка)
ssh -i $KEY $SRV "cp /opt/gse-demo/data/demo.db /opt/gse-demo/data/demo.db.bak"
```

## 2. Снять admin-токен (Б5) — сделать в ЭТОМ же пересоздании контейнера

Env читается только при создании контейнера, поэтому убрать переменную из env-file и пересоздать одним шагом:
```bash
# убрать строку DEMO_ADMIN_TOKEN=... из /opt/gse-demo/env
ssh -i $KEY $SRV "sed -i '/^DEMO_ADMIN_TOKEN=/d' /opt/gse-demo/env"
ssh -i $KEY $SRV "docker rm -f gse-demo && docker run -d --name gse-demo \
  --network grader-net --memory 400m --restart unless-stopped \
  -v /opt/gse-demo/data:/data --env-file /opt/gse-demo/env gse-demo"
```
После этого код backend уже не читает токен (переменная удалена вместе с кодом гейта), а фронт не показывает unlock. Настройки открыты всем — это осознанное решение (платный `POST /api/models/{name}/test` и сброс бюджета тоже открыты; защита трат — только бюджет-cap).

## 3. Отключить Cultural Adaptation на проде (Б4) — БЕЗ удаления истории

На проде критерий уже засеян со скорами; hard-delete заблокирован кодом (409) и инвариантом. Правильный путь — `enabled=0` (история скоров/замечаний остаётся, агрегат ре-нормализуется):
```bash
ssh -i $KEY $SRV "docker exec gse-demo python -c \"
import sqlite3; c=sqlite3.connect('/data/demo.db')
c.execute(\\\"UPDATE criterion SET enabled=0 WHERE id='cultural'\\\"); c.commit()
print('cultural enabled ->', c.execute(\\\"SELECT enabled FROM criterion WHERE id='cultural'\\\").fetchone())\""
ssh -i $KEY $SRV "docker restart gse-demo"
```
Проверка (публичный GET): `GET https://gse-translation.ru/api/criteria` — cultural с `enabled:false`, остальные 4 активны.

## 4. Проверка после деплоя (публичные GET, без денег)

```bash
# документы/термины/модели живы, ключи замаскированы, admin-check роут исчез
curl -s https://gse-translation.ru/api/documents | python3 -m json.tool | head
curl -s https://gse-translation.ru/api/criteria  | python3 -c "import sys,json; print([(x['id'],x['enabled']) for x in json.load(sys.stdin)])"
curl -s -o /dev/null -w "%{http_code}\n" https://gse-translation.ru/api/admin/check   # ожидаем 404 (роут удалён)
```

## 5. Отложено — решение владельца (НЕ делал)

- **Пере-сид baseline** для устранения gap 8.3↔7.2: НЕ рекомендую. Это (а) реальные деньги (~$0.5) и (б) `seed()` теперь снёс бы всю прод-БД с предсказаниями — прямой конфликт с инвариантом. Смягчения уже в коде: judge-seed (Б6, воспроизводимость впредь) + criteria_key-бейдж «другой набор критериев» (Б3). Если всё же захочешь пере-сид — только через `docker exec -e PALIMPSEST_SEED_DEMO=1 -e PALIMPSEST_SEED_FORCE=1 …` (force-guard теперь обязателен) и с явным осознанием потери текущих предсказаний.

## Rollback
```bash
ssh -i $KEY $SRV "cp /opt/gse-demo/data/demo.db.bak /opt/gse-demo/data/demo.db && docker restart gse-demo"
# образ: docker run со старым image id (предыдущий тег)
```
