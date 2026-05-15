"""Replay Engine: Cross-session topic co-occurrence graph.

Builds a graph where nodes are topic strings and edges connect topics
that appear together in the same session (co-occurrence).  Node
positions come from UMAP embeddings so semantically similar topics
cluster together visually.

Usage::

    backend = SentenceTransformerBackend()
    async with ConversationsDB() as db:
        nodes, edges = await build_topic_graph(db, backend)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import combinations

from src.replay.db import ConversationsDB
from src.replay.topic_vectorizer import EmbeddingBackend
from src.replay.umap_runner import UMAPFilter, run_umap

logger = logging.getLogger(__name__)

# Canvas dimensions used when scaling UMAP coordinates to pixel space.
_CANVAS_W = 1200.0
_CANVAS_H = 800.0
_PADDING = 0.08


@dataclass
class TopicGraphNode:
    """A topic node in the co-occurrence graph.

    Attributes:
        id: Stable node identifier (``"t:{topic}"``).
        label: Display string for the topic.
        count: Total occurrence count across all sessions.
        session_count: Number of distinct sessions this topic appears in.
        x: Canvas x-coordinate (UMAP-derived, scaled to [~0, _CANVAS_W]).
        y: Canvas y-coordinate (UMAP-derived, scaled to [~0, _CANVAS_H]).
    """

    id: str
    label: str
    count: int
    session_count: int
    x: float
    y: float


@dataclass
class TopicGraphEdge:
    """An undirected co-occurrence edge between two topic nodes.

    Attributes:
        source: Node ID of the first topic (``"t:{topic_a}"``).
        target: Node ID of the second topic (``"t:{topic_b}"``).
        shared_sessions: Number of sessions in which both topics co-occur.
    """

    source: str
    target: str
    shared_sessions: int


# ─── pure helpers (fully testable without DB/UMAP) ───────────────────────────


def _aggregate_rows(
    rows: list[dict],
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Aggregate raw DB rows into per-topic session sets and total counts.

    Args:
        rows: Each dict must have ``"topic"``, ``"session_id"``, ``"count"`` keys.

    Returns:
        Tuple of (topic_sessions, topic_count) mappings.
    """
    topic_sessions: dict[str, set[str]] = {}
    topic_count: dict[str, int] = {}
    for row in rows:
        t: str = row["topic"]
        s: str = row["session_id"]
        c: int = int(row["count"])
        topic_sessions.setdefault(t, set()).add(s)
        topic_count[t] = topic_count.get(t, 0) + c
    return topic_sessions, topic_count


def _scale_to_canvas(
    topic_list: list[str],
    raw_coords: list[tuple[float, float]],
    topic_count: dict[str, int],
    topic_sessions: dict[str, set[str]],
) -> list[TopicGraphNode]:
    """Convert raw UMAP coordinates to canvas-space TopicGraphNodes.

    Normalises x and y independently into [padding*W, (1-padding)*W] and
    [padding*H, (1-padding)*H] respectively.

    Args:
        topic_list: Ordered list of topic strings matching raw_coords.
        raw_coords: UMAP (x, y) pairs in original float space.
        topic_count: Total occurrence count per topic.
        topic_sessions: Set of session IDs per topic.

    Returns:
        List of TopicGraphNode with scaled x/y coordinates.
    """
    if not raw_coords:
        return []

    xs = [c[0] for c in raw_coords]
    ys = [c[1] for c in raw_coords]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = x_max - x_min or 1.0
    y_range = y_max - y_min or 1.0

    usable_w = _CANVAS_W * (1.0 - 2.0 * _PADDING)
    usable_h = _CANVAS_H * (1.0 - 2.0 * _PADDING)

    nodes: list[TopicGraphNode] = []
    for i, topic in enumerate(topic_list):
        rx, ry = raw_coords[i]
        sx = _PADDING * _CANVAS_W + (rx - x_min) / x_range * usable_w
        sy = _PADDING * _CANVAS_H + (ry - y_min) / y_range * usable_h
        nodes.append(
            TopicGraphNode(
                id=f"t:{topic}",
                label=topic,
                count=topic_count.get(topic, 0),
                session_count=len(topic_sessions.get(topic, set())),
                x=round(sx, 1),
                y=round(sy, 1),
            )
        )
    return nodes


def _build_edges(
    node_labels: set[str],
    topic_sessions: dict[str, set[str]],
    min_shared_sessions: int,
) -> list[TopicGraphEdge]:
    """Build undirected co-occurrence edges for the given topic set.

    Args:
        node_labels: Topics to consider (already filtered by min_topic_count).
        topic_sessions: Mapping of topic → set of session IDs.
        min_shared_sessions: Minimum shared sessions to create an edge.

    Returns:
        List of TopicGraphEdge (one per qualifying topic pair).
    """
    edges: list[TopicGraphEdge] = []
    for t1, t2 in combinations(sorted(node_labels), 2):
        s1 = topic_sessions.get(t1, set())
        s2 = topic_sessions.get(t2, set())
        shared = len(s1 & s2)
        if shared >= min_shared_sessions:
            edges.append(
                TopicGraphEdge(
                    source=f"t:{t1}",
                    target=f"t:{t2}",
                    shared_sessions=shared,
                )
            )
    return edges


# ─── async orchestrator ───────────────────────────────────────────────────────


async def build_topic_graph(
    db: ConversationsDB,
    backend: EmbeddingBackend,
    min_topic_count: int = 2,
    min_shared_sessions: int = 1,
) -> tuple[list[TopicGraphNode], list[TopicGraphEdge]]:
    """Build a cross-session topic co-occurrence graph.

    Topics are positioned using UMAP coordinates averaged across sessions
    (cached in the DB).  Edges connect topics that co-occur in at least
    *min_shared_sessions* sessions.

    Args:
        db: Open ConversationsDB.
        backend: Embedding backend used for UMAP coordinate generation.
        min_topic_count: Minimum total occurrence count for a topic to appear.
        min_shared_sessions: Minimum shared sessions for an edge.

    Returns:
        Tuple of (nodes, edges).  Both lists are empty when fewer than
        2 eligible topics exist.
    """
    rows = await db.get_topics_for_umap()
    if not rows:
        return [], []

    topic_sessions, topic_count = _aggregate_rows(rows)

    # Keep only topics that meet the count threshold.
    eligible: set[str] = {t for t, c in topic_count.items() if c >= min_topic_count}
    if len(eligible) < 2:
        return [], []

    # Obtain UMAP coordinates (uses embedding cache in DB).
    umap_points = await run_umap(db, backend, UMAPFilter())

    # Average UMAP coordinates across sessions for each eligible topic.
    coord_acc: dict[str, list[tuple[float, float]]] = {}
    for p in umap_points:
        if p.topic in eligible:
            coord_acc.setdefault(p.topic, []).append((p.x, p.y))

    # Only keep topics that have UMAP coordinates.
    topics_with_coords = [t for t in sorted(coord_acc) if t in eligible]
    if len(topics_with_coords) < 2:
        return [], []

    raw_coords = [
        (
            sum(c[0] for c in coord_acc[t]) / len(coord_acc[t]),
            sum(c[1] for c in coord_acc[t]) / len(coord_acc[t]),
        )
        for t in topics_with_coords
    ]

    nodes = _scale_to_canvas(topics_with_coords, raw_coords, topic_count, topic_sessions)
    node_label_set = {n.label for n in nodes}
    edges = _build_edges(node_label_set, topic_sessions, min_shared_sessions)

    logger.info(
        "Topic graph: %d nodes, %d edges (min_count=%d, min_shared=%d)",
        len(nodes),
        len(edges),
        min_topic_count,
        min_shared_sessions,
    )
    return nodes, edges
