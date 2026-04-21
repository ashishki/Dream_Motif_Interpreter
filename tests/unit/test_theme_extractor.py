from __future__ import annotations

import json
import uuid
from datetime import date

import pytest

from app.llm.theme_extractor import ThemeAssignment, ThemeExtractor
from app.models.dream import DreamEntry
from app.models.theme import ThemeCategory


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
        content_hash="theme-extractor-test-hash",
        segmentation_confidence="high",
    )


def _categories() -> list[ThemeCategory]:
    return [
        ThemeCategory(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            name="water",
            description="Water imagery.",
            status="active",
        ),
        ThemeCategory(
            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            name="mother_figure",
            description="Mother imagery.",
            status="active",
        ),
        ThemeCategory(
            id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            name="house_rooms",
            description="Rooms and houses.",
            status="active",
        ),
    ]


@pytest.mark.asyncio
async def test_extract_returns_valid_structure() -> None:
    categories = _categories()
    client = FixedLLMClient(
        [
            json.dumps(
                {
                    "themes": [
                        {
                            "category_id": str(categories[0].id),
                            "salience": 0.92,
                            "match_type": "literal",
                            "justification": "Water is repeatedly described as rising.",
                        },
                        {
                            "category_id": str(categories[1].id),
                            "salience": 0.78,
                            "match_type": "semantic",
                            "justification": "The mother is present as an important relational figure.",
                        },
                    ]
                }
            )
        ]
    )

    assignments = await ThemeExtractor(client=client).extract(_dream_entry(), categories)

    assert assignments
    assert all(isinstance(assignment, ThemeAssignment) for assignment in assignments)
    assert [assignment.category_id for assignment in assignments] == [
        categories[0].id,
        categories[1].id,
    ]
    assert all(0.0 <= assignment.salience <= 1.0 for assignment in assignments)
    assert {assignment.match_type for assignment in assignments} <= {
        "literal",
        "semantic",
        "symbolic",
    }
    assert all(
        isinstance(assignment.justification, str) and assignment.justification
        for assignment in assignments
    )


@pytest.mark.asyncio
async def test_no_hallucinated_category_ids() -> None:
    categories = _categories()
    hallucinated_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    client = FixedLLMClient(
        [
            json.dumps(
                {
                    "themes": [
                        {
                            "category_id": str(hallucinated_id),
                            "salience": 0.9,
                            "match_type": "symbolic",
                            "justification": "Invalid category on purpose.",
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "themes": [
                        {
                            "category_id": str(categories[2].id),
                            "salience": 0.81,
                            "match_type": "literal",
                            "justification": "The house rooms are central to the scene.",
                        }
                    ]
                }
            ),
        ]
    )

    assignments = await ThemeExtractor(client=client).extract(_dream_entry(), categories)

    assert client.calls == 2
    assert [assignment.category_id for assignment in assignments] == [categories[2].id]


@pytest.mark.asyncio
async def test_extraction_consistency() -> None:
    categories = _categories()
    response = json.dumps(
        {
            "themes": [
                {
                    "category_id": str(categories[0].id),
                    "salience": 0.95,
                    "match_type": "literal",
                    "justification": "Flooding dominates the imagery.",
                },
                {
                    "category_id": str(categories[2].id),
                    "salience": 0.82,
                    "match_type": "literal",
                    "justification": "The house is the main setting.",
                },
                {
                    "category_id": str(categories[1].id),
                    "salience": 0.79,
                    "match_type": "semantic",
                    "justification": "The mother's presence shapes the emotional context.",
                },
            ]
        }
    )
    extractor = ThemeExtractor(client=FixedLLMClient([response, response]))

    first = await extractor.extract(_dream_entry(), categories)
    second = await extractor.extract(_dream_entry(), categories)

    first_top_three = {assignment.category_id for assignment in first[:3]}
    second_top_three = {assignment.category_id for assignment in second[:3]}
    overlap = len(first_top_three & second_top_three) / 3

    assert overlap >= 0.8


@pytest.mark.asyncio
async def test_extract_accepts_json_code_fence() -> None:
    categories = _categories()
    client = FixedLLMClient(
        [
            """```json
            {"themes":[{"category_id":"11111111-1111-1111-1111-111111111111","salience":0.9,"match_type":"literal","justification":"Water dominates the imagery."}]}
            ```"""
        ]
    )

    assignments = await ThemeExtractor(client=client).extract(_dream_entry(), categories)

    assert [assignment.category_id for assignment in assignments] == [categories[0].id]


@pytest.mark.asyncio
async def test_extract_accepts_prefixed_text_around_json() -> None:
    categories = _categories()
    client = FixedLLMClient(
        [
            (
                "Here is the draft JSON response.\n"
                '{"themes":[{"category_id":"22222222-2222-2222-2222-222222222222","salience":0.84,"match_type":"semantic","justification":"The mother is central to the dream."}]}'
            )
        ]
    )

    assignments = await ThemeExtractor(client=client).extract(_dream_entry(), categories)

    assert [assignment.category_id for assignment in assignments] == [categories[1].id]
