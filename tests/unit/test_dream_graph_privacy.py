from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.dream_graph import (
    GraphConfirmationStatus,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    ModelSuggestionProvenance,
    SourceDreamFragmentRef,
)
from app.models.dream_graph_privacy import (
    DreamGraphExportOptions,
    DreamGraphExportScope,
    DreamGraphPrivacyControls,
    DreamGraphSnapshot,
    SourceDreamExportRef,
    export_dream_graph,
    normal_graph_output,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DREAM_MEMORY_MAP = REPO_ROOT / "docs" / "DREAM_MEMORY_MAP.md"


def test_privacy_export_contract_is_documented() -> None:
    text = DREAM_MEMORY_MAP.read_text(encoding="utf-8")
    flat_text = " ".join(text.split())

    assert "dream-memory-graph-export.v1" in text
    assert "`normal_graph_output`" in text
    assert "`all_with_controls`" in text
    assert "`confirmed_only`" in text
    assert "Rejection never deletes the source dream reference" in flat_text


def test_export_dream_graph_uses_documented_deterministic_format() -> None:
    snapshot = _sample_snapshot()

    first_export = export_dream_graph(snapshot)
    second_export = export_dream_graph(snapshot)

    assert first_export == second_export
    assert json.dumps(first_export, sort_keys=True)
    assert first_export["format"] == "dream-memory-graph-export.v1"
    assert first_export["scope"] == "normal_graph_output"
    assert first_export["options"] == {
        "default_excludes_hidden_rejected_deleted": True,
    }
    assert first_export["source_dreams"] == [
        {
            "dream_id": "dream-1",
            "graph_node_id": "dream:dream-1",
            "source_ref": "archive:dream-1",
        },
        {
            "dream_id": "dream-2",
            "graph_node_id": "dream:dream-2",
            "source_ref": "archive:dream-2",
        },
    ]
    assert first_export["nodes"][0] == {
        "id": "dream:dream-1",
        "type": "Dream",
        "label": "dream reference 1",
        "confirmation_status": "confirmed",
        "hidden": False,
    }
    stairs_edge = next(
        edge for edge in first_export["edges"] if edge["id"] == "edge:stairs:dream-1"
    )
    assert stairs_edge["suggestion"] == {
        "model_name": "test-model",
        "model_version": "v1",
        "confidence": "moderate",
        "source_fragments": [
            {
                "dream_id": "dream-1",
                "chunk_id": "chunk-1",
                "fragment_index": None,
                "start_char": None,
                "end_char": None,
            }
        ],
    }
    assert first_export["privacy_controls"]["hidden_dream_ids"] == []
    assert first_export["privacy_controls"]["rejected_suggestions"] == []


def test_hidden_or_deleted_dream_and_motif_are_removed_from_normal_graph_output() -> None:
    snapshot = _sample_snapshot()
    controls = DreamGraphPrivacyControls().hide_dream("dream-2").delete_node("motif:hidden-forest")
    controlled_snapshot = DreamGraphSnapshot(
        source_dreams=snapshot.source_dreams,
        nodes=snapshot.nodes,
        edges=snapshot.edges,
        privacy_controls=controls,
    )

    graph_output = normal_graph_output(controlled_snapshot)
    export = export_dream_graph(controlled_snapshot)

    assert {dream.dream_id for dream in graph_output.source_dreams} == {"dream-1"}
    assert {node.id for node in graph_output.nodes} == {
        "dream:dream-1",
        "motif:stairs",
    }
    assert {edge.id for edge in graph_output.edges} == {"edge:stairs:dream-1"}
    assert export["privacy_controls"]["hidden_dream_ids"] == ["dream-2"]
    assert export["privacy_controls"]["deleted_node_ids"] == ["motif:hidden-forest"]


def test_rejecting_ai_suggested_edge_keeps_source_dream_reference() -> None:
    snapshot = _sample_snapshot()
    suggested_edge = next(edge for edge in snapshot.edges if edge.id == "edge:stairs:dream-1")
    controls = DreamGraphPrivacyControls().reject_ai_suggested_edge(suggested_edge)
    controlled_snapshot = DreamGraphSnapshot(
        source_dreams=snapshot.source_dreams,
        nodes=snapshot.nodes,
        edges=snapshot.edges,
        privacy_controls=controls,
    )

    graph_output = normal_graph_output(controlled_snapshot)
    export = export_dream_graph(controlled_snapshot)

    assert {dream.dream_id for dream in graph_output.source_dreams} == {
        "dream-1",
        "dream-2",
    }
    assert "edge:stairs:dream-1" not in {edge.id for edge in graph_output.edges}
    assert export["privacy_controls"]["deleted_dream_ids"] == []
    assert export["privacy_controls"]["rejected_edge_ids"] == ["edge:stairs:dream-1"]
    assert export["privacy_controls"]["rejected_suggestions"] == [
        {
            "subject_type": "edge",
            "subject_id": "edge:stairs:dream-1",
            "source_fragments": [
                {
                    "dream_id": "dream-1",
                    "chunk_id": "chunk-1",
                    "fragment_index": None,
                    "start_char": None,
                    "end_char": None,
                }
            ],
        }
    ]


def test_rejecting_non_model_edge_is_invalid() -> None:
    edge = GraphEdge(
        id="edge:user-confirmed:1",
        edge_type=GraphEdgeType.USER_CONFIRMED,
        source_node_id="motif:stairs",
        target_node_id="dream:dream-1",
        confirmation_status=GraphConfirmationStatus.CONFIRMED,
    )

    with pytest.raises(ValueError, match="model-suggested"):
        DreamGraphPrivacyControls().reject_ai_suggested_edge(edge)


def test_overlapping_hidden_deleted_or_rejected_controls_are_invalid() -> None:
    with pytest.raises(ValueError, match="dream privacy controls must not overlap"):
        DreamGraphPrivacyControls(
            hidden_dream_ids=frozenset({"dream-1"}),
            deleted_dream_ids=frozenset({"dream-1"}),
        )

    with pytest.raises(ValueError, match="edge privacy controls must not overlap"):
        DreamGraphPrivacyControls(
            deleted_edge_ids=frozenset({"edge:1"}),
            rejected_edge_ids=frozenset({"edge:1"}),
        )


def test_confirmed_only_export_excludes_unconfirmed_suggestions() -> None:
    snapshot = _sample_snapshot()

    export = export_dream_graph(
        snapshot,
        DreamGraphExportOptions(scope=DreamGraphExportScope.CONFIRMED_ONLY),
    )

    assert export["scope"] == "confirmed_only"
    assert export["options"] == {
        "default_excludes_hidden_rejected_deleted": True,
    }
    assert {node["id"] for node in export["nodes"]} == {
        "dream:dream-1",
        "dream:dream-2",
    }
    assert export["edges"] == []


def test_all_with_controls_export_is_sorted_for_deterministic_output() -> None:
    snapshot = _sample_snapshot()
    reversed_snapshot = DreamGraphSnapshot(
        source_dreams=tuple(reversed(snapshot.source_dreams)),
        nodes=tuple(reversed(snapshot.nodes)),
        edges=tuple(reversed(snapshot.edges)),
    )

    export = export_dream_graph(
        reversed_snapshot,
        DreamGraphExportOptions(scope=DreamGraphExportScope.ALL_WITH_CONTROLS),
    )

    assert export["options"] == {
        "default_excludes_hidden_rejected_deleted": False,
    }
    assert [dream["dream_id"] for dream in export["source_dreams"]] == [
        "dream-1",
        "dream-2",
    ]
    assert [node["id"] for node in export["nodes"]] == [
        "dream:dream-1",
        "dream:dream-2",
        "motif:hidden-forest",
        "motif:stairs",
    ]
    assert [edge["id"] for edge in export["edges"]] == [
        "edge:forest:dream-2",
        "edge:stairs:dream-1",
    ]


def test_duplicate_source_dream_graph_node_refs_are_invalid() -> None:
    snapshot = _sample_snapshot()

    with pytest.raises(ValueError, match="unique by graph_node_id"):
        DreamGraphSnapshot(
            source_dreams=(
                SourceDreamExportRef(
                    dream_id="dream-1",
                    graph_node_id="dream:shared",
                ),
                SourceDreamExportRef(
                    dream_id="dream-2",
                    graph_node_id="dream:shared",
                ),
            ),
            nodes=snapshot.nodes,
            edges=snapshot.edges,
        )


def _sample_snapshot() -> DreamGraphSnapshot:
    fragment_ref = SourceDreamFragmentRef(dream_id="dream-1", chunk_id="chunk-1")
    suggestion = ModelSuggestionProvenance(
        model_name="test-model",
        model_version="v1",
        confidence="moderate",
        source_fragments=(fragment_ref,),
    )
    nodes = (
        GraphNode(
            id="dream:dream-1",
            node_type=GraphNodeType.DREAM,
            label="dream reference 1",
            confirmation_status=GraphConfirmationStatus.CONFIRMED,
        ),
        GraphNode(
            id="dream:dream-2",
            node_type=GraphNodeType.DREAM,
            label="dream reference 2",
            confirmation_status=GraphConfirmationStatus.CONFIRMED,
        ),
        GraphNode(
            id="motif:hidden-forest",
            node_type=GraphNodeType.MOTIF,
            label="hidden forest",
        ),
        GraphNode(
            id="motif:stairs",
            node_type=GraphNodeType.MOTIF,
            label="stairs",
        ),
    )
    edges = (
        GraphEdge(
            id="edge:forest:dream-2",
            edge_type=GraphEdgeType.APPEARS_IN,
            source_node_id="motif:hidden-forest",
            target_node_id="dream:dream-2",
            suggestion=ModelSuggestionProvenance(
                model_name="test-model",
                source_fragments=(SourceDreamFragmentRef(dream_id="dream-2", fragment_index=0),),
            ),
        ),
        GraphEdge(
            id="edge:stairs:dream-1",
            edge_type=GraphEdgeType.APPEARS_IN,
            source_node_id="motif:stairs",
            target_node_id="dream:dream-1",
            suggestion=suggestion,
        ),
    )
    return DreamGraphSnapshot(
        source_dreams=(
            SourceDreamExportRef(
                dream_id="dream-1",
                graph_node_id="dream:dream-1",
                source_ref="archive:dream-1",
            ),
            SourceDreamExportRef(
                dream_id="dream-2",
                graph_node_id="dream:dream-2",
                source_ref="archive:dream-2",
            ),
        ),
        nodes=nodes,
        edges=edges,
    )
