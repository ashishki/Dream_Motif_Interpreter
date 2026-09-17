from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_rollback_verifier_is_restore_drill_only() -> None:
    script_path = PROJECT_ROOT / "scripts" / "verify_compose_rollback.sh"
    script = script_path.read_text(encoding="utf-8")

    assert os.access(script_path, os.X_OK)
    assert "Usage: scripts/verify_compose_rollback.sh --manifest FILE" in script
    assert "--restore-drill-db NAME" in script
    assert "ending in _restore_drill" in script
    assert "Refusing to restore into the canonical dream_motif database" in script
    assert "createdb -U postgres" in script
    assert "dropdb -U postgres --if-exists" in script
    assert "trap cleanup EXIT" in script
    assert "drop_restore_drill_db" in script


def test_rollback_verifier_checks_archive_and_previous_image_identity() -> None:
    script = (PROJECT_ROOT / "scripts" / "verify_compose_rollback.sh").read_text(encoding="utf-8")

    assert "while IFS='=' read -r key value" in script
    assert "source " not in script
    assert "backup_sha256" in script
    assert "sha256sum" in script
    assert "pg_restore --list" in script
    assert "docker image inspect" in script
    assert 'org.opencontainers.image.revision" }}' in script
    assert "Previous API image OCI revision label does not match the manifest" in script
    assert "--allow-missing-previous-image only for first-launch drills" in script
    assert "select version_num from alembic_version limit 1" in script


def test_rollback_drill_docs_point_to_the_verifier() -> None:
    deploy = (PROJECT_ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    bot_runbook = (PROJECT_ROOT / "docs" / "RUNBOOK_TELEGRAM_BOT.md").read_text(encoding="utf-8")

    for document in (deploy, bot_runbook):
        assert "./scripts/verify_compose_rollback.sh" in document
        assert "--restore-drill-db dream_motif_restore_drill" in document
        assert "refuses the canonical `dream_motif` database" in document
