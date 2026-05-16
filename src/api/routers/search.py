"""Search API: full-text search and topic keyword search over conversation summaries.

Endpoints
---------
GET /search/conversations?q={text}
    FTS5 trigram full-text search over summary_short + summary_long + topics_text.
    Supports Japanese / CJK substring matching.

GET /search/topics?q={keyword}
    Topic keyword partial-match search using json_each + LIKE.
    Returns conversations whose topic list contains any topic matching the keyword.

Both endpoints share optional filter parameters:
    project_id  : restrict to a specific Claude project slug
    since_days  : restrict to conversations within the last N days
    limit       : max results (default 20, max 100)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_db
from src.replay.db import ConversationsDB

router = APIRouter()


class ConversationSearchResult(BaseModel):
    conversation_id: str
    session_id: str
    project_id: str
    created_at: str
    summary_short: str
    topics: list[str]


class SearchResponse(BaseModel):
    query: str
    count: int
    results: list[ConversationSearchResult]


def _since_dt(since_days: Optional[float]) -> Optional[datetime]:
    if since_days is None or since_days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=since_days)


@router.get("/search/conversations", response_model=SearchResponse)
async def search_conversations(
    q: str = Query(
        min_length=3,
        description="Full-text search query (FTS5 trigram, supports Japanese; minimum 3 characters)",
    ),
    project_id: Optional[str] = Query(default=None, description="Filter by project slug"),
    since_days: Optional[float] = Query(default=None, ge=0, description="Restrict to last N days"),
    limit: int = Query(default=20, ge=1, le=100),
    db: ConversationsDB = Depends(get_db),
) -> SearchResponse:
    """Full-text search over conversation summaries.

    Uses SQLite FTS5 with the trigram tokenizer, which supports:
    - English word-boundary search: ``machine learning``
    - Japanese/CJK substring search: ``要約``
    - Prefix search: ``trans`` matches ``transformer``

    Results are ordered newest-first.
    """
    results: list[dict[str, Any]] = await db.search_conversations_fts(
        query=q,
        limit=limit,
        project_id=project_id,
        since=_since_dt(since_days),
    )
    return SearchResponse(
        query=q,
        count=len(results),
        results=[ConversationSearchResult(**r) for r in results],
    )


@router.get("/search/topics", response_model=SearchResponse)
async def search_by_topic(
    q: str = Query(description="Topic keyword (partial match, case-insensitive for ASCII)"),
    project_id: Optional[str] = Query(default=None, description="Filter by project slug"),
    since_days: Optional[float] = Query(default=None, ge=0, description="Restrict to last N days"),
    limit: int = Query(default=20, ge=1, le=100),
    db: ConversationsDB = Depends(get_db),
) -> SearchResponse:
    """Search conversations by topic keyword.

    Returns conversations whose topic list contains at least one topic that
    partially matches *q* (e.g. ``q=transform`` matches the topic
    ``transformer``).  Uses ``json_each`` expansion + LIKE under the hood —
    no FTS index required.
    """
    results: list[dict[str, Any]] = await db.search_by_topic(
        keyword=q,
        limit=limit,
        project_id=project_id,
        since=_since_dt(since_days),
    )
    return SearchResponse(
        query=q,
        count=len(results),
        results=[ConversationSearchResult(**r) for r in results],
    )
