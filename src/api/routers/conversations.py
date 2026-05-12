"""Conversations API: per-session conversation listing and active-topic tracking.

Endpoints
---------
GET /sessions/{session_id}/conversations
    Newest-first conversation list with optional summaries (LEFT JOIN).
    Supports keyset cursor paging via ``before_conversation_id``.

GET /sessions/{session_id}/topics/active
    Returns the top-K active topics for the session using a moving-average
    approach over the most recent ``window`` summarised conversations.

Trend semantics (compare latest half vs prior half of the window)
-----------------------------------------------------------------
  new     — topic appears only in the recent half (absent in prior half)
  rising  — frequency in recent half > frequency in prior half
  stable  — all other cases (including topics only in the prior half)
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_db, get_store
from src.replay.db import ConversationsDB
from src.store.event_store import EventStore

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ConversationItem(BaseModel):
    conversation_id: str
    session_id: str
    created_at: str
    message_count: int
    event_index_start: int
    event_index_end: int
    summary_short: Optional[str]
    topics: Optional[list[str]]
    is_pending: bool = False


class ActiveTopic(BaseModel):
    topic: str
    weight: float
    trend: str


class ActiveTopicWindow(BaseModel):
    conversations: int
    from_: Optional[str]
    to: Optional[str]


class ActiveTopicsResponse(BaseModel):
    active_topics: list[ActiveTopic]
    window: ActiveTopicWindow


# ---------------------------------------------------------------------------
# GET /sessions/{session_id}/conversations
# ---------------------------------------------------------------------------


def _make_pending_item(
    session_id: str,
    store: EventStore,
    last_indexed: Optional[int],
) -> Optional[ConversationItem]:
    """Build a synthetic pending ConversationItem from trailing unindexed events.

    Returns None when there are no trailing events (all events are indexed).
    Only call this when ``before_conversation_id`` is None (first page).
    """
    total = store.count_events(session_id)
    trailing_start = (last_indexed + 1) if last_indexed is not None else 0
    if total <= trailing_start:
        return None

    trailing_count = total - trailing_start

    # Read the first trailing event to get its timestamp.
    pending_ts: str = datetime.now(timezone.utc).isoformat()
    all_events = store.iter_events(session_id)
    if trailing_start < len(all_events):
        pending_ts = all_events[trailing_start].timestamp.isoformat()

    return ConversationItem(
        conversation_id=f"pending:{session_id}",
        session_id=session_id,
        created_at=pending_ts,
        message_count=trailing_count,
        event_index_start=trailing_start,
        event_index_end=total - 1,
        summary_short=None,
        topics=None,
        is_pending=True,
    )


@router.get(
    "/sessions/{session_id}/conversations",
    response_model=list[ConversationItem],
)
async def list_conversations(
    session_id: str,
    limit: int = Query(default=10, ge=1, le=200, description="Maximum conversations to return"),
    before_conversation_id: Optional[str] = Query(
        default=None,
        description="Cursor: return conversations older than this conversation_id",
    ),
    db: ConversationsDB = Depends(get_db),
    store: EventStore = Depends(get_store),
) -> list[ConversationItem]:
    """Return conversations for a session, newest-first, with cursor paging.

    Conversations without summaries (pipeline lag) are included with
    ``summary_short=null`` and ``topics=null``.  Use ``before_conversation_id``
    to page backwards: pass the oldest ``conversation_id`` from the previous
    response to retrieve the next page.

    A synthetic ``is_pending=True`` entry is prepended on the first page when
    trailing events exist beyond the last STOP-indexed conversation.  This
    represents an in-progress or interrupted session that has not yet been
    closed by a StopEvent.
    """
    rows = await db.get_latest_conversations_with_summaries_cursor(
        session_id=session_id,
        limit=limit,
        before_conversation_id=before_conversation_id,
    )
    items: list[ConversationItem] = [ConversationItem(**row) for row in rows]

    if before_conversation_id is None:
        last_indexed = await db.get_last_indexed_event(session_id)
        pending = _make_pending_item(session_id, store, last_indexed)
        if pending is not None:
            items.insert(0, pending)

    return items


# ---------------------------------------------------------------------------
# GET /sessions/{session_id}/topics/active
# ---------------------------------------------------------------------------


def _compute_active_topics(
    rows: list[dict[str, Any]],
    window: int,
    top_k: int,
) -> ActiveTopicsResponse:
    """Compute moving-average active topics from a list of summarised conversations.

    The ``window`` most recent rows (already ordered newest-first) are used.
    Trend is determined by comparing topic frequency in the latest half versus
    the prior half:
      - new     : absent in the prior half, present in the recent half
      - rising  : frequency in recent half strictly greater than prior half
      - stable  : all other cases
    """
    # Clamp to window size and reverse to chronological order (oldest first).
    capped = rows[:window]
    chronological = list(reversed(capped))
    n = len(chronological)

    if n == 0:
        return ActiveTopicsResponse(
            active_topics=[],
            window=ActiveTopicWindow(conversations=0, from_=None, to=None),
        )

    # Split into prior half and recent half.
    mid = n // 2
    prior_half = chronological[:mid]
    recent_half = chronological[mid:]

    prior_counter: Counter[str] = Counter()
    recent_counter: Counter[str] = Counter()
    for r in prior_half:
        prior_counter.update(r.get("topics") or [])
    for r in recent_half:
        recent_counter.update(r.get("topics") or [])

    # Total counts across the full window for weight.
    total_counter: Counter[str] = prior_counter + recent_counter

    # Guard against empty denominators.
    prior_n = max(len(prior_half), 1)
    recent_n = max(len(recent_half), 1)

    active: list[ActiveTopic] = []
    for topic, count in total_counter.most_common(top_k):
        weight = round(count / n, 4)
        prior_freq = prior_counter[topic] / prior_n
        recent_freq = recent_counter[topic] / recent_n

        if prior_counter[topic] == 0:
            trend = "new"
        elif recent_freq > prior_freq:
            trend = "rising"
        else:
            trend = "stable"

        active.append(ActiveTopic(topic=topic, weight=weight, trend=trend))

    dates = [r["created_at"] for r in chronological]
    return ActiveTopicsResponse(
        active_topics=active,
        window=ActiveTopicWindow(
            conversations=n,
            from_=min(dates) if dates else None,
            to=max(dates) if dates else None,
        ),
    )


@router.get(
    "/sessions/{session_id}/topics/active",
    response_model=ActiveTopicsResponse,
)
async def get_active_topics(
    session_id: str,
    window: int = Query(
        default=10,
        ge=1,
        le=200,
        description="Number of recent summarised conversations to analyse",
    ),
    top_k: int = Query(
        default=5,
        ge=1,
        le=50,
        description="Maximum active topics to return",
    ),
    db: ConversationsDB = Depends(get_db),
) -> ActiveTopicsResponse:
    """Return the top active topics for a session using a moving-average window.

    Only summarised conversations contribute (they carry topic lists).  Topics
    are ranked by overall frequency within the window.  Trend reflects change
    between the older and newer halves of the window:

    - **new**: topic appears only in the recent half
    - **rising**: topic is more frequent in the recent half
    - **stable**: everything else

    ``weight`` is ``count / window_size``.
    """
    rows = await db.get_conversations_with_summaries(
        session_id=session_id,
        limit=window,
    )
    return _compute_active_topics(rows, window, top_k)
