#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/deploy_compose.sh [--with-auto-sync] [--google-service-account]

Safely rolls out the current commit with Docker Compose:
  1. stop every application writer
  2. start and wait for PostgreSQL/Redis
  3. build the application image and run migrations to completion
  4. start API, verify /ready for the exact revision, then start Telegram bot and optionally auto-sync

Options:
  --with-auto-sync          Start the optional auto-sync service after migration.
  --google-service-account  Include docker-compose.google-service-account.yml.
  -h, --help                Show this help.
EOF
}

with_auto_sync=false
with_google_service_account=false

while (($#)); do
  case "$1" in
    --with-auto-sync)
      with_auto_sync=true
      ;;
    --google-service-account)
      with_google_service_account=true
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
cd "${repo_root}"

if [[ ! -f .env ]]; then
  echo "Missing ${repo_root}/.env; copy .env.example and set its secrets first." >&2
  exit 1
fi

head_sha="$(git rev-parse --verify HEAD)"
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to deploy a dirty worktree; commit or remove repository changes first." >&2
  exit 1
fi
if [[ -z "${BUILD_SHA:-}" ]]; then
  BUILD_SHA="${head_sha}"
fi
if [[ -z "${BUILD_SHA}" || "${BUILD_SHA}" == "unknown" ]]; then
  echo "BUILD_SHA must identify the exact deployed commit and cannot be 'unknown'." >&2
  exit 1
fi
if [[ "${BUILD_SHA}" != "${head_sha}" ]]; then
  echo "BUILD_SHA must equal the checked-out HEAD (${head_sha})." >&2
  exit 1
fi
export BUILD_SHA

compose_files=(-f docker-compose.yml)
if [[ "${with_google_service_account}" == true ]]; then
  compose_files+=(-f docker-compose.google-service-account.yml)
fi
compose=(docker compose "${compose_files[@]}")
rollout_phase=before_quiesce

on_error() {
  exit_code=$?
  if [[ "${rollout_phase}" == before_quiesce ]]; then
    echo "Rollout failed before quiescing application writers; inspect the error before retrying." >&2
  else
    echo "Rollout failed while application writers are quiesced or partially started; stopping new application writers." >&2
    "${compose[@]}" --profile autosync stop --timeout 50 api telegram-bot auto-sync >/dev/null 2>&1 || true
  fi
  exit "${exit_code}"
}
trap on_error ERR

"${compose[@]}" --profile autosync config --quiet

echo "Stopping API, Telegram bot, and auto-sync before schema migration..."
"${compose[@]}" --profile autosync stop --timeout 50 api telegram-bot auto-sync
rollout_phase=quiesced

echo "Starting infrastructure and waiting for health checks..."
"${compose[@]}" up -d --wait postgres redis

build_services=(migrate api telegram-bot)
if [[ "${with_auto_sync}" == true ]]; then
  build_services+=(auto-sync)
fi
echo "Building application image for ${BUILD_SHA}..."
"${compose[@]}" --profile autosync build "${build_services[@]}"

echo "Applying Alembic migrations while application writers are stopped..."
"${compose[@]}" run --rm --no-deps migrate

echo "Starting API from the migrated revision..."
rollout_phase=starting_api
"${compose[@]}" up -d --no-deps --no-build api

echo "Waiting for the API readiness check before restarting background writers..."
for attempt in {1..30}; do
  if "${compose[@]}" exec -T api python -c \
    'import json, os, urllib.request; payload=json.load(urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3)); assert payload["build_sha"] == os.environ["BUILD_SHA"]; assert payload["status"] == "ok"' \
    >/dev/null 2>&1; then
    echo "Starting Telegram bot and optional auto-sync after API readiness..."
    rollout_phase=starting_writers
    "${compose[@]}" up -d --no-deps --no-build telegram-bot
    if [[ "${with_auto_sync}" == true ]]; then
      "${compose[@]}" --profile autosync up -d --no-deps --no-build auto-sync
    fi
    trap - ERR
    "${compose[@]}" --profile autosync ps
    echo "Rollout complete: ${BUILD_SHA}"
    exit 0
  fi
  if ((attempt < 30)); then
    sleep 2
  fi
done

echo "API did not report ready revision ${BUILD_SHA}." >&2
false
