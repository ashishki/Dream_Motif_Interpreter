from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from app.models.dream_graph import (
    GraphConfirmationStatus,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    SourceDreamFragmentRef,
)


EXPORT_FORMAT = "dream-memory-graph-export.v1"


class DreamGraphExportScope(str, Enum):
    NORMAL_GRAPH_OUTPUT = "normal_graph_output"
    ALL_WITH_CONTROLS = "all_with_controls"
    CONFIRMED_ONLY = "confirmed_only"


class RejectedSuggestionSubject(str, Enum):
    NODE = "node"
    EDGE = "edge"


@dataclass(frozen=True)
class SourceDreamExportRef:
    dream_id: str
    graph_node_id: str | None = None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.dream_id:
            raise ValueError("source dream export references require dream_id")
        if self.graph_node_id == "":
            raise ValueError("source dream graph_node_id must be non-empty")
        if self.source_ref == "":
            raise ValueError("source dream source_ref must be non-empty")


@dataclass(frozen=True)
class RejectedGraphSuggestion:
    subject_type: RejectedSuggestionSubject
    subject_id: str
    source_fragments: tuple[SourceDreamFragmentRef, ...]

    def __post_init__(self) -> None:
        if not self.subject_id:
            raise ValueError("rejected graph suggestions require subject_id")
        if not self.source_fragments:
            raise ValueError("rejected graph suggestions require source fragment references")


@dataclass(frozen=True)
class DreamGraphPrivacyControls:
    hidden_dream_ids: frozenset[str] = frozenset()
    deleted_dream_ids: frozenset[str] = frozenset()
    hidden_node_ids: frozenset[str] = frozenset()
    deleted_node_ids: frozenset[str] = frozenset()
    hidden_edge_ids: frozenset[str] = frozenset()
    deleted_edge_ids: frozenset[str] = frozenset()
    rejected_node_ids: frozenset[str] = frozenset()
    rejected_edge_ids: frozenset[str] = frozenset()
    rejected_suggestions: tuple[RejectedGraphSuggestion, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "hidden_dream_ids",
            "deleted_dream_ids",
            "hidden_node_ids",
            "deleted_node_ids",
            "hidden_edge_ids",
            "deleted_edge_ids",
            "rejected_node_ids",
            "rejected_edge_ids",
        ):
            values = getattr(self, field_name)
            if any(not value for value in values):
                raise ValueError(f"{field_name} cannot contain empty ids")

        _reject_overlapping_controls(
            self.hidden_dream_ids,
            self.deleted_dream_ids,
            "dream",
        )
        _reject_overlapping_controls(
            self.hidden_node_ids,
            self.deleted_node_ids | self.rejected_node_ids,
            "node",
        )
        _reject_overlapping_controls(
            self.deleted_node_ids,
            self.rejected_node_ids,
            "node",
        )
        _reject_overlapping_controls(
            self.hidden_edge_ids,
            self.deleted_edge_ids | self.rejected_edge_ids,
            "edge",
        )
        _reject_overlapping_controls(
            self.deleted_edge_ids,
            self.rejected_edge_ids,
            "edge",
        )

        rejected_node_ids = {
            item.subject_id
            for item in self.rejected_suggestions
            if item.subject_type is RejectedSuggestionSubject.NODE
        }
        rejected_edge_ids = {
            item.subject_id
            for item in self.rejected_suggestions
            if item.subject_type is RejectedSuggestionSubject.EDGE
        }
        if not rejected_node_ids.issubset(self.rejected_node_ids):
            raise ValueError("rejected node suggestions must be represented in rejected_node_ids")
        if not rejected_edge_ids.issubset(self.rejected_edge_ids):
            raise ValueError("rejected edge suggestions must be represented in rejected_edge_ids")

    def hide_dream(self, dream_id: str) -> DreamGraphPrivacyControls:
        return replace(self, hidden_dream_ids=self.hidden_dream_ids | _one_id(dream_id))

    def delete_dream(self, dream_id: str) -> DreamGraphPrivacyControls:
        return replace(self, deleted_dream_ids=self.deleted_dream_ids | _one_id(dream_id))

    def hide_node(self, node_id: str) -> DreamGraphPrivacyControls:
        return replace(self, hidden_node_ids=self.hidden_node_ids | _one_id(node_id))

    def delete_node(self, node_id: str) -> DreamGraphPrivacyControls:
        return replace(self, deleted_node_ids=self.deleted_node_ids | _one_id(node_id))

    def hide_edge(self, edge_id: str) -> DreamGraphPrivacyControls:
        return replace(self, hidden_edge_ids=self.hidden_edge_ids | _one_id(edge_id))

    def delete_edge(self, edge_id: str) -> DreamGraphPrivacyControls:
        return replace(self, deleted_edge_ids=self.deleted_edge_ids | _one_id(edge_id))

    def reject_ai_suggested_node(
        self,
        node: GraphNode,
        source_fragments: tuple[SourceDreamFragmentRef, ...],
    ) -> DreamGraphPrivacyControls:
        rejected = RejectedGraphSuggestion(
            subject_type=RejectedSuggestionSubject.NODE,
            subject_id=node.id,
            source_fragments=source_fragments,
        )
        return replace(
            self,
            rejected_node_ids=self.rejected_node_ids | {node.id},
            rejected_suggestions=self.rejected_suggestions + (rejected,),
        )

    def reject_ai_suggested_edge(self, edge: GraphEdge) -> DreamGraphPrivacyControls:
        if edge.suggestion is None:
            raise ValueError("only model-suggested edges can be rejected as AI suggestions")

        rejected = RejectedGraphSuggestion(
            subject_type=RejectedSuggestionSubject.EDGE,
            subject_id=edge.id,
            source_fragments=edge.suggestion.source_fragments,
        )
        return replace(
            self,
            rejected_edge_ids=self.rejected_edge_ids | {edge.id},
            rejected_suggestions=self.rejected_suggestions + (rejected,),
        )


@dataclass(frozen=True)
class DreamGraphSnapshot:
    source_dreams: tuple[SourceDreamExportRef, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    privacy_controls: DreamGraphPrivacyControls = field(default_factory=DreamGraphPrivacyControls)

    def __post_init__(self) -> None:
        dream_ids = [dream.dream_id for dream in self.source_dreams]
        if len(dream_ids) != len(set(dream_ids)):
            raise ValueError("source dream export references must be unique by dream_id")

        graph_node_ids = [
            dream.graph_node_id for dream in self.source_dreams if dream.graph_node_id is not None
        ]
        if len(graph_node_ids) != len(set(graph_node_ids)):
            raise ValueError("source dream export references must be unique by graph_node_id")

        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("graph nodes must be unique by id")

        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("graph edges must be unique by id")


@dataclass(frozen=True)
class DreamGraphExportOptions:
    scope: DreamGraphExportScope = DreamGraphExportScope.NORMAL_GRAPH_OUTPUT


def normal_graph_output(snapshot: DreamGraphSnapshot) -> DreamGraphSnapshot:
    return filtered_graph_snapshot(
        snapshot,
        DreamGraphExportOptions(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT),
    )


def filtered_graph_snapshot(
    snapshot: DreamGraphSnapshot,
    options: DreamGraphExportOptions | None = None,
) -> DreamGraphSnapshot:
    options = options or DreamGraphExportOptions()

    if options.scope is DreamGraphExportScope.ALL_WITH_CONTROLS:
        return DreamGraphSnapshot(
            source_dreams=tuple(sorted(snapshot.source_dreams, key=lambda dream: dream.dream_id)),
            nodes=tuple(sorted(snapshot.nodes, key=lambda node: node.id)),
            edges=tuple(sorted(snapshot.edges, key=lambda edge: edge.id)),
            privacy_controls=snapshot.privacy_controls,
        )

    controls = snapshot.privacy_controls
    visible_source_dreams = tuple(
        dream
        for dream in snapshot.source_dreams
        if dream.dream_id not in controls.hidden_dream_ids | controls.deleted_dream_ids
    )
    visible_dream_ids = {dream.dream_id for dream in visible_source_dreams}

    visible_nodes = tuple(
        node
        for node in snapshot.nodes
        if _node_is_visible(node, controls, visible_dream_ids, snapshot.source_dreams)
    )
    visible_node_ids = {node.id for node in visible_nodes}

    visible_edges = tuple(
        edge
        for edge in snapshot.edges
        if _edge_is_visible(edge, controls, visible_node_ids, visible_dream_ids)
    )

    if options.scope is DreamGraphExportScope.CONFIRMED_ONLY:
        visible_nodes = tuple(
            node
            for node in visible_nodes
            if node.confirmation_status is GraphConfirmationStatus.CONFIRMED
        )
        visible_node_ids = {node.id for node in visible_nodes}
        visible_edges = tuple(
            edge
            for edge in visible_edges
            if edge.confirmation_status is GraphConfirmationStatus.CONFIRMED
            and edge.source_node_id in visible_node_ids
            and edge.target_node_id in visible_node_ids
        )

    return DreamGraphSnapshot(
        source_dreams=tuple(sorted(visible_source_dreams, key=lambda dream: dream.dream_id)),
        nodes=tuple(sorted(visible_nodes, key=lambda node: node.id)),
        edges=tuple(sorted(visible_edges, key=lambda edge: edge.id)),
        privacy_controls=controls,
    )


def export_dream_graph(
    snapshot: DreamGraphSnapshot,
    options: DreamGraphExportOptions | None = None,
) -> dict[str, Any]:
    options = options or DreamGraphExportOptions()
    export_snapshot = filtered_graph_snapshot(snapshot, options)

    return {
        "format": EXPORT_FORMAT,
        "scope": options.scope.value,
        "options": {
            "default_excludes_hidden_rejected_deleted": (
                options.scope is not DreamGraphExportScope.ALL_WITH_CONTROLS
            ),
        },
        "source_dreams": [_source_dream_to_dict(dream) for dream in export_snapshot.source_dreams],
        "nodes": [_node_to_dict(node) for node in export_snapshot.nodes],
        "edges": [_edge_to_dict(edge) for edge in export_snapshot.edges],
        "privacy_controls": _privacy_controls_to_dict(snapshot.privacy_controls),
    }


def _node_is_visible(
    node: GraphNode,
    controls: DreamGraphPrivacyControls,
    visible_dream_ids: set[str],
    source_dreams: tuple[SourceDreamExportRef, ...],
) -> bool:
    if node.hidden or node.confirmation_status in {
        GraphConfirmationStatus.HIDDEN,
        GraphConfirmationStatus.REJECTED,
    }:
        return False
    if node.id in controls.hidden_node_ids | controls.deleted_node_ids | controls.rejected_node_ids:
        return False
    if node.node_type is GraphNodeType.DREAM:
        dream_refs = {
            dream.graph_node_id: dream.dream_id
            for dream in source_dreams
            if dream.graph_node_id is not None
        }
        dream_id = dream_refs.get(node.id, node.id)
        return dream_id in visible_dream_ids
    return True


def _edge_is_visible(
    edge: GraphEdge,
    controls: DreamGraphPrivacyControls,
    visible_node_ids: set[str],
    visible_dream_ids: set[str],
) -> bool:
    if edge.hidden or edge.confirmation_status in {
        GraphConfirmationStatus.HIDDEN,
        GraphConfirmationStatus.REJECTED,
    }:
        return False
    if edge.id in controls.hidden_edge_ids | controls.deleted_edge_ids | controls.rejected_edge_ids:
        return False
    if edge.source_node_id not in visible_node_ids or edge.target_node_id not in visible_node_ids:
        return False
    if edge.suggestion is None:
        return True
    return all(
        fragment.dream_id in visible_dream_ids for fragment in edge.suggestion.source_fragments
    )


def _source_dream_to_dict(dream: SourceDreamExportRef) -> dict[str, Any]:
    return {
        "dream_id": dream.dream_id,
        "graph_node_id": dream.graph_node_id,
        "source_ref": dream.source_ref,
    }


def _node_to_dict(node: GraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "type": node.node_type.value,
        "label": node.label,
        "confirmation_status": node.confirmation_status.value,
        "hidden": node.hidden,
    }


def _edge_to_dict(edge: GraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "type": edge.edge_type.value,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "confirmation_status": edge.confirmation_status.value,
        "hidden": edge.hidden,
        "suggestion": _suggestion_to_dict(edge),
    }


def _suggestion_to_dict(edge: GraphEdge) -> dict[str, Any] | None:
    if edge.suggestion is None:
        return None
    return {
        "model_name": edge.suggestion.model_name,
        "model_version": edge.suggestion.model_version,
        "confidence": edge.suggestion.confidence,
        "source_fragments": [
            _fragment_ref_to_dict(fragment)
            for fragment in sorted(
                edge.suggestion.source_fragments,
                key=lambda fragment: (
                    fragment.dream_id,
                    fragment.chunk_id or "",
                    fragment.fragment_index if fragment.fragment_index is not None else -1,
                    fragment.start_char if fragment.start_char is not None else -1,
                    fragment.end_char if fragment.end_char is not None else -1,
                ),
            )
        ],
    }


def _privacy_controls_to_dict(controls: DreamGraphPrivacyControls) -> dict[str, Any]:
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
                    _fragment_ref_to_dict(fragment) for fragment in suggestion.source_fragments
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


def _fragment_ref_to_dict(fragment: SourceDreamFragmentRef) -> dict[str, Any]:
    return {
        "dream_id": fragment.dream_id,
        "chunk_id": fragment.chunk_id,
        "fragment_index": fragment.fragment_index,
        "start_char": fragment.start_char,
        "end_char": fragment.end_char,
    }


def _one_id(value: str) -> frozenset[str]:
    if not value:
        raise ValueError("privacy control ids must be non-empty")
    return frozenset((value,))


def _reject_overlapping_controls(
    first: frozenset[str],
    second: frozenset[str],
    subject_name: str,
) -> None:
    if first & second:
        raise ValueError(f"{subject_name} privacy controls must not overlap")
