from types import SimpleNamespace
import uuid

import pytest

from app.assistant.selection import (
    parse_selection_command,
    visible_references,
    selection_text,
    is_selection_analysis,
)


def ref(title, day="2026-09-01"):
    return SimpleNamespace(dream_id=str(uuid.uuid4()), title=title, date=day)


@pytest.mark.parametrize(
    "text,action,numbers",
    [
        ("Покажи второй целиком", "open", (2,)),
        ("Открой сон номер 3", "open", (3,)),
        ("Третий не подходит", "remove", (3,)),
        ("Убери 2 и 4 из подборки", "remove", (2, 4)),
        ("Оставь только первый и третий", "keep", (1, 3)),
        ("Покажи подборку", "show", ()),
    ],
)
def test_read_only_commands(text, action, numbers):
    command = parse_selection_command(text)
    assert command.action == action
    assert command.indices == numbers


@pytest.mark.parametrize(
    "text",
    [
        "Удали третий сон",
        "Убери все сны из архива",
        "Покажи сон про море",
        "Мне приснился второй дом",
        "Оставь 0",
        "Открой 2 и 3",
    ],
)
def test_ambiguous_or_archive_mutation_is_not_selection_command(text):
    assert parse_selection_command(text) is None


def test_visible_order_is_not_retrieval_order():
    first, second = ref("Северный мост"), ref("Пустой сад", "2026-09-02")
    assert visible_references(
        "1. 02.09.26 Пустой сад\n2. 01.09.26 Северный мост", [first, second]
    ) == [second, first]


def test_same_date_does_not_make_hidden_candidates_visible():
    shown, hidden = ref("Мост"), ref("Поезд")
    assert visible_references("1. 01.09.26 Мост", [shown, hidden]) == [shown]


def test_numbered_paragraphs_never_bind_hidden_candidates():
    assert (
        visible_references("1. Посмотрим\n2. Недостаточно данных", [ref("Мост"), ref("Поезд")])
        == []
    )


def test_duplicate_titles_need_unambiguous_dates():
    first, second = ref("Дом"), ref("Дом", "2026-09-02")
    assert visible_references("1. Дом", [first, second]) == []
    assert visible_references("1. 02.09.26 Дом", [first, second]) == [second]


def test_empty_selection_does_not_expose_ids():
    assert "пуста" in selection_text([])
    item = ref("Сад")
    assert item.dream_id not in selection_text([item])


@pytest.mark.parametrize(
    "text", ["А что у них общего?", "Сравни оставшиеся", "Что там повторяется?"]
)
def test_natural_followup_analysis(text):
    assert is_selection_analysis(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("#границы", "#границы"),
        ("Код: возвращение домой", "#возвращение домой"),
        ("Добавь код к этому сну: #возвращение", "#возвращение"),
        ("Добавь код: мост", "#мост"),
        ("Предложи коды", None),
        ("Не добавляй код: мост", None),
        ("#", None),
    ],
)
def test_only_explicit_human_codes_become_note_requests(text, expected):
    from app.telegram.handlers import _extract_direct_note_text

    assert _extract_direct_note_text(text) == expected


def test_short_title_inside_other_title_is_not_another_dream():
    first, second = ref("Дом"), ref("Дом у моря")
    assert visible_references("1. Дом у моря", [first, second]) == [second]
    assert visible_references("1. Дом у моря\n2. Дом", [first, second]) == [second, first]


def test_visible_numbers_are_checked_before_using_ordinals():
    from app.assistant.selection import numbered_references_are_consistent

    first, second = ref("Мост"), ref("Дом")
    assert numbered_references_are_consistent("1. Мост\n2. Дом", [first, second])
    assert not numbered_references_are_consistent("1. Мост\n3. Дом", [first, second])
    assert not numbered_references_are_consistent("1. Мост и Дом", [first, second])
