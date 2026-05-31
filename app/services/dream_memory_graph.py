from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from app.models.dream import DreamEntry
from app.models.dream_graph import (
    GraphConfirmationStatus,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    ModelSuggestionProvenance,
    SourceDreamFragmentRef,
)
from app.models.dream_graph_privacy import DreamGraphSnapshot, SourceDreamExportRef
from app.models.motif import MotifInduction


def build_dream_memory_snapshot(
    *,
    dreams: Iterable[DreamEntry],
    motifs: Iterable[MotifInduction],
) -> DreamGraphSnapshot:
    dream_items = list(dreams)
    motif_items = list(motifs)
    source_dreams = tuple(dream_to_source_ref(dream) for dream in dream_items)
    dream_nodes = tuple(dream_to_graph_node(dream) for dream in dream_items)
    dream_node_ids = {node.id for node in dream_nodes}
    motif_nodes = tuple(motif_to_graph_node(motif) for motif in motif_items)
    motif_edges = tuple(
        edge
        for motif in motif_items
        if (edge := motif_to_dream_edge(motif)).target_node_id in dream_node_ids
    )

    return DreamGraphSnapshot(
        source_dreams=source_dreams,
        nodes=dream_nodes + motif_nodes,
        edges=motif_edges,
    )


def dream_to_source_ref(dream: DreamEntry) -> SourceDreamExportRef:
    dream_id = str(dream.id)
    return SourceDreamExportRef(
        dream_id=dream_id,
        graph_node_id=dream_node_id(dream.id),
        source_ref=f"archive:{dream_id}",
    )


def dream_to_graph_node(dream: DreamEntry) -> GraphNode:
    return GraphNode(
        id=dream_node_id(dream.id),
        node_type=GraphNodeType.DREAM,
        label=f"dream:{dream.id}",
        confirmation_status=GraphConfirmationStatus.CONFIRMED,
    )


def motif_to_graph_node(motif: MotifInduction) -> GraphNode:
    return GraphNode(
        id=motif_node_id(motif.id),
        node_type=GraphNodeType.MOTIF,
        label=motif.label,
        confirmation_status=_motif_confirmation_status(motif.status),
    )


def motif_to_dream_edge(motif: MotifInduction) -> GraphEdge:
    return GraphEdge(
        id=motif_dream_edge_id(motif.id, motif.dream_id),
        edge_type=GraphEdgeType.APPEARS_IN,
        source_node_id=motif_node_id(motif.id),
        target_node_id=dream_node_id(motif.dream_id),
        confirmation_status=_motif_confirmation_status(motif.status),
        suggestion=motif_suggestion_provenance(motif),
    )


def motif_suggestion_provenance(motif: MotifInduction) -> ModelSuggestionProvenance | None:
    source_fragments = source_fragment_refs(
        dream_id=str(motif.dream_id),
        fragments=motif.fragments if isinstance(motif.fragments, list) else [],
    )
    if not source_fragments:
        return None
    return ModelSuggestionProvenance(
        model_name="motif-induction",
        model_version=getattr(motif, "model_version", None),
        confidence=getattr(motif, "confidence", None),
        source_fragments=source_fragments,
    )


def source_fragment_refs(
    *,
    dream_id: str,
    fragments: list[dict[str, Any]],
) -> tuple[SourceDreamFragmentRef, ...]:
    refs: list[SourceDreamFragmentRef] = []
    for index, fragment in enumerate(fragments):
        if not isinstance(fragment, dict):
            continue
        chunk_id = _optional_non_empty_string(fragment.get("chunk_id"))
        start_char = _optional_int(fragment.get("start_char", fragment.get("start_offset")))
        end_char = _optional_int(fragment.get("end_char", fragment.get("end_offset")))

        try:
            if chunk_id is not None:
                refs.append(SourceDreamFragmentRef(dream_id=dream_id, chunk_id=chunk_id))
            elif start_char is not None and end_char is not None:
                refs.append(
                    SourceDreamFragmentRef(
                        dream_id=dream_id,
                        start_char=start_char,
                        end_char=end_char,
                    )
                )
            else:
                refs.append(SourceDreamFragmentRef(dream_id=dream_id, fragment_index=index))
        except ValueError:
            continue
    return tuple(refs)


def motif_node_id(motif_id: uuid.UUID) -> str:
    return f"motif_induction:{motif_id}"


def dream_node_id(dream_id: uuid.UUID) -> str:
    return f"dream:{dream_id}"


def motif_dream_edge_id(motif_id: uuid.UUID, dream_id: uuid.UUID) -> str:
    return f"edge:motif_induction:{motif_id}:appears_in:dream:{dream_id}"


def _motif_confirmation_status(status: str) -> GraphConfirmationStatus:
    if status == "confirmed":
        return GraphConfirmationStatus.CONFIRMED
    if status == "rejected":
        return GraphConfirmationStatus.REJECTED
    return GraphConfirmationStatus.UNREVIEWED


def _optional_non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None
