"""GET /topics — multi-scope topic listing with occurrence counts and time filtering.

Query parameters
----------------
scope          : "conversation" | "session" | "global"  (default: conversation)
session_id     : filter by session (any scope; ignored only in spirit at global)
with_counts    : bool — include topic_counts dict in each entry
within_days    : float — restrict to conversations within the last N days
within_hours   : float — within N hours   (additive with the other within_* params)
within_minutes : float — within N minutes (additive)

Time params are additive: within_days=1&within_hours=2 = last 26 hours.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_db
from src.replay.db import ConversationsDB

router = APIRouter()


class TopicsResponse(BaseModel):
    scope: str
    within_minutes: Optional[float]
    since: Optional[str]
    data: list[dict[str, Any]]


def _compute_since(
    within_days: Optional[float],
    within_hours: Optional[float],
    within_minutes: Optional[float],
) -> tuple[Optional[datetime], Optional[float]]:
    """Return (since_dt, total_minutes). Both None when no filter specified."""
    total = (within_days or 0.0) * 1440.0 + (within_hours or 0.0) * 60.0 + (within_minutes or 0.0)
    if total <= 0:
        return None, None
    return datetime.now(timezone.utc) - timedelta(minutes=total), total


@router.get("/topics", response_model=TopicsResponse)
async def list_topics(
    scope: str = Query(
        default="conversation",
        pattern="^(conversation|session|global)$",
        description="Aggregation scope: conversation | session | global",
    ),
    session_id: Optional[str] = Query(default=None),
    with_counts: bool = Query(default=False, description="Include topic occurrence counts"),
    within_days: Optional[float] = Query(default=None, ge=0),
    within_hours: Optional[float] = Query(default=None, ge=0),
    within_minutes: Optional[float] = Query(default=None, ge=0),
    db: ConversationsDB = Depends(get_db),
) -> TopicsResponse:
    """List topics across conversations with optional scope aggregation and time range.

    - **conversation**: one entry per conversation (finest grain)
    - **session**: topics aggregated per session, counts = appearances across conversations
    - **global**: all sessions collapsed into a single entry

    Set ``with_counts=true`` to get ``topic_counts`` dicts ordered by frequency.
    Use ``within_*`` params to focus on a recent time window.
    """
    since, total_minutes = _compute_since(within_days, within_hours, within_minutes)

    rows = await db.get_conversations_with_summaries(
        session_id=session_id,
        since=since,
        limit=5000,
    )

    if scope == "conversation":
        data = _build_conversation(rows, with_counts)
    elif scope == "session":
        data = _build_session(rows, with_counts)
    else:
        data = _build_global(rows, with_counts)

    return TopicsResponse(
        scope=scope,
        within_minutes=total_minutes,
        since=since.isoformat() if since else None,
        data=data,
    )


# ---------------------------------------------------------------------------
# Scope builders
# ---------------------------------------------------------------------------


def _build_conversation(rows: list[dict[str, Any]], with_counts: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "conversation_id": row["conversation_id"],
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "summary_short": row["summary_short"],
            "topics": row["topics"],
        }
        if with_counts:
            # Within a single conversation each topic appears once.
            entry["topic_counts"] = {t: 1 for t in row["topics"]}
        result.append(entry)
    return result


def _build_session(rows: list[dict[str, Any]], with_counts: bool) -> list[dict[str, Any]]:
    """Aggregate by session; topic_counts = number of conversations mentioning each topic."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = row["session_id"]
        if sid not in buckets:
            buckets[sid] = {
                "session_id": sid,
                "conversation_count": 0,
                "_counter": Counter(),
                "_dates": [],
            }
        b = buckets[sid]
        b["conversation_count"] += 1
        b["_counter"].update(row["topics"])
        b["_dates"].append(row["created_at"])

    result: list[dict[str, Any]] = []
    for b in buckets.values():
        counter: Counter[str] = b["_counter"]
        entry: dict[str, Any] = {
            "session_id": b["session_id"],
            "topics": [t for t, _ in counter.most_common()],
            "conversation_count": b["conversation_count"],
            "earliest": min(b["_dates"]),
            "latest": max(b["_dates"]),
        }
        if with_counts:
            entry["topic_counts"] = dict(counter.most_common())
        result.append(entry)

    result.sort(key=lambda x: x["latest"], reverse=True)
    return result


def _build_global(rows: list[dict[str, Any]], with_counts: bool) -> list[dict[str, Any]]:
    """Collapse all sessions into one entry."""
    if not rows:
        base: dict[str, Any] = {
            "topics": [],
            "conversation_count": 0,
            "session_count": 0,
            "earliest": None,
            "latest": None,
        }
        if with_counts:
            base["topic_counts"] = {}
        return [base]

    counter: Counter[str] = Counter()
    sessions: set[str] = set()
    dates: list[str] = []
    for row in rows:
        counter.update(row["topics"])
        sessions.add(row["session_id"])
        dates.append(row["created_at"])

    entry: dict[str, Any] = {
        "topics": [t for t, _ in counter.most_common()],
        "conversation_count": len(rows),
        "session_count": len(sessions),
        "earliest": min(dates),
        "latest": max(dates),
    }
    if with_counts:
        entry["topic_counts"] = dict(counter.most_common())
    return [entry]
