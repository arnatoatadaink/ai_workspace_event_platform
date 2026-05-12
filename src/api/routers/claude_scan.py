"""GET /claude/scan-sessions — discover Claude CLI transcript JSONL files.

POST /sessions/{session_id}/ingest  — ingest transcript messages into the event store.
POST /sessions/{session_id}/analyze — split ingested events into conversation records.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.adapters.claude.transcript import parse_transcript_messages, write_cursor
from src.api.deps import get_db, get_snapshot_store, get_store
from src.replay.db import ConversationsDB
from src.replay.snapshot import run_incremental_update
from src.replay.snapshot_store import SnapshotStore
from src.replay.transcript_analyzer import analyze_transcript_session
from src.store.event_store import EventStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _cwd_to_claude_project_dir() -> Path:
    """Derive ~/.claude/projects/<slug>/ from the current working directory."""
    import os

    cwd = str(Path(os.getcwd()).resolve())
    slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    return Path.home() / ".claude" / "projects" / slug


class ScannedSession(BaseModel):
    session_id: str
    message_count: int
    first_message_at: Optional[str] = None
    last_message_at: Optional[str] = None
    file_size_bytes: int


def _scan_jsonl(path: Path) -> ScannedSession:
    """Extract metadata from a single Claude transcript JSONL file."""
    session_id = path.stem
    size = path.stat().st_size
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    count = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            count += 1
            ts = d.get("timestamp")
            if ts:
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
    return ScannedSession(
        session_id=session_id,
        message_count=count,
        first_message_at=first_ts,
        last_message_at=last_ts,
        file_size_bytes=size,
    )


def _scan_dir(target: Path) -> list[ScannedSession]:
    """Synchronous directory scan — run in a thread."""
    if not target.is_dir():
        return []
    files = sorted(target.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_scan_jsonl(p) for p in files]


class IngestResponse(BaseModel):
    session_id: str
    ingested_count: int
    conversations_indexed: int


@router.get("/claude/scan-sessions", response_model=list[ScannedSession])
async def scan_sessions(
    scan_dir: Optional[str] = Query(
        default=None,
        description="Directory to scan. Defaults to ~/.claude/projects/<cwd-slug>/",
    ),
) -> list[ScannedSession]:
    """List Claude CLI transcript files found in the given directory.

    Returns session metadata without importing events into the store.
    """
    target = Path(scan_dir).expanduser().resolve() if scan_dir else _cwd_to_claude_project_dir()
    return await asyncio.to_thread(_scan_dir, target)


@router.post("/sessions/{session_id}/ingest", response_model=IngestResponse)
async def ingest_session_transcript(
    session_id: str,
    store: EventStore = Depends(get_store),
    db: ConversationsDB = Depends(get_db),
    snapshot_store: SnapshotStore = Depends(get_snapshot_store),
) -> IngestResponse:
    """Ingest unprocessed transcript messages for a session into the event store.

    Reads the Claude CLI transcript file at
    ``~/.claude/projects/<cwd-slug>/<session_id>.jsonl``, parses any lines
    beyond the stored cursor, appends them as ``MessageEvent`` instances to the
    event store, updates the cursor, then runs the incremental indexer so new
    conversation boundaries are reflected immediately in the DB.

    Returns the number of ingested events and newly indexed conversations.
    """
    scan_dir = _cwd_to_claude_project_dir()
    transcript_path = scan_dir / f"{session_id}.jsonl"
    cursor_path = Path("runtime/transcript_cursors") / f"{session_id}.cursor"
    store_base = Path("runtime/sessions")

    if not transcript_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Transcript not found: {transcript_path}",
        )

    msg_events, new_line_count = await asyncio.to_thread(
        parse_transcript_messages,
        transcript_path,
        session_id,
        cursor_path,
        store_base,
    )

    for event in msg_events:
        await asyncio.to_thread(store.append, event)

    await asyncio.to_thread(write_cursor, cursor_path, new_line_count)

    before_count = await db.get_last_indexed_event(session_id) or 0
    await run_incremental_update(session_id, store, db, snapshot_store, summarizer=None)
    after_count = await db.get_last_indexed_event(session_id) or 0
    conversations_indexed = max(0, after_count - before_count)

    logger.info(
        "Ingest %s: %d message events ingested, %d new conversation events indexed",
        session_id,
        len(msg_events),
        conversations_indexed,
    )
    return IngestResponse(
        session_id=session_id,
        ingested_count=len(msg_events),
        conversations_indexed=conversations_indexed,
    )


class AnalyzeResponse(BaseModel):
    session_id: str
    conversations_created: int


@router.post("/sessions/{session_id}/analyze", response_model=AnalyzeResponse)
async def analyze_session_transcript(
    session_id: str,
    store: EventStore = Depends(get_store),
    db: ConversationsDB = Depends(get_db),
) -> AnalyzeResponse:
    """Split ingested events into conversation records using transcript turn boundaries.

    Reads ``system/turn_duration`` markers from the session's Claude CLI
    transcript JSONL to determine conversation end times, then groups any
    unindexed events in the event store into new rows in the conversations
    table.

    Falls back to treating all unindexed events as one conversation when the
    transcript file is unavailable or contains no turn_duration entries.

    Returns the number of newly created conversation records.
    """
    scan_dir = _cwd_to_claude_project_dir()
    transcript_path: Optional[Path] = scan_dir / f"{session_id}.jsonl"
    if not transcript_path.exists():
        transcript_path = None

    created = await analyze_transcript_session(
        session_id=session_id,
        transcript_path=transcript_path,
        store=store,
        db=db,
    )

    logger.info("Analyze %s: %d conversations created", session_id, created)
    return AnalyzeResponse(session_id=session_id, conversations_created=created)
