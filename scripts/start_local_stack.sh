#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.run"
mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"

set -a
source "$ROOT_DIR/.env"
set +a

if command -v docker >/dev/null 2>&1; then
  docker compose up -d postgres redis
else
  echo "docker not found, assuming postgres and redis are already running"
fi

.venv/bin/alembic upgrade head

start_if_not_running() {
  local name="$1"
  local cmd="$2"
  local pid_file="$LOG_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"

  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "$name already running (pid=$pid)"
      return
    fi
    rm -f "$pid_file"
  fi

  nohup bash -lc "$cmd" >"$log_file" 2>&1 &
  echo $! >"$pid_file"
  echo "started $name (pid=$(cat "$pid_file"))"
}

start_if_not_running "api" ".venv/bin/python -m app.main"
start_if_not_running "telegram" ".venv/bin/python -m app.telegram"
start_if_not_running "auto_sync" ".venv/bin/python -m app.auto_sync"

echo "logs: $LOG_DIR"
