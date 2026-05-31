from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from app.models.dream_graph import GraphEdge, GraphNode, ModelSuggestionProvenance

PROOF_RECEIPT_SCHEMA_VERSION = "entropy_core.product_receipt.v1"
PRODUCT_ID = "dream-motif-interpreter"


@dataclass(frozen=True)
class DreamProofEvidenceRef:
    ref_id: str
    ref_type: Literal["dream_fragment", "graph_node", "graph_edge"]
    supports: str
    checksum_sha256: str


@dataclass(frozen=True)
class DreamMemoryActionReceipt:
    type: Literal["dream_memory_action_receipt"]
    schema_version: Literal["entropy_core.product_receipt.v1"]
    product_id: Literal["dream-motif-interpreter"]
    action: Literal["node_suggested", "edge_suggested", "node_confirmed", "edge_confirmed"]
    subject_id: str
    verifier_status: Literal["passed", "needs_review", "failed"]
    evidence_refs: tuple[DreamProofEvidenceRef, ...]
    generated_at: datetime
    entropy_core_level: Literal["receipt_compatible"]

    def canonical_json(self) -> str:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def receipt_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_node_memory_receipt(
    *,
    node: GraphNode,
    action: Literal["node_suggested", "node_confirmed"],
    generated_at: datetime | None = None,
) -> DreamMemoryActionReceipt:
    return DreamMemoryActionReceipt(
        type="dream_memory_action_receipt",
        schema_version=PROOF_RECEIPT_SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        action=action,
        subject_id=node.id,
        verifier_status="passed",
        evidence_refs=(
            DreamProofEvidenceRef(
                ref_id=f"graph_node:{node.id}",
                ref_type="graph_node",
                supports=action,
                checksum_sha256=_hash_text(f"{node.node_type}:{node.label}:{node.hidden}"),
            ),
        ),
        generated_at=generated_at or datetime.now(UTC),
        entropy_core_level="receipt_compatible",
    )


def build_edge_memory_receipt(
    *,
    edge: GraphEdge,
    action: Literal["edge_suggested", "edge_confirmed"],
    generated_at: datetime | None = None,
) -> DreamMemoryActionReceipt:
    evidence_refs = [
        DreamProofEvidenceRef(
            ref_id=f"graph_edge:{edge.id}",
            ref_type="graph_edge",
            supports=action,
            checksum_sha256=_hash_text(
                f"{edge.edge_type}:{edge.source_node_id}:{edge.target_node_id}:{edge.hidden}"
            ),
        )
    ]
    if edge.suggestion is not None:
        evidence_refs.extend(_suggestion_refs(edge.suggestion))
    verifier_status: Literal["passed", "needs_review", "failed"] = (
        "passed" if action == "edge_confirmed" or edge.suggestion is not None else "needs_review"
    )
    return DreamMemoryActionReceipt(
        type="dream_memory_action_receipt",
        schema_version=PROOF_RECEIPT_SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        action=action,
        subject_id=edge.id,
        verifier_status=verifier_status,
        evidence_refs=tuple(evidence_refs),
        generated_at=generated_at or datetime.now(UTC),
        entropy_core_level="receipt_compatible",
    )


def _suggestion_refs(
    suggestion: ModelSuggestionProvenance,
) -> tuple[DreamProofEvidenceRef, ...]:
    refs: list[DreamProofEvidenceRef] = []
    for fragment in suggestion.source_fragments:
        locator = (
            fragment.chunk_id
            or (
                f"fragment:{fragment.fragment_index}"
                if fragment.fragment_index is not None
                else f"offsets:{fragment.start_char}-{fragment.end_char}"
            )
        )
        ref_id = f"dream_fragment:{fragment.dream_id}:{locator}"
        refs.append(
            DreamProofEvidenceRef(
                ref_id=ref_id,
                ref_type="dream_fragment",
                supports=suggestion.model_name,
                checksum_sha256=_hash_text(ref_id),
            )
        )
    return tuple(refs)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
