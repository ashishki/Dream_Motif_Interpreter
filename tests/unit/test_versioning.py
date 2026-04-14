from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_no_delete_or_update_on_annotation_versions() -> None:
    forbidden_patterns = (
        "DELETE FROM " + "annotation_versions",
        "UPDATE " + "annotation_versions",
    )
    search_roots = (
        PROJECT_ROOT / "app",
        PROJECT_ROOT / "tests",
        PROJECT_ROOT / "alembic",
        PROJECT_ROOT / "scripts",
    )
    offenders: list[str] = []

    for root in search_roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".sql"}:
                continue
            content = path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                if pattern in content:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {pattern}")

    assert offenders == []
