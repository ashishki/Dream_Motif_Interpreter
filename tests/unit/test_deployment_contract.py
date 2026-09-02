from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_compose_build_has_a_real_dockerfile_and_runtime_services() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim" in dockerfile
    assert "USER app" in dockerfile
    assert "ARG BUILD_SHA=unknown" in dockerfile
    assert 'LABEL org.opencontainers.image.revision="${BUILD_SHA}"' in dockerfile
    assert "BUILD_SHA=${BUILD_SHA}" in dockerfile
    assert (
        "x-app-image: &app-image "
        "${APP_IMAGE_REPOSITORY:-dream-motif-interpreter}:${BUILD_SHA:-unknown}"
    ) in compose
    assert "BUILD_SHA: ${BUILD_SHA:-unknown}" in compose
    assert compose.count("image: *app-image") == 4
    assert "RUNTIME_STATE_FILE: /var/lib/dream-motif/runtime_extra_docs.json" in compose
    assert "runtime_state:/var/lib/dream-motif" in compose
    assert "migrate:" in compose
    assert "api:" in compose
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000" in compose
    assert "telegram-bot:" in compose
    assert "auto-sync:" in compose
    assert "service_completed_successfully" in compose
    assert "127.0.0.1:${POSTGRES_PORT:-5432}:5432" in compose
    assert "127.0.0.1:${REDIS_PORT:-6379}:6379" in compose
    assert compose.count("POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env") == 1
    assert compose.count("postgres:${POSTGRES_PASSWORD}@postgres:5432/dream_motif") == 4
    assert "POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}@postgres" not in compose
    assert "POSTGRES_PASSWORD:-postgres" not in compose


def test_production_requirements_never_install_the_repository_from_git() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lock = (PROJECT_ROOT / "requirements.lock").read_text(encoding="utf-8")
    dev_lock = (PROJECT_ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "git+https://" not in requirements
    assert requirements.rstrip().endswith("-e .")
    assert "--hash=sha256:" in lock
    assert "--hash=sha256:" in dev_lock
    assert "--require-hashes -r requirements.lock" in dockerfile
    assert "--require-hashes -r requirements-dev.lock" in workflow
    assert "pip check" in dockerfile
    assert "pip check" in workflow


def test_example_environment_is_safe_and_complete_enough_to_boot_after_setup() -> None:
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "SECRET_KEY=replace-me" in example
    assert "POSTGRES_PASSWORD=replace-me" in example
    assert "API_BIND_ADDRESS=127.0.0.1" in example
    assert "APP_IMAGE_REPOSITORY=dream-motif-interpreter" in example
    assert "GOOGLE_SERVICE_ACCOUNT_HOST_FILE=" in example
    assert "TELEGRAM_ALLOWED_CHAT_ID=0" in example
    assert "VOICE_TRANSCRIPT_RETENTION_SECONDS=" in example
    assert "RUNTIME_STATE_FILE" not in example  # Compose supplies its persistent path.


def test_google_service_account_mount_is_explicit_read_only_overlay() -> None:
    overlay = (PROJECT_ROOT / "docker-compose.google-service-account.yml").read_text(
        encoding="utf-8"
    )
    base = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "GOOGLE_SERVICE_ACCOUNT_HOST_FILE:?" in overlay
    assert "target: /run/secrets/google-service-account.json" in overlay
    assert "read_only: true" in overlay
    assert "GOOGLE_SERVICE_ACCOUNT_FILE: /run/secrets/google-service-account.json" in overlay
    assert "/run/secrets/google-service-account.json" not in base


def test_ci_verifies_compose_and_non_root_container_contract() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "container-contract:" in workflow
    assert "Refuse missing PostgreSQL password" in workflow
    assert "docker compose config succeeded without POSTGRES_PASSWORD" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker-compose.google-service-account.yml config --quiet" in workflow
    assert "docker build --build-arg BUILD_SHA=" in workflow
    assert "Verify image revision label" in workflow
    assert 'org.opencontainers.image.revision" }}' in workflow
    assert 'test "$(id -u)" -ne 0' in workflow
    assert "test -w /var/lib/dream-voice" in workflow
    assert "test -w /var/lib/dream-motif" in workflow


def test_integration_database_guard_requires_an_explicit_test_suffix() -> None:
    conftest = (PROJECT_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert "_validated_test_database_url" in conftest
    assert 'endswith(("_test", "_testing", "_eval"))' in conftest


def test_compose_rollout_quiesces_writers_before_migration() -> None:
    script_path = PROJECT_ROOT / "scripts" / "deploy_compose.sh"
    script = script_path.read_text(encoding="utf-8")

    assert os.access(script_path, os.X_OK)
    stop = script.index(
        '"${compose[@]}" --profile autosync stop --timeout 50 api telegram-bot auto-sync'
    )
    infrastructure = script.index('"${compose[@]}" up -d --wait postgres redis')
    backup_dump = script.index("pg_dump -U postgres -d dream_motif --format=custom")
    backup_verify = script.index("pg_restore --list")
    build = script.index('"${compose[@]}" --profile autosync build "${build_services[@]}"')
    migration = script.index('"${compose[@]}" run --rm --no-deps migrate')
    api_start = script.index('"${compose[@]}" up -d --no-deps --no-build api')
    ready_check = script.index('urllib.request.urlopen("http://127.0.0.1:8000/ready"')
    bot_start = script.index('"${compose[@]}" up -d --no-deps --no-build telegram-bot')
    autosync_start = script.index(
        '"${compose[@]}" --profile autosync up -d --no-deps --no-build auto-sync'
    )

    assert (
        stop
        < infrastructure
        < backup_dump
        < backup_verify
        < build
        < migration
        < api_start
        < ready_check
        < bot_start
        < autosync_start
    )
    assert "Usage: scripts/deploy_compose.sh --backup-dir DIR" in script
    assert 'backup_dir="${DEPLOY_BACKUP_DIR:-}"' in script
    assert "refusing to migrate without a verified pre-migration backup" in script
    assert "Backup directory must be outside the repository checkout" in script
    assert "Refusing to overwrite an existing backup archive or manifest" in script
    assert "Pre-migration PostgreSQL backup is empty" in script
    assert "backup_sha256=" in script
    assert "alembic_revision=" in script
    assert "Refusing to deploy a dirty worktree" in script
    assert 'if [[ "${BUILD_SHA}" != "${head_sha}" ]]' in script
    assert "BUILD_SHA must identify the exact deployed commit" in script
    assert "trap on_error ERR" in script
    assert "rollout_phase=before_quiesce" in script
    assert "rollout_phase=quiesced" in script
    assert "rollout_phase=starting_api" in script
    assert "rollout_phase=starting_writers" in script
    assert "Rollout failed before quiescing application writers" in script
    assert "Rollout failed while application writers are quiesced or partially started" in script


def test_active_deployment_docs_use_the_quiesced_rollout_script() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    deploy = (PROJECT_ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    bot_runbook = (PROJECT_ROOT / "docs" / "RUNBOOK_TELEGRAM_BOT.md").read_text(encoding="utf-8")
    voice_runbook = (PROJECT_ROOT / "docs" / "RUNBOOK_VOICE_PIPELINE.md").read_text(
        encoding="utf-8"
    )

    for document in (readme, deploy, bot_runbook, voice_runbook):
        assert "./scripts/deploy_compose.sh" in document

    assert "stop `api`, `telegram-bot` and `auto-sync`" in deploy
    assert 'deploy_compose.sh --backup-dir "$DEPLOY_BACKUP_DIR"' in readme
    assert 'deploy_compose.sh --backup-dir "$DEPLOY_BACKUP_DIR"' in deploy
    assert 'deploy_compose.sh --backup-dir "$DEPLOY_BACKUP_DIR"' in bot_runbook
    assert 'deploy_compose.sh --backup-dir "$DEPLOY_BACKUP_DIR"' in voice_runbook
    assert "run `alembic upgrade head`" in deploy
    assert "verify it with `pg_restore --list`" in deploy
    assert "only after the API reports `/ready` for the intended" in deploy
    assert "`BUILD_SHA`, so background writers do not accept new work" in deploy
    assert "Keep previous release" in deploy
    assert "tags until the rollback drill" in deploy
