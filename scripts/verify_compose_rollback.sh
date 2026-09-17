#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/verify_compose_rollback.sh --manifest FILE --restore-drill-db NAME [--allow-missing-previous-image]

Verifies a Compose deployment backup without restoring production:
  1. read the deploy manifest without sourcing it
  2. verify backup file permissions, checksum and pg_restore listing
  3. verify the recorded previous API image and OCI revision label when present
  4. restore the archive into a disposable *_restore_drill database
  5. drop the disposable database before exit

Options:
  --manifest FILE                  Manifest emitted by scripts/deploy_compose.sh.
  --restore-drill-db NAME          Disposable database name; must end with _restore_drill.
  --allow-missing-previous-image   Permit first-launch manifests without a previous API image.
  -h, --help                       Show this help.
EOF
}

manifest_file=""
restore_drill_db=""
allow_missing_previous_image=false

while (($#)); do
  case "$1" in
    --manifest)
      if (($# < 2)); then
        echo "--manifest requires a file path." >&2
        exit 2
      fi
      manifest_file="$2"
      shift
      ;;
    --restore-drill-db)
      if (($# < 2)); then
        echo "--restore-drill-db requires a disposable database name." >&2
        exit 2
      fi
      restore_drill_db="$2"
      shift
      ;;
    --allow-missing-previous-image)
      allow_missing_previous_image=true
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

if [[ -z "${manifest_file}" || -z "${restore_drill_db}" ]]; then
  usage >&2
  exit 2
fi
if [[ ! -f "${manifest_file}" || -L "${manifest_file}" ]]; then
  echo "Manifest must be a regular file: ${manifest_file}" >&2
  exit 1
fi
if [[ ! "${restore_drill_db}" =~ ^[A-Za-z_][A-Za-z0-9_]*_restore_drill$ ]]; then
  echo "Restore drill database must be a simple identifier ending in _restore_drill." >&2
  exit 1
fi
if [[ "${restore_drill_db}" == "dream_motif" ]]; then
  echo "Refusing to restore into the canonical dream_motif database." >&2
  exit 1
fi

created_at_utc=""
build_sha=""
database_name=""
backup_file=""
backup_sha256=""
alembic_revision=""
previous_api_image_id=""
previous_api_build_sha=""

while IFS='=' read -r key value || [[ -n "${key}" ]]; do
  case "${key}" in
    "" | "#"*) ;;
    created_at_utc) created_at_utc="${value}" ;;
    build_sha) build_sha="${value}" ;;
    database_name) database_name="${value}" ;;
    backup_file) backup_file="${value}" ;;
    backup_sha256) backup_sha256="${value}" ;;
    alembic_revision) alembic_revision="${value}" ;;
    previous_api_image_id) previous_api_image_id="${value}" ;;
    previous_api_build_sha) previous_api_build_sha="${value}" ;;
  esac
done <"${manifest_file}"

for required_name in created_at_utc build_sha database_name backup_file backup_sha256 alembic_revision; do
  if [[ -z "${!required_name}" ]]; then
    echo "Manifest is missing required field: ${required_name}" >&2
    exit 1
  fi
done
if [[ "${database_name}" != "dream_motif" ]]; then
  echo "Manifest database_name must be dream_motif." >&2
  exit 1
fi
if [[ "${backup_file}" != /* ]]; then
  echo "Manifest backup_file must be an absolute path." >&2
  exit 1
fi
if [[ ! -f "${backup_file}" || -L "${backup_file}" ]]; then
  echo "Backup archive must be a regular file: ${backup_file}" >&2
  exit 1
fi
backup_mode="$(stat -c '%a' "${backup_file}")"
if [[ "${backup_mode}" != "600" && "${backup_mode}" != "400" ]]; then
  echo "Backup archive must not be group/world-readable; expected mode 600 or 400, got ${backup_mode}." >&2
  exit 1
fi
actual_sha256="$(sha256sum "${backup_file}")"
actual_sha256="${actual_sha256%% *}"
if [[ "${actual_sha256}" != "${backup_sha256}" ]]; then
  echo "Backup SHA256 mismatch." >&2
  exit 1
fi

compose=(docker compose -f docker-compose.yml)
"${compose[@]}" config --quiet

if [[ -n "${previous_api_image_id}" ]]; then
  docker image inspect "${previous_api_image_id}" >/dev/null
  if [[ -z "${previous_api_build_sha}" ]]; then
    echo "Previous API image is recorded but has no OCI revision label." >&2
    exit 1
  fi
  inspected_previous_sha="$(docker image inspect "${previous_api_image_id}" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
  if [[ "${inspected_previous_sha}" != "${previous_api_build_sha}" ]]; then
    echo "Previous API image OCI revision label does not match the manifest." >&2
    exit 1
  fi
elif [[ "${allow_missing_previous_image}" != true ]]; then
  echo "Manifest has no previous API image; rerun with --allow-missing-previous-image only for first-launch drills." >&2
  exit 1
fi

echo "Starting PostgreSQL for restore drill..."
"${compose[@]}" up -d --wait postgres

echo "Verifying PostgreSQL archive listing..."
"${compose[@]}" exec -T postgres pg_restore --list <"${backup_file}" >/dev/null

restore_drill_started=false

drop_restore_drill_db() {
  "${compose[@]}" exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${restore_drill_db}' AND pid <> pg_backend_pid();" \
    >/dev/null 2>&1 || true
  "${compose[@]}" exec -T postgres dropdb -U postgres --if-exists "${restore_drill_db}" >/dev/null 2>&1 || true
}

cleanup() {
  if [[ "${restore_drill_started}" == true ]]; then
    drop_restore_drill_db
  fi
}
trap cleanup EXIT

echo "Restoring into disposable database ${restore_drill_db}..."
restore_drill_started=true
drop_restore_drill_db
"${compose[@]}" exec -T postgres createdb -U postgres "${restore_drill_db}"
"${compose[@]}" exec -T postgres pg_restore -U postgres -d "${restore_drill_db}" <"${backup_file}" >/dev/null

if [[ "${alembic_revision}" != "none" ]]; then
  restored_revision="$("${compose[@]}" exec -T postgres psql -U postgres -d "${restore_drill_db}" -Atc 'select version_num from alembic_version limit 1;')"
  if [[ "${restored_revision}" != "${alembic_revision}" ]]; then
    echo "Restored Alembic revision ${restored_revision} does not match manifest ${alembic_revision}." >&2
    exit 1
  fi
fi

drop_restore_drill_db
restore_drill_started=false
trap - EXIT

echo "Rollback verifier complete for ${backup_file}; disposable database ${restore_drill_db} was removed."
