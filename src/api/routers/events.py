"""GET /events — paginated event listing for a session."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_store
from src.store.event_store import EventStore

router = APIRouter()


class EventPage(BaseModel):
    session_id: str
    total: int
    offset: int
    limit: int
    items: list[dict[str, Any]]


@router.get("/events", response_model=EventPage)
async def list_events(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    store: EventStore = Depends(get_store),
) -> EventPage:
    """List events for *session_id* with limit+offset pagination."""
    all_events = await asyncio.to_thread(store.iter_events, session_id)
    page = all_events[offset : offset + limit]
    return EventPage(
        session_id=session_id,
        total=len(all_events),
        offset=offset,
        limit=limit,
        items=[e.model_dump(mode="json") for e in page],
    )
