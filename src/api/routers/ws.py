"""WS /stream — WebSocket event stream for a session."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.store.event_store import EventStore

logger = logging.getLogger(__name__)
router = APIRouter()

_POLL_INTERVAL = 1.0


@router.websocket("/stream")
async def stream_events(websocket: WebSocket, session_id: str) -> None:
    """Stream new events for *session_id* as they are appended to the store.

    On connect: sends all events already in the store (to restore client state),
    then streams deltas at 1-second poll intervals.

    Each message is a single InternalEvent serialised as JSON.
    """
    store: EventStore = websocket.app.state.store
    await websocket.accept()
    logger.debug("WebSocket connected: session_id=%r", session_id)

    known_count = 0
    try:
        while True:
            events = await asyncio.to_thread(store.iter_events, session_id)
            new_events = events[known_count:]

            for event in new_events:
                await websocket.send_text(event.model_dump_json())

            known_count = len(events)
            await asyncio.sleep(_POLL_INTERVAL)
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected: session_id=%r", session_id)
