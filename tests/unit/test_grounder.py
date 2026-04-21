from __future__ import annotations

import json
import uuid
from datetime import date

import pytest

from app.llm.grounder import GroundedTheme, Grounder
from app.llm.theme_extractor import ThemeAssignment
from app.models.dream import DreamEntry


class FixedLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, system: str, user: str, *, max_tokens: int = 1000) -> str:
        del system, user, max_tokens
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


def _dream_entry() -> DreamEntry:
    return DreamEntry(
        source_doc_id="doc-1",
        date=date(2026, 4, 12),
        title="Flooded childhood house",
        raw_text=(
            "I was back in my childhood house and water kept rising through the rooms. "
            "My mother watched from the stairs while I tried to seal the doors."
        ),
        word_count=27,
        content_hash="grounder-test-hash",
        segmentation_confidence="high",
    )


def _assignments() -> list[ThemeAssignment]:
    return [
        ThemeAssignment(
            category_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            salience=0.7,
            match_type="literal",
            justification="Water is repeatedly described as rising.",
        ),
        ThemeAssignment(
            category_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            salience=0.6,
            match_type="semantic",
            justification="The mother is an emotionally significant figure.",
        ),
    ]


@pytest.mark.asyncio
async def test_ground_returns_grounded_themes() -> None:
    raw_text = _dream_entry().raw_text
    water_text = "water kept rising"
    mother_text = "My mother watched"
    client = FixedLLMClient(
        [
            json.dumps(
                {
                    "themes": [
                        {
                            "category_id": str(_assignments()[1].category_id),
                            "salience": 0.81,
                            "fragments": [
                                {
                                    "text": mother_text,
                                    "start_offset": raw_text.index(mother_text),
                                    "end_offset": raw_text.index(mother_text) + len(mother_text),
                                    "match_type": "semantic",
                                }
                            ],
                        },
                        {
                            "category_id": str(_assignments()[0].category_id),
                            "salience": 0.93,
                            "fragments": [
                                {
                                    "text": water_text,
                                    "start_offset": raw_text.index(water_text),
                                    "end_offset": raw_text.index(water_text) + len(water_text),
                                    "match_type": "literal",
                                }
                            ],
                        },
                    ]
                }
            )
        ]
    )

    grounded = await Grounder(client=client).ground(_dream_entry(), _assignments())

    assert [theme.category_id for theme in grounded] == [
        _assignments()[0].category_id,
        _assignments()[1].category_id,
    ]
    assert all(isinstance(theme, GroundedTheme) for theme in grounded)
    assert grounded[0].salience >= grounded[1].salience
    assert all(theme.fragments for theme in grounded)
    assert all(
        set(fragment) == {"text", "start_offset", "end_offset", "match_type", "verified"}
        for theme in grounded
        for fragment in theme.fragments
    )


@pytest.mark.asyncio
async def test_fragment_text_matches_source_offsets() -> None:
    dream_entry = _dream_entry()
    valid_text = "water kept rising"
    invalid_text = "mother called"
    valid_start = dream_entry.raw_text.index(valid_text)
    invalid_start = dream_entry.raw_text.index("My mother watched")
    client = FixedLLMClient(
        [
            json.dumps(
                {
                    "themes": [
                        {
                            "category_id": str(_assignments()[0].category_id),
                            "salience": 0.9,
                            "fragments": [
                                {
                                    "text": valid_text,
                                    "start_offset": valid_start,
                                    "end_offset": valid_start + len(valid_text),
                                    "match_type": "literal",
                                },
                                {
                                    "text": invalid_text,
                                    "start_offset": invalid_start,
                                    "end_offset": invalid_start + len(invalid_text),
                                    "match_type": "semantic",
                                },
                            ],
                        }
                    ]
                }
            )
        ]
    )

    grounded = await Grounder(client=client).ground(dream_entry, [_assignments()[0]])
    fragments = grounded[0].fragments

    assert (
        fragments[0]["text"]
        == dream_entry.raw_text[fragments[0]["start_offset"] : fragments[0]["end_offset"]]
    )
    assert fragments[0]["verified"] is True
    assert (
        fragments[1]["text"]
        != dream_entry.raw_text[fragments[1]["start_offset"] : fragments[1]["end_offset"]]
    )
    assert fragments[1]["verified"] is False


@pytest.mark.asyncio
async def test_ground_accepts_json_code_fence() -> None:
    raw_text = _dream_entry().raw_text
    fragment_text = "water kept rising"
    client = FixedLLMClient(
        [
            f"""```json
            {{"themes":[{{"category_id":"{_assignments()[0].category_id}","salience":0.9,"fragments":[{{"text":"{fragment_text}","start_offset":{raw_text.index(fragment_text)},"end_offset":{raw_text.index(fragment_text) + len(fragment_text)},"match_type":"literal"}}]}}]}}
            ```"""
        ]
    )

    grounded = await Grounder(client=client).ground(_dream_entry(), [_assignments()[0]])

    assert [theme.category_id for theme in grounded] == [_assignments()[0].category_id]


@pytest.mark.asyncio
async def test_ground_accepts_prefixed_text_around_json() -> None:
    raw_text = _dream_entry().raw_text
    fragment_text = "My mother watched"
    client = FixedLLMClient(
        [
            (
                "Here is the grounded draft JSON.\n"
                f'{{"themes":[{{"category_id":"{_assignments()[1].category_id}","salience":0.8,"fragments":[{{"text":"{fragment_text}","start_offset":{raw_text.index(fragment_text)},"end_offset":{raw_text.index(fragment_text) + len(fragment_text)},"match_type":"semantic"}}]}}]}}'
            )
        ]
    )

    grounded = await Grounder(client=client).ground(_dream_entry(), [_assignments()[1]])

    assert [theme.category_id for theme in grounded] == [_assignments()[1].category_id]
