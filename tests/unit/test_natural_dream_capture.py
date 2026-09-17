from __future__ import annotations

import pytest

from app.assistant.tools import _has_natural_dream_opening, _split_natural_dream_followup


@pytest.mark.parametrize(
    "text",
    [
        "Мне приснился мост.",
        "Сегодня мне приснилось, что я вернулся домой.",
        "  мне снилось море",
    ],
)
def test_natural_dream_opening_accepts_only_clear_leading_capture(text: str) -> None:
    assert _has_natural_dream_opening(text)


@pytest.mark.parametrize(
    "text",
    [
        "Терапевт спросил, что мне приснилось вчера.",
        "Я сказал: мне приснился мост.",
        "Мне приснился мост, но не сохраняй этот сон.",
        "Не нужно сохранять: мне приснился мост.",
    ],
)
def test_natural_dream_opening_rejects_mentions_and_negative_capture(text: str) -> None:
    assert not _has_natural_dream_opening(text)


def test_split_natural_followup_keeps_meta_question_out_of_archive_text() -> None:
    dream, followup = _split_natural_dream_followup(
        "Мне приснилось, что я иду по мосту. Что это значит?"
    )

    assert dream == "Мне приснилось, что я иду по мосту."
    assert followup == "Что это значит?"


def test_split_natural_followup_keeps_question_spoken_inside_dream() -> None:
    text = "Мне приснилось, что я спросил: «Куда мы идём?» Потом проснулся."

    assert _split_natural_dream_followup(text) == (text, None)
