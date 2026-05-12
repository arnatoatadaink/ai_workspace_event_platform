"""Replay Engine: UMAP projection of topic embeddings.

Aggregates topics from the DB, embeds them (with cache), and runs UMAP
to produce 2-D coordinates suitable for Plotly scatter visualisation.

Usage::

    backend = SentenceTransformerBackend()
    async with ConversationsDB() as db:
        points = await run_umap(db, backend, UMAPFilter())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import umap  # type: ignore[import-untyped]

from src.replay.db import ConversationsDB
from src.replay.topic_vectorizer import EmbeddingBackend, vectorize_topics

logger = logging.getLogger(__name__)

_MIN_TOPICS = 2
_DEFAULT_N_NEIGHBORS = 15
_DEFAULT_MIN_DIST = 0.1


@dataclass
class UMAPFilter:
    """Filters applied before UMAP projection.

    Attributes:
        session_id: Restrict topics to a specific session.
        since: Include only conversations created at or after this UTC datetime.
        until: Include only conversations created before this UTC datetime.
        color_by: Grouping axis for the scatter plot (``"session"`` or ``"time"``).
    """

    session_id: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    color_by: str = "session"


@dataclass
class TopicPoint:
    """One scatter-plot data point in 2-D UMAP space.

    Attributes:
        topic: Topic string.
        x: UMAP x coordinate.
        y: UMAP y coordinate.
        count: Number of times this topic appeared in the filtered set.
        session_id: Session the topic came from (``"multiple"`` if aggregated).
        color_label: The label used for colour grouping (depends on ``color_by``).
        first_seen: ISO-8601 timestamp of the earliest conversation containing the topic.
    """

    topic: str
    x: float
    y: float
    count: int
    session_id: str
    color_label: str
    first_seen: str = field(default="")


async def run_umap(
    db: ConversationsDB,
    backend: EmbeddingBackend,
    umap_filter: UMAPFilter | None = None,
) -> list[TopicPoint]:
    """Project topics into 2-D UMAP space and return scatter data.

    Fetches topic occurrences from the DB, embeds unique topic strings
    (using cache), then runs UMAP on the embedding matrix.

    Args:
        db: Open ConversationsDB.
        backend: Embedding backend (e.g. SentenceTransformerBackend).
        umap_filter: Filters and options for the projection.

    Returns:
        List of TopicPoint objects.  Empty list if fewer than 2 unique topics.

    Raises:
        RuntimeError: If UMAP projection fails for an unexpected reason.
    """
    if umap_filter is None:
        umap_filter = UMAPFilter()

    rows = await db.get_topics_for_umap(
        session_id=umap_filter.session_id,
        since=umap_filter.since,
        until=umap_filter.until,
    )

    if not rows:
        logger.info("No topic rows found for UMAP — returning empty result.")
        return []

    unique_topics = list(dict.fromkeys(r["topic"] for r in rows))
    if len(unique_topics) < _MIN_TOPICS:
        logger.info(
            "Only %d unique topic(s) found — need at least %d for UMAP.",
            len(unique_topics),
            _MIN_TOPICS,
        )
        return []

    topic_vectors = await vectorize_topics(unique_topics, db, backend)

    matrix = np.array([topic_vectors[t] for t in unique_topics], dtype=np.float32)

    n_neighbors = min(_DEFAULT_N_NEIGHBORS, len(unique_topics) - 1)
    logger.debug("Running UMAP on %d topics (n_neighbors=%d)", len(unique_topics), n_neighbors)

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=_DEFAULT_MIN_DIST,
        metric="cosine",
        random_state=42,
    )
    coords: np.ndarray = reducer.fit_transform(matrix)

    topic_to_coord: dict[str, tuple[float, float]] = {
        t: (float(coords[i, 0]), float(coords[i, 1])) for i, t in enumerate(unique_topics)
    }

    points: list[TopicPoint] = []
    for row in rows:
        topic: str = row["topic"]
        x, y = topic_to_coord[topic]
        session_id: str = row["session_id"]
        color_label = _compute_color_label(row, umap_filter.color_by)
        points.append(
            TopicPoint(
                topic=topic,
                x=round(x, 6),
                y=round(y, 6),
                count=row["count"],
                session_id=session_id,
                color_label=color_label,
                first_seen=row["first_seen"] or "",
            )
        )

    return points


def _compute_color_label(row: dict, color_by: str) -> str:
    """Derive the colour label for a topic row based on *color_by* axis."""
    if color_by == "session":
        return row["session_id"]
    if color_by == "time":
        first_seen: str = row.get("first_seen") or ""
        return first_seen[:7] if len(first_seen) >= 7 else first_seen  # YYYY-MM
    return row["session_id"]
