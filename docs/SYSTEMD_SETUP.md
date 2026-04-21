# Systemd Setup

Актуально на 2026-04-21

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

## Полезные команды

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
