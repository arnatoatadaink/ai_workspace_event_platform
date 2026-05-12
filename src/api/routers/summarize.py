"""Summarize API: on-demand conversation summarization.

Endpoints
---------
POST /conversations/{conversation_id}/summarize
    Summarize one conversation using the active LLM backend.
    Appends SummaryUpdateEvent + TopicExtractionEvent to the EventStore,
    then writes the derived summary to the conversations_summaries table.

    Query parameter ``force=true`` re-runs summarization even if a summary
    already exists (overwrites previous result).

POST /sessions/{session_id}/summarize
    Summarize all unsummarized conversations in a session sequentially.
    With ``force=true``, re-summarizes conversations that already have a summary.
    Returns per-session statistics: processed / skipped / failed.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.deps import get_db, get_store, get_summarizer
from src.replay.db import ConversationsDB
from src.replay.summarizer import SummarizerBackend, summarize_conversation
from src.store.event_store import EventStore

logger = logging.getLogger(__name__)

router = APIRouter()


class SummarizeResponse(BaseModel):
    conversation_id: str
    summary_short: str
    summary_long: str
    topics: list[str]
    model_used: str
    was_cached: bool


class SessionSummarizeResult(BaseModel):
    conversation_id: str
    summary_short: str
    topics: list[str]


class SessionSummarizeResponse(BaseModel):
    session_id: str
    processed: int
    skipped: int
    failed: list[str]
    results: list[SessionSummarizeResult]


@router.post(
    "/conversations/{conversation_id}/summarize",
    response_model=SummarizeResponse,
)
async def summarize_one(
    conversation_id: str,
    force: bool = Query(default=False, description="Re-summarize even if summary exists"),
    db: ConversationsDB = Depends(get_db),
    store: EventStore = Depends(get_store),
    backend: SummarizerBackend = Depends(get_summarizer),
) -> SummarizeResponse:
    """Summarize a conversation on demand.

    Reads the conversation's events from the EventStore, generates
    ``summary_short``, ``summary_long``, and ``topics`` via the active LLM
    backend, then appends ``SummaryUpdateEvent`` and ``TopicExtractionEvent``
    to the event store and persists the result in SQLite.

    Returns the cached summary when one already exists and ``force`` is False.
    """
    conv = await db.get_conversation_by_id(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not force:
        existing: Optional[dict] = await db.get_summary(conversation_id)
        if existing is not None:
            return SummarizeResponse(
                conversation_id=conversation_id,
                summary_short=existing["summary_short"],
                summary_long=existing["summary_long"],
                topics=existing["topics"],
                model_used=existing["model_used"],
                was_cached=True,
            )

    result = await summarize_conversation(conv, store, db, backend)

    return SummarizeResponse(
        conversation_id=conversation_id,
        summary_short=result["summary_short"],
        summary_long=result["summary_long"],
        topics=result["topics"],
        model_used=backend.model_name,
        was_cached=False,
    )


@router.post(
    "/sessions/{session_id}/summarize",
    response_model=SessionSummarizeResponse,
)
async def summarize_session(
    session_id: str,
    force: bool = Query(
        default=False,
        description="Re-summarize conversations that already have a summary",
    ),
    db: ConversationsDB = Depends(get_db),
    store: EventStore = Depends(get_store),
    backend: SummarizerBackend = Depends(get_summarizer),
) -> SessionSummarizeResponse:
    """Summarize all conversations in a session sequentially.

    When ``force`` is False (default), only conversations without an existing
    summary are processed.  Already-summarized conversations are counted in
    ``skipped``.

    When ``force`` is True, every conversation in the session is re-summarized,
    replacing any previous results.

    Each conversation is processed independently so a single LLM failure does
    not abort the entire session — failed conversation IDs are collected in
    ``failed`` and the remainder continue.
    """
    if force:
        conversations = await db.get_latest_conversations(session_id, limit=10_000)
        conversations = list(reversed(conversations))  # oldest-first for pipeline order
    else:
        conversations = await db.get_unsummarized_conversations(session_id)

    if not conversations and not force:
        skipped_count = len(await db.get_latest_conversations(session_id, limit=10_000))
        return SessionSummarizeResponse(
            session_id=session_id,
            processed=0,
            skipped=skipped_count,
            failed=[],
            results=[],
        )

    processed = 0
    skipped = 0
    failed: list[str] = []
    results: list[SessionSummarizeResult] = []

    for conv in conversations:
        cid: str = conv["conversation_id"]
        if not force:
            existing = await db.get_summary(cid)
            if existing is not None:
                skipped += 1
                continue
        try:
            result = await summarize_conversation(conv, store, db, backend)
            processed += 1
            results.append(
                SessionSummarizeResult(
                    conversation_id=cid,
                    summary_short=result["summary_short"],
                    topics=result["topics"],
                )
            )
            logger.info("Session %s: summarized %s", session_id, cid)
        except Exception as exc:
            logger.error("Session %s: failed to summarize %s: %s", session_id, cid, exc)
            failed.append(cid)

    return SessionSummarizeResponse(
        session_id=session_id,
        processed=processed,
        skipped=skipped,
        failed=failed,
        results=results,
    )
