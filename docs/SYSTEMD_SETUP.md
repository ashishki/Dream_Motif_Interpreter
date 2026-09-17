# Systemd Setup

Актуально на 2026-09-17

Для постоянной работы после перезагрузки нужны три сервиса:

- `dream-motif-api.service`
- `dream-motif-telegram.service`
- `dream-motif-auto-sync.service`

Шаблоны unit-файлов лежат в:

```text
deploy/systemd/
```

## Что делают сервисы

- `dream-motif-api` — поднимает HTTP API на `127.0.0.1:8000`
- `dream-motif-telegram` — держит Telegram-бота на long polling
- `dream-motif-auto-sync` — проверяет Google Docs и запускает sync только при изменении документа

## Быстрая установка

```bash
sudo cp deploy/systemd/dream-motif-api.service /etc/systemd/system/
sudo cp deploy/systemd/dream-motif-telegram.service /etc/systemd/system/
sudo cp deploy/systemd/dream-motif-auto-sync.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now dream-motif-api.service
sudo systemctl enable --now dream-motif-telegram.service
sudo systemctl enable --now dream-motif-auto-sync.service
```

## Граница с Docker Compose

Systemd и Compose — два самостоятельных способа запустить приложение. Если эти три unit уже
обслуживают production-базу, не запускайте `docker compose up` или
`scripts/deploy_compose.sh` на том же хосте: Compose создаст собственные PostgreSQL/Redis
контейнеры и может занять уже используемые порты. Его `DMI_DATABASE_SECRET_FILE` относится
только к Compose. Systemd читает защищённый `.env` через `EnvironmentFile`.

## Полезные команды

### Безопасное обновление кода и схемы

Перед обновлением зафиксируйте чистый commit и запишите его SHA в `BUILD_SHA` защищённого `.env`.
Проверьте, что этот `.env` имеет права `0600` и содержит настоящий, не шаблонный `SECRET_KEY`.
Новая версия откажется стартовать с `change-me`, `replace-me` и другими placeholder-значениями;
смена `SECRET_KEY` сбрасывает ранее выданные cookie-сессии.

Не обновляйте схему при работающем API, Telegram-боте или auto-sync. Выполните rollout в таком
порядке:

```bash
sudo systemctl stop dream-motif-auto-sync.service \
  dream-motif-telegram.service \
  dream-motif-api.service

# Создайте custom-format pg_dump вне checkout, проверьте его через pg_restore --list
# и выполните restore drill в отдельной БД с суффиксом _restore_drill.

uv sync --locked --extra dev

# Alembic не читает systemd EnvironmentFile автоматически.
set -a; . ./.env; set +a
.venv/bin/alembic upgrade head

# Сначала API: /ready должен вернуть status=ok и текущий BUILD_SHA.
sudo systemctl start dream-motif-api.service
curl --fail http://127.0.0.1:8000/ready

sudo systemctl start dream-motif-telegram.service \
  dream-motif-auto-sync.service
```

Не запускайте Telegram и auto-sync, пока API не прошёл `/ready`. Если backup, migration или
readiness вернули ненулевой код, оставьте writers остановленными и устраните причину. Не
восстанавливайте каноническую БД без сверки внешних Telegram/Google Docs действий; restore drill
всегда выполняется только в disposable БД.

Проверить статус:

```bash
systemctl status dream-motif-api.service
systemctl status dream-motif-telegram.service
systemctl status dream-motif-auto-sync.service
```

Перезапустить:

```bash
sudo systemctl restart dream-motif-api.service
sudo systemctl restart dream-motif-telegram.service
sudo systemctl restart dream-motif-auto-sync.service
```

Смотреть логи:

```bash
journalctl -u dream-motif-api.service -n 100 --no-pager
journalctl -u dream-motif-telegram.service -n 100 --no-pager
journalctl -u dream-motif-auto-sync.service -n 100 --no-pager
```
