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
from app.services.proof_receipts import (
    build_edge_memory_receipt,
    build_node_memory_receipt,
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
            source_fragments=(
                SourceDreamFragmentRef(dream_id="dream-1", chunk_id="chunk-7"),
            ),
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
    assert "dream_fragment:dream-1:chunk-7" in {
        ref.ref_id for ref in receipt.evidence_refs
    }


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
