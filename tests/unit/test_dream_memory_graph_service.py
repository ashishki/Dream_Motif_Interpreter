from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from app.models.dream_graph import GraphConfirmationStatus, GraphEdgeType
from app.services.dream_memory_graph import build_dream_memory_snapshot


def _dream(*, title: str, dream_date: date) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), title=title, date=dream_date)


def _motif(*, dream_id: uuid.UUID, label: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        dream_id=dream_id,
        label=label,
        status=status,
        confidence="high",
        model_version="test-v1",
        fragments=[{"text": "лестница", "start_offset": 3, "end_offset": 11}],
    )


def test_state_snapshot_can_use_human_dream_title_and_date() -> None:
    dream = _dream(title="Башня", dream_date=date(2026, 8, 30))

    private_snapshot = build_dream_memory_snapshot(dreams=[dream], motifs=[])
    state_snapshot = build_dream_memory_snapshot(
        dreams=[dream],
        motifs=[],
        include_dream_labels=True,
    )

    assert private_snapshot.nodes[0].label == f"dream:{dream.id}"
    assert state_snapshot.nodes[0].label == "30.08.26 — Башня"


def test_repeated_motif_labels_are_linked_across_dreams() -> None:
    first_dream = _dream(title="Первый", dream_date=date(2026, 8, 29))
    second_dream = _dream(title="Второй", dream_date=date(2026, 8, 30))
    first = _motif(
        dream_id=first_dream.id,
        label="Закрытая дверь",
        status="confirmed",
    )
    second = _motif(
        dream_id=second_dream.id,
        label="  закрытая   ДВЕРЬ ",
        status="confirmed",
    )

    snapshot = build_dream_memory_snapshot(
        dreams=[first_dream, second_dream],
        motifs=[first, second],
    )
    repeat_edges = [edge for edge in snapshot.edges if edge.edge_type is GraphEdgeType.REPEATS_WITH]

    assert len(repeat_edges) == 1
    assert repeat_edges[0].confirmation_status is GraphConfirmationStatus.CONFIRMED
    assert repeat_edges[0].suggestion is not None
    assert {ref.dream_id for ref in repeat_edges[0].suggestion.source_fragments} == {
        str(first_dream.id),
        str(second_dream.id),
    }
