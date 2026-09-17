#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/deploy_compose.sh --backup-dir DIR [--with-auto-sync] [--google-service-account]

Safely rolls out the current commit with Docker Compose:
  1. stop every application writer
  2. start and wait for PostgreSQL/Redis
  3. create and verify a pre-migration PostgreSQL backup
  4. build the application image and run migrations to completion
  5. start API, verify /ready for the exact revision, then start Telegram bot and optionally auto-sync

Options:
  --backup-dir DIR          Absolute host directory for pre-migration pg_dump archives.
  --with-auto-sync          Start the optional auto-sync service after migration.
  --google-service-account  Include docker-compose.google-service-account.yml.
  -h, --help                Show this help.
EOF
}

with_auto_sync=false
with_google_service_account=false
backup_dir="${DEPLOY_BACKUP_DIR:-}"

while (($#)); do
  case "$1" in
    --backup-dir)
      if (($# < 2)); then
        echo "--backup-dir requires an absolute directory path." >&2
        exit 2
      fi
      backup_dir="$2"
      shift
      ;;
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

if [[ -z "${backup_dir}" ]]; then
  echo "Missing --backup-dir or DEPLOY_BACKUP_DIR; refusing to migrate without a verified pre-migration backup." >&2
  exit 1
fi
if [[ "${backup_dir}" != /* ]]; then
  echo "Backup directory must be an absolute host path." >&2
  exit 1
fi
backup_dir="${backup_dir%/}"
case "${backup_dir}/" in
  "${repo_root}/"*)
    echo "Backup directory must be outside the repository checkout." >&2
    exit 1
    ;;
esac
mkdir -p -- "${backup_dir}"
chmod go-rwx -- "${backup_dir}"

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

previous_api_container_id="$("${compose[@]}" ps -q api 2>/dev/null || true)"
previous_api_image_id=""
previous_api_build_sha=""
if [[ -n "${previous_api_container_id}" ]]; then
  previous_api_image_id="$(docker inspect --format '{{.Image}}' "${previous_api_container_id}" 2>/dev/null || true)"
  if [[ -n "${previous_api_image_id}" ]]; then
    previous_api_build_sha="$(docker image inspect "${previous_api_image_id}" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' 2>/dev/null || true)"
  fi
fi

echo "Stopping API, Telegram bot, and auto-sync before schema migration..."
"${compose[@]}" --profile autosync stop --timeout 50 api telegram-bot auto-sync
rollout_phase=quiesced

echo "Starting infrastructure and waiting for health checks..."
"${compose[@]}" up -d --wait postgres redis

backup_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${backup_dir}/dream_motif_${backup_timestamp}_${BUILD_SHA}.dump"
backup_tmp="${backup_file}.tmp"
backup_manifest="${backup_file}.manifest"
if [[ -e "${backup_file}" || -e "${backup_manifest}" ]]; then
  echo "Refusing to overwrite an existing backup archive or manifest: ${backup_file}" >&2
  exit 1
fi
rm -f -- "${backup_tmp}"

echo "Creating verified pre-migration PostgreSQL backup..."
umask 077
"${compose[@]}" exec -T postgres pg_dump -U postgres -d dream_motif --format=custom >"${backup_tmp}"
chmod 600 -- "${backup_tmp}"
if [[ ! -s "${backup_tmp}" ]]; then
  echo "Pre-migration PostgreSQL backup is empty." >&2
  exit 1
fi
"${compose[@]}" exec -T postgres pg_restore --list <"${backup_tmp}" >/dev/null
backup_sha256="$(sha256sum "${backup_tmp}")"
backup_sha256="${backup_sha256%% *}"
alembic_revision="$("${compose[@]}" exec -T postgres psql -U postgres -d dream_motif -Atc 'select version_num from alembic_version limit 1;' 2>/dev/null || true)"
if [[ -z "${alembic_revision}" ]]; then
  alembic_revision="none"
fi
mv -- "${backup_tmp}" "${backup_file}"
cat >"${backup_manifest}" <<EOF
created_at_utc=${backup_timestamp}
build_sha=${BUILD_SHA}
database_name=dream_motif
backup_file=${backup_file}
backup_sha256=${backup_sha256}
alembic_revision=${alembic_revision}
previous_api_container_id=${previous_api_container_id}
previous_api_image_id=${previous_api_image_id}
previous_api_build_sha=${previous_api_build_sha}
EOF
chmod 600 -- "${backup_manifest}"
rollout_phase=backup_created
echo "Pre-migration backup verified: ${backup_file}"

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
