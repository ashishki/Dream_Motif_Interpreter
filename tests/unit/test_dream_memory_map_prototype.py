from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = REPO_ROOT / "docs" / "mockups" / "dream_memory_map_prototype.html"


def _read_prototype() -> str:
    return PROTOTYPE.read_text(encoding="utf-8")


def _prototype_data() -> dict[str, Any]:
    text = _read_prototype()
    match = re.search(
        r'<script type="application/json" id="dream-memory-map-prototype-data">\s*(.*?)\s*</script>',
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def test_prototype_shows_dream_nodes_motif_nodes_and_edges_in_one_graph() -> None:
    text = _read_prototype()
    data = _prototype_data()

    node_types = {node["type"] for node in data["nodes"]}
    edge_types = {edge["type"] for edge in data["edges"]}

    assert "Graph view with dream nodes, motif nodes, and edges" in text
    assert {"Dream", "Motif"}.issubset(node_types)
    assert {"appears_in", "repeats_with", "evolves_from", "user_confirmed"}.issubset(edge_types)
    assert all(edge["source"] and edge["target"] for edge in data["edges"])


def test_prototype_can_open_a_motif_and_show_linked_dreams_and_fragments() -> None:
    text = _read_prototype()
    data = _prototype_data()

    assert "function openMotif" in text
    assert 'data-node-type": node.type' in text
    assert "motif-tabs" in text
    assert "Linked dreams" in text
    assert "Evidence fragments" in text

    motif_nodes = {node["id"] for node in data["nodes"] if node["type"] == "Motif"}
    detail_motifs = {motif["id"] for motif in data["motifs"]}
    assert detail_motifs == motif_nodes

    for motif in data["motifs"]:
        assert motif["linkedDreams"]
        assert motif["fragments"]
        assert all(dream["fragmentIds"] for dream in motif["linkedDreams"])
        assert all(fragment["label"] == "source fragment" for fragment in motif["fragments"])


def test_prototype_labels_ai_suggestions_and_user_confirmed_links_distinctly() -> None:
    text = _read_prototype()
    data = _prototype_data()

    assert "AI suggestion" in text
    assert "confirmed by user" in text
    assert "not diagnosis" in text
    assert "diagnostic" not in text.lower()

    edge_states = {edge["state"] for edge in data["edges"]}
    edge_labels = {edge["label"] for edge in data["edges"]}
    fragment_states = {
        fragment["state"] for motif in data["motifs"] for fragment in motif["fragments"]
    }

    assert {"suggested", "confirmed"}.issubset(edge_states)
    assert any(label.startswith("AI suggestion") for label in edge_labels)
    assert "confirmed by user" in edge_labels
    assert {"AI suggestion", "confirmed by user"}.issubset(fragment_states)
