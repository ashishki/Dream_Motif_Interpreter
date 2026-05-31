from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Mapping

from app.models.dream_graph import GraphEdge, GraphNode, ModelSuggestionProvenance
from app.models.dream_graph_privacy import DreamGraphPrivacyControls

PROOF_RECEIPT_SCHEMA_VERSION = "entropy_core.product_receipt.v1"
PRODUCT_ID = "dream-motif-interpreter"


@dataclass(frozen=True)
class DreamProofEvidenceRef:
    ref_id: str
    ref_type: Literal[
        "dream_fragment",
        "graph_node",
        "graph_edge",
        "graph_export",
        "privacy_control",
        "source_dream",
    ]
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


@dataclass(frozen=True)
class DreamPrivacyActionReceipt:
    type: Literal["privacy_export_receipt", "deletion_receipt", "privacy_control_receipt"]
    schema_version: Literal["entropy_core.product_receipt.v1"]
    product_id: Literal["dream-motif-interpreter"]
    action: Literal[
        "graph_exported",
        "dream_deleted",
        "node_deleted",
        "edge_deleted",
        "dream_hidden",
        "node_hidden",
        "edge_hidden",
    ]
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


def build_privacy_export_receipt(
    *,
    export_payload: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> DreamPrivacyActionReceipt:
    export_format = str(export_payload.get("format", "unknown"))
    export_scope = str(export_payload.get("scope", "unknown"))
    subject_id = f"graph_export:{export_format}:{export_scope}"
    return DreamPrivacyActionReceipt(
        type="privacy_export_receipt",
        schema_version=PROOF_RECEIPT_SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        action="graph_exported",
        subject_id=subject_id,
        verifier_status="passed" if export_format != "unknown" else "needs_review",
        evidence_refs=(
            DreamProofEvidenceRef(
                ref_id=subject_id,
                ref_type="graph_export",
                supports="graph_exported",
                checksum_sha256=_hash_json(export_payload),
            ),
        ),
        generated_at=generated_at or datetime.now(UTC),
        entropy_core_level="receipt_compatible",
    )


def build_deletion_receipt(
    *,
    subject_id: str,
    subject_type: Literal["dream", "graph_node", "graph_edge"],
    privacy_controls: DreamGraphPrivacyControls,
    generated_at: datetime | None = None,
) -> DreamPrivacyActionReceipt:
    action: Literal["dream_deleted", "node_deleted", "edge_deleted"]
    ref_type: Literal["source_dream", "graph_node", "graph_edge"]
    deleted_ids: frozenset[str]
    if subject_type == "dream":
        action = "dream_deleted"
        ref_type = "source_dream"
        deleted_ids = privacy_controls.deleted_dream_ids
    elif subject_type == "graph_node":
        action = "node_deleted"
        ref_type = "graph_node"
        deleted_ids = privacy_controls.deleted_node_ids
    else:
        action = "edge_deleted"
        ref_type = "graph_edge"
        deleted_ids = privacy_controls.deleted_edge_ids

    verifier_status: Literal["passed", "needs_review", "failed"] = (
        "passed" if subject_id in deleted_ids else "needs_review"
    )
    return DreamPrivacyActionReceipt(
        type="deletion_receipt",
        schema_version=PROOF_RECEIPT_SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        action=action,
        subject_id=subject_id,
        verifier_status=verifier_status,
        evidence_refs=(
            DreamProofEvidenceRef(
                ref_id=f"privacy_control:{subject_type}:{subject_id}",
                ref_type="privacy_control",
                supports=action,
                checksum_sha256=_hash_json(_privacy_controls_payload(privacy_controls)),
            ),
            DreamProofEvidenceRef(
                ref_id=f"{subject_type}:{subject_id}",
                ref_type=ref_type,
                supports=action,
                checksum_sha256=_hash_text(f"{subject_type}:{subject_id}"),
            ),
        ),
        generated_at=generated_at or datetime.now(UTC),
        entropy_core_level="receipt_compatible",
    )


def build_hide_receipt(
    *,
    subject_id: str,
    subject_type: Literal["dream", "graph_node", "graph_edge"],
    privacy_controls: DreamGraphPrivacyControls,
    generated_at: datetime | None = None,
) -> DreamPrivacyActionReceipt:
    action: Literal["dream_hidden", "node_hidden", "edge_hidden"]
    ref_type: Literal["source_dream", "graph_node", "graph_edge"]
    hidden_ids: frozenset[str]
    if subject_type == "dream":
        action = "dream_hidden"
        ref_type = "source_dream"
        hidden_ids = privacy_controls.hidden_dream_ids
    elif subject_type == "graph_node":
        action = "node_hidden"
        ref_type = "graph_node"
        hidden_ids = privacy_controls.hidden_node_ids
    else:
        action = "edge_hidden"
        ref_type = "graph_edge"
        hidden_ids = privacy_controls.hidden_edge_ids

    verifier_status: Literal["passed", "needs_review", "failed"] = (
        "passed" if subject_id in hidden_ids else "needs_review"
    )
    return DreamPrivacyActionReceipt(
        type="privacy_control_receipt",
        schema_version=PROOF_RECEIPT_SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        action=action,
        subject_id=subject_id,
        verifier_status=verifier_status,
        evidence_refs=(
            DreamProofEvidenceRef(
                ref_id=f"privacy_control:{subject_type}:{subject_id}",
                ref_type="privacy_control",
                supports=action,
                checksum_sha256=_hash_json(_privacy_controls_payload(privacy_controls)),
            ),
            DreamProofEvidenceRef(
                ref_id=f"{subject_type}:{subject_id}",
                ref_type=ref_type,
                supports=action,
                checksum_sha256=_hash_text(f"{subject_type}:{subject_id}"),
            ),
        ),
        generated_at=generated_at or datetime.now(UTC),
        entropy_core_level="receipt_compatible",
    )


def _suggestion_refs(
    suggestion: ModelSuggestionProvenance,
) -> tuple[DreamProofEvidenceRef, ...]:
    refs: list[DreamProofEvidenceRef] = []
    for fragment in suggestion.source_fragments:
        locator = fragment.chunk_id or (
            f"fragment:{fragment.fragment_index}"
            if fragment.fragment_index is not None
            else f"offsets:{fragment.start_char}-{fragment.end_char}"
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


def _hash_json(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _privacy_controls_payload(controls: DreamGraphPrivacyControls) -> dict[str, Any]:
    return {
        "hidden_dream_ids": sorted(controls.hidden_dream_ids),
        "deleted_dream_ids": sorted(controls.deleted_dream_ids),
        "hidden_node_ids": sorted(controls.hidden_node_ids),
        "deleted_node_ids": sorted(controls.deleted_node_ids),
        "hidden_edge_ids": sorted(controls.hidden_edge_ids),
        "deleted_edge_ids": sorted(controls.deleted_edge_ids),
        "rejected_node_ids": sorted(controls.rejected_node_ids),
        "rejected_edge_ids": sorted(controls.rejected_edge_ids),
        "rejected_suggestions": [
            {
                "subject_type": suggestion.subject_type.value,
                "subject_id": suggestion.subject_id,
                "source_fragments": [
                    {
                        "dream_id": fragment.dream_id,
                        "chunk_id": fragment.chunk_id,
                        "fragment_index": fragment.fragment_index,
                        "start_char": fragment.start_char,
                        "end_char": fragment.end_char,
                    }
                    for fragment in suggestion.source_fragments
                ],
            }
            for suggestion in sorted(
                controls.rejected_suggestions,
                key=lambda suggestion: (
                    suggestion.subject_type.value,
                    suggestion.subject_id,
                ),
            )
        ],
    }
