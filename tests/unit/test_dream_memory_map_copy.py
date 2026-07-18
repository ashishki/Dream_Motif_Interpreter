from __future__ import annotations

from pathlib import Path


MINI_APP_HTML = Path(__file__).resolve().parents[2] / "app" / "static" / "dream_memory_map.html"


def test_graph_privacy_action_does_not_claim_to_delete_archive_data() -> None:
    html = MINI_APP_HTML.read_text(encoding="utf-8")

    assert "Убрать из карты" in html
    assert "не удаляет исходную запись сна" in html
    assert ">Delete<" not in html
    assert "source_node_id} ->" not in html


def test_graph_shell_uses_telegram_theme_and_accessible_status() -> None:
    html = MINI_APP_HTML.read_text(encoding="utf-8")

    assert "--tg-theme-bg-color" in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'lang="ru"' in html
