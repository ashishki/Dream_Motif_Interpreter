from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GraphNodeType(str, Enum):
    DREAM = "Dream"
    MOTIF = "Motif"
    PERSON = "Person"
    PLACE = "Place"
    EMOTION = "Emotion"
    EVENT = "Event"


class GraphEdgeType(str, Enum):
    APPEARS_IN = "appears_in"
    REPEATS_WITH = "repeats_with"
    CONTRADICTS = "contradicts"
    EVOLVES_FROM = "evolves_from"
    USER_CONFIRMED = "user_confirmed"


class GraphConfirmationStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    HIDDEN = "hidden"


@dataclass(frozen=True)
class GraphNode:
    id: str
    node_type: GraphNodeType
    label: str
    confirmation_status: GraphConfirmationStatus = GraphConfirmationStatus.UNREVIEWED
    hidden: bool = False


@dataclass(frozen=True)
class SourceDreamFragmentRef:
    dream_id: str
    chunk_id: str | None = None
    fragment_index: int | None = None
    start_char: int | None = None
    end_char: int | None = None

    def __post_init__(self) -> None:
        if not self.dream_id:
            raise ValueError("source fragment references require dream_id")

        has_chunk = self.chunk_id is not None
        has_fragment_index = self.fragment_index is not None
        has_offsets = self.start_char is not None and self.end_char is not None
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("source fragment offsets require both start_char and end_char")
        if not (has_chunk or has_fragment_index or has_offsets):
            raise ValueError(
                "source fragment references require chunk_id, fragment_index, or offsets"
            )

        if has_chunk and not self.chunk_id:
            raise ValueError("source fragment chunk_id must be non-empty")
        if has_fragment_index and self.fragment_index is not None:
            if self.fragment_index < 0:
                raise ValueError("source fragment index must be non-negative")
        if has_offsets and self.start_char is not None and self.end_char is not None:
            if self.start_char < 0 or self.end_char <= self.start_char:
                raise ValueError("source fragment offsets must be a positive range")


@dataclass(frozen=True)
class ModelSuggestionProvenance:
    model_name: str
    source_fragments: tuple[SourceDreamFragmentRef, ...]
    model_version: str | None = None
    confidence: str | None = None

    def __post_init__(self) -> None:
        if not self.model_name:
            raise ValueError("model suggestions require model_name")
        if not self.source_fragments:
            raise ValueError("model suggestions require source dream fragment references")


@dataclass(frozen=True)
class GraphEdge:
    id: str
    edge_type: GraphEdgeType
    source_node_id: str
    target_node_id: str
    confirmation_status: GraphConfirmationStatus = GraphConfirmationStatus.UNREVIEWED
    suggestion: ModelSuggestionProvenance | None = None
    hidden: bool = False


GRAPH_NODE_TYPES: tuple[GraphNodeType, ...] = tuple(GraphNodeType)
GRAPH_EDGE_TYPES: tuple[GraphEdgeType, ...] = tuple(GraphEdgeType)
