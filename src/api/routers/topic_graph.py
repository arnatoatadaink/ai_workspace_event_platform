"""FastAPI router: cross-session topic co-occurrence graph."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.requests import Request

from src.replay.db import ConversationsDB
from src.replay.topic_graph import build_topic_graph
from src.replay.topic_vectorizer import SentenceTransformerBackend

router = APIRouter(prefix="/topic-graph", tags=["topic-graph"])

_backend = SentenceTransformerBackend()


def _get_db(request: Request) -> ConversationsDB:
    return request.app.state.db  # type: ignore[no-any-return]


@router.get("")
async def get_topic_graph(
    db: Annotated[ConversationsDB, Depends(_get_db)],
    min_topic_count: int = Query(
        2, ge=1, description="Minimum total occurrences for a topic to appear as a node"
    ),
    min_shared_sessions: int = Query(
        1, ge=1, description="Minimum shared sessions required to draw an edge between two topics"
    ),
) -> dict[str, Any]:
    """Return a cross-session topic co-occurrence graph.

    Node positions are derived from UMAP embeddings so semantically similar
    topics cluster together.  Edges connect topics that appear in the same
    session at least *min_shared_sessions* times.

    Response shape::

        {
            "nodes": [{"id", "label", "count", "session_count", "x", "y"}, ...],
            "edges": [{"source", "target", "shared_sessions"}, ...],
            "total_nodes": int,
            "total_edges": int
        }
    """
    try:
        nodes, edges = await build_topic_graph(db, _backend, min_topic_count, min_shared_sessions)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "nodes": [dataclasses.asdict(n) for n in nodes],
        "edges": [dataclasses.asdict(e) for e in edges],
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }
