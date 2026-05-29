from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DREAM_MEMORY_MAP = REPO_ROOT / "docs" / "DREAM_MEMORY_MAP.md"
PRODUCT_OVERVIEW = REPO_ROOT / "docs" / "PRODUCT_OVERVIEW.md"
README = REPO_ROOT / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(path: Path) -> str:
    return " ".join(_read(path).split())


def test_dream_memory_map_defines_required_screens() -> None:
    text = _read(DREAM_MEMORY_MAP)

    for heading in [
        "### Dream Entry",
        "### Motif Graph",
        "### Recurring Motif Page",
        "### Timeline",
        "### Search",
        "### Privacy and Export Settings",
    ]:
        assert heading in text

    assert "Telegram mini app" in text
    assert "Obsidian is a visual and structural reference only" in text


def test_dream_memory_map_is_reflective_not_diagnostic() -> None:
    text = _flat(DREAM_MEMORY_MAP)
    overview = _flat(PRODUCT_OVERVIEW)
    readme = _flat(README)

    assert "reflective dream journaling and pattern memory" in text
    assert "not psychological diagnosis" in text
    assert "not diagnosis" in overview
    assert "not psychological diagnosis" in readme


def test_dream_memory_map_splits_bot_and_mini_app_responsibilities() -> None:
    text = _read(DREAM_MEMORY_MAP)

    assert "### Telegram Bot" in text
    assert "### Telegram Mini App" in text

    bot_section = text.split("### Telegram Bot", maxsplit=1)[1].split(
        "### Telegram Mini App",
        maxsplit=1,
    )[0]
    mini_app_section = text.split("### Telegram Mini App", maxsplit=1)[1].split(
        "## 4. Core Screens",
        maxsplit=1,
    )[0]

    for expected in [
        "text dream capture",
        "voice dream capture and transcription",
        "explicit sync trigger",
        "archive search through conversation",
    ]:
        assert expected in bot_section

    for expected in [
        "motif graph browsing",
        "recurring motif pages with linked evidence",
        "timeline exploration",
        "privacy, export, deletion, and hidden-item controls",
    ]:
        assert expected in mini_app_section
