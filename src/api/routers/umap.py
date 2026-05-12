"""FastAPI router: UMAP topic map generation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.requests import Request

from src.replay.db import ConversationsDB
from src.replay.topic_vectorizer import SentenceTransformerBackend
from src.replay.umap_render import build_plotly_figure
from src.replay.umap_runner import UMAPFilter, run_umap

router = APIRouter(prefix="/umap", tags=["umap"])

_backend = SentenceTransformerBackend()


def _get_db(request: Request) -> ConversationsDB:
    return request.app.state.db  # type: ignore[no-any-return]


@router.get("")
async def get_umap(
    db: Annotated[ConversationsDB, Depends(_get_db)],
    session_id: Optional[str] = Query(None, description="Restrict to a specific session"),
    since: Optional[datetime] = Query(
        None, description="Include conversations on/after this UTC datetime (ISO-8601)"
    ),
    until: Optional[datetime] = Query(
        None, description="Include conversations before this UTC datetime (ISO-8601)"
    ),
    color_by: str = Query("session", pattern="^(session|time)$", description="Color grouping axis"),
) -> dict[str, Any]:
    """Generate a Plotly scatter figure of UMAP-projected topic embeddings.

    Returns a Plotly figure dict (``data`` + ``layout``) ready for
    ``react-plotly.js``.  Topics are embedded with sentence-transformers and
    projected to 2-D with UMAP.  Results are cached in the DB.

    Query params:
    - ``session_id``: restrict to one session
    - ``since`` / ``until``: time-window filter (ISO-8601 UTC)
    - ``color_by``: ``session`` (default) or ``time`` (YYYY-MM buckets)
    """
    since_utc: Optional[datetime] = None
    until_utc: Optional[datetime] = None

    if since is not None:
        since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)

    if until is not None:
        until_utc = until if until.tzinfo else until.replace(tzinfo=timezone.utc)

    umap_filter = UMAPFilter(
        session_id=session_id,
        since=since_utc,
        until=until_utc,
        color_by=color_by,
    )

    try:
        points = await run_umap(db, _backend, umap_filter)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    figure = build_plotly_figure(points, color_by=color_by)
    return {
        "figure": figure,
        "point_count": len(points),
        "color_by": color_by,
    }
