from __future__ import annotations

import pytest

from app.models.dream_graph import (
    GRAPH_EDGE_TYPES,
    GRAPH_NODE_TYPES,
    GraphConfirmationStatus,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    ModelSuggestionProvenance,
    SourceDreamFragmentRef,
)


def test_graph_schema_defines_required_node_types() -> None:
    assert {node_type.value for node_type in GRAPH_NODE_TYPES} == {
        "Dream",
        "Motif",
        "Person",
        "Place",
        "Emotion",
        "Event",
    }

    node = GraphNode(id="motif:stairs", node_type=GraphNodeType.MOTIF, label="stairs")
    assert node.confirmation_status is GraphConfirmationStatus.UNREVIEWED


def test_graph_schema_defines_required_edge_types() -> None:
    assert {edge_type.value for edge_type in GRAPH_EDGE_TYPES} == {
        "appears_in",
        "repeats_with",
        "contradicts",
        "evolves_from",
        "user_confirmed",
    }

    edge = GraphEdge(
        id="edge:stairs:dream-1",
        edge_type=GraphEdgeType.APPEARS_IN,
        source_node_id="motif:stairs",
        target_node_id="dream:1",
    )
    assert edge.confirmation_status is GraphConfirmationStatus.UNREVIEWED


def test_ai_suggested_edge_requires_source_dream_fragment_references() -> None:
    fragment_ref = SourceDreamFragmentRef(dream_id="dream-1", chunk_id="chunk-4")
    suggestion = ModelSuggestionProvenance(
        model_name="test-model",
        model_version="v1",
        confidence="moderate",
        source_fragments=(fragment_ref,),
    )

    edge = GraphEdge(
        id="edge:stairs:dream-1",
        edge_type=GraphEdgeType.APPEARS_IN,
        source_node_id="motif:stairs",
        target_node_id="dream:1",
        suggestion=suggestion,
    )

    assert edge.suggestion is not None
    assert edge.suggestion.source_fragments == (fragment_ref,)


def test_model_suggestion_rejects_missing_source_fragments() -> None:
    with pytest.raises(ValueError, match="source dream fragment"):
        ModelSuggestionProvenance(model_name="test-model", source_fragments=())


def test_fragment_reference_rejects_unlocatable_source() -> None:
    with pytest.raises(ValueError, match="chunk_id, fragment_index, or offsets"):
        SourceDreamFragmentRef(dream_id="dream-1")


def test_fragment_reference_rejects_malformed_locators() -> None:
    with pytest.raises(ValueError, match="chunk_id must be non-empty"):
        SourceDreamFragmentRef(dream_id="dream-1", chunk_id="")

    with pytest.raises(ValueError, match="index must be non-negative"):
        SourceDreamFragmentRef(dream_id="dream-1", fragment_index=-1)

    with pytest.raises(ValueError, match="both start_char and end_char"):
        SourceDreamFragmentRef(dream_id="dream-1", start_char=10)

    with pytest.raises(ValueError, match="positive range"):
        SourceDreamFragmentRef(dream_id="dream-1", start_char=10, end_char=2)


def test_user_confirmation_status_is_separate_from_model_suggestion() -> None:
    fragment_ref = SourceDreamFragmentRef(dream_id="dream-1", fragment_index=2)
    suggestion = ModelSuggestionProvenance(
        model_name="test-model",
        source_fragments=(fragment_ref,),
    )

    confirmed_model_edge = GraphEdge(
        id="edge:stairs:dream-1",
        edge_type=GraphEdgeType.APPEARS_IN,
        source_node_id="motif:stairs",
        target_node_id="dream:1",
        confirmation_status=GraphConfirmationStatus.CONFIRMED,
        suggestion=suggestion,
    )
    user_asserted_edge = GraphEdge(
        id="edge:user-confirmed:1",
        edge_type=GraphEdgeType.USER_CONFIRMED,
        source_node_id="person:friend",
        target_node_id="dream:1",
        confirmation_status=GraphConfirmationStatus.CONFIRMED,
        suggestion=None,
    )

    assert confirmed_model_edge.confirmation_status is GraphConfirmationStatus.CONFIRMED
    assert confirmed_model_edge.suggestion == suggestion
    assert user_asserted_edge.confirmation_status is GraphConfirmationStatus.CONFIRMED
    assert user_asserted_edge.suggestion is None
