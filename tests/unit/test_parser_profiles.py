from __future__ import annotations

from datetime import datetime, timezone

from app.retrieval.types import NormalizedDocument
from app.services.segmentation import (
    get_parser_profile_registry,
    parse_dream_entry_candidates,
    resolve_parser_profile,
)


def _build_document(
    paragraphs: list[str],
    *,
    metadata: dict[str, object] | None = None,
) -> NormalizedDocument:
    return NormalizedDocument(
        client_id="default",
        source_type="google_doc",
        external_id="doc-parser-profiles",
        source_path="documents/doc-parser-profiles",
        title="Dream Journal",
        raw_text="\n\n".join(paragraphs),
        sections=paragraphs,
        metadata=metadata or {},
        fetched_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )


def test_profile_registry_contains_required_profiles() -> None:
    registry = get_parser_profile_registry()

    assert {"default", "dated_entries", "heading_based"}.issubset(registry)


def test_explicit_profile_overrides_autodetect() -> None:
    document = _build_document(
        [
            "2026-01-01",
            "I was walking through a flooded station.",
            "2026-01-02",
            "A violin was buried under the platform.",
        ],
        metadata={"parser_profile": "heading_based"},
    )

    resolved_profile, candidates = parse_dream_entry_candidates(document)

    assert resolved_profile.profile_name == "heading_based"
    assert len(candidates) == 1
    assert candidates[0].applied_profile == "heading_based"
    assert candidates[0].segmentation_confidence == "low"


def test_low_confidence_autodetect_falls_back_to_default() -> None:
    document = _build_document(
        [
            "I was standing in an empty field at dusk.",
            "The wind kept moving the same ladder in slow circles.",
        ]
    )

    resolved_profile, candidates = parse_dream_entry_candidates(document)

    assert resolved_profile.profile_name == "default"
    assert len(candidates) == 1
    assert candidates[0].applied_profile == "default"
    assert any("falling back to default profile" in warning for warning in candidates[0].parse_warnings)


def test_heading_based_profile_detects_structured_entries() -> None:
    document = _build_document(
        [
            "Офис",
            "Я вернулась в старый офис и искала несуществующую дверь.",
            "Коридор",
            "Длинный коридор заканчивался окном в море.",
        ]
    )

    resolved_profile = resolve_parser_profile(document)
    _, candidates = parse_dream_entry_candidates(document)

    assert resolved_profile.profile_name == "heading_based"
    assert [candidate.title for candidate in candidates] == ["Офис", "Коридор"]
