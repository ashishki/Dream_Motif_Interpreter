from __future__ import annotations

from datetime import UTC, datetime

from app.models.dream_graph import (
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    ModelSuggestionProvenance,
    SourceDreamFragmentRef,
)
from app.models.dream_graph_privacy import DreamGraphPrivacyControls
from app.services.proof_receipts import (
    build_deletion_receipt,
    build_edge_memory_receipt,
    build_node_memory_receipt,
    build_privacy_export_receipt,
)


def test_node_memory_receipt_records_graph_subject_and_checksum() -> None:
    node = GraphNode(id="motif-fish", node_type=GraphNodeType.MOTIF, label="fish")

    receipt = build_node_memory_receipt(
        node=node,
        action="node_suggested",
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    assert receipt.type == "dream_memory_action_receipt"
    assert receipt.schema_version == "entropy_core.product_receipt.v1"
    assert receipt.product_id == "dream-motif-interpreter"
    assert receipt.subject_id == "motif-fish"
    assert receipt.verifier_status == "passed"
    assert receipt.evidence_refs[0].ref_id == "graph_node:motif-fish"
    assert len(receipt.receipt_sha256()) == 64


def test_edge_memory_receipt_links_model_suggestion_to_dream_fragments() -> None:
    edge = GraphEdge(
        id="edge-1",
        edge_type=GraphEdgeType.APPEARS_IN,
        source_node_id="motif-fish",
        target_node_id="dream-1",
        suggestion=ModelSuggestionProvenance(
            model_name="motif-grounder-v1",
            source_fragments=(SourceDreamFragmentRef(dream_id="dream-1", chunk_id="chunk-7"),),
        ),
    )

    receipt = build_edge_memory_receipt(
        edge=edge,
        action="edge_suggested",
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    assert receipt.verifier_status == "passed"
    assert {ref.ref_type for ref in receipt.evidence_refs} == {
        "graph_edge",
        "dream_fragment",
    }
    assert "dream_fragment:dream-1:chunk-7" in {ref.ref_id for ref in receipt.evidence_refs}


def test_edge_suggestion_without_source_fragment_needs_review() -> None:
    edge = GraphEdge(
        id="edge-1",
        edge_type=GraphEdgeType.REPEATS_WITH,
        source_node_id="motif-fish",
        target_node_id="motif-water",
    )

    receipt = build_edge_memory_receipt(
        edge=edge,
        action="edge_suggested",
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    assert receipt.verifier_status == "needs_review"


def test_privacy_export_receipt_hashes_deterministic_export_payload() -> None:
    export_payload = {
        "scope": "normal_graph_output",
        "format": "dream-memory-graph-export.v1",
        "nodes": [{"id": "motif-fish"}],
        "edges": [],
        "source_dreams": [{"dream_id": "dream-1"}],
        "privacy_controls": {"deleted_dream_ids": []},
    }
    same_payload_different_key_order = {
        "privacy_controls": {"deleted_dream_ids": []},
        "source_dreams": [{"dream_id": "dream-1"}],
        "edges": [],
        "nodes": [{"id": "motif-fish"}],
        "format": "dream-memory-graph-export.v1",
        "scope": "normal_graph_output",
    }

    first_receipt = build_privacy_export_receipt(
        export_payload=export_payload,
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )
    second_receipt = build_privacy_export_receipt(
        export_payload=same_payload_different_key_order,
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    assert first_receipt.type == "privacy_export_receipt"
    assert first_receipt.action == "graph_exported"
    assert (
        first_receipt.subject_id == "graph_export:dream-memory-graph-export.v1:normal_graph_output"
    )
    assert first_receipt.verifier_status == "passed"
    assert first_receipt.evidence_refs[0].ref_type == "graph_export"
    assert first_receipt.receipt_sha256() == second_receipt.receipt_sha256()


def test_deletion_receipt_passes_when_privacy_controls_include_subject() -> None:
    controls = DreamGraphPrivacyControls().delete_dream("dream-1")

    receipt = build_deletion_receipt(
        subject_id="dream-1",
        subject_type="dream",
        privacy_controls=controls,
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    assert receipt.type == "deletion_receipt"
    assert receipt.action == "dream_deleted"
    assert receipt.subject_id == "dream-1"
    assert receipt.verifier_status == "passed"
    assert {ref.ref_type for ref in receipt.evidence_refs} == {
        "privacy_control",
        "source_dream",
    }
    assert len(receipt.receipt_sha256()) == 64


def test_deletion_receipt_needs_review_when_subject_is_not_deleted() -> None:
    controls = DreamGraphPrivacyControls().hide_node("motif-fish")

    receipt = build_deletion_receipt(
        subject_id="motif-fish",
        subject_type="graph_node",
        privacy_controls=controls,
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    assert receipt.action == "node_deleted"
    assert receipt.verifier_status == "needs_review"
