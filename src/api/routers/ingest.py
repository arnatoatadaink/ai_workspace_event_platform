"""POST /ingest — receive source-specific hook payloads and store as internal events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.adapters.base import AdapterPlugin
from src.api.deps import get_adapters, get_store
from src.store.event_store import EventStore

logger = logging.getLogger(__name__)
router = APIRouter()


class IngestRequest(BaseModel):
    source: str
    payload: dict[str, Any]


class IngestResponse(BaseModel):
    stored: int


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    body: IngestRequest,
    store: EventStore = Depends(get_store),
    adapters: dict[str, AdapterPlugin] = Depends(get_adapters),
) -> IngestResponse:
    """Convert a source-specific hook payload to InternalEvents and append to the store.

    The ``source`` field must match a registered AdapterPlugin's ``source_name``.
    Returns the count of events successfully stored.
    """
    adapter = adapters.get(body.source)
    if adapter is None:
        raise HTTPException(status_code=422, detail=f"Unknown source: {body.source!r}")

    events = await asyncio.to_thread(adapter.parse, body.payload)
    for event in events:
        await asyncio.to_thread(store.append, event)

    logger.debug("Ingested %d events from source=%r", len(events), body.source)
    return IngestResponse(stored=len(events))
