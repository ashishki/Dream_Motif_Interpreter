#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.run"

stop_if_running() {
  local name="$1"
  local pid_file="$LOG_DIR/$name.pid"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name not running"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "stopped $name (pid=$pid)"
  else
    echo "$name already stopped"
  fi
  rm -f "$pid_file"
}

stop_if_running "auto_sync"
stop_if_running "telegram"
stop_if_running "api"
