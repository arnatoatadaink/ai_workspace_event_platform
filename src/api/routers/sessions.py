"""GET /sessions — list all sessions with event counts."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.adapters.claude.transcript import read_cursor
from src.api.deps import get_db, get_store
from src.replay.db import ConversationsDB
from src.store.event_store import EventStore

_PROJECTS_ROOT = Path.home() / ".claude" / "projects"

router = APIRouter()


def _cwd_to_claude_project_dir() -> Path:
    """Derive ~/.claude/projects/<slug>/ from the current working directory."""
    import os

    cwd = str(Path(os.getcwd()).resolve())
    slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    return Path.home() / ".claude" / "projects" / slug


def _find_transcript(session_id: str) -> Optional[Path]:
    """Locate the transcript JSONL for *session_id* across all project directories."""
    # Check CWD project first for the common case.
    candidate = _cwd_to_claude_project_dir() / f"{session_id}.jsonl"
    if candidate.exists():
        return candidate
    if _PROJECTS_ROOT.is_dir():
        for slug_dir in _PROJECTS_ROOT.iterdir():
            p = slug_dir / f"{session_id}.jsonl"
            if p.exists():
                return p
    return None


def _has_pending_transcript(session_id: str) -> bool:
    """Return True if the transcript has unprocessed lines beyond the pipeline cursor.

    Uses the pipeline cursor (``{session_id}.pipeline.cursor``) so this reflects
    the independent pipeline state rather than the stop-hook cursor.
    """
    transcript_path = _find_transcript(session_id)
    if transcript_path is None:
        return False
    pipeline_cursor_path = Path("runtime/transcript_cursors") / f"{session_id}.pipeline.cursor"
    try:
        total_lines = sum(1 for _ in transcript_path.open(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    cursor = read_cursor(pipeline_cursor_path)
    if cursor is None:
        return total_lines > 0
    return cursor < total_lines


class SessionInfo(BaseModel):
    session_id: str
    event_count: int
    project_id: Optional[str] = None


class SessionStats(BaseModel):
    session_id: str
    conversation_count: int
    summarized_count: int
    has_pending_transcript: bool
    has_unanalyzed_events: bool


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    store: EventStore = Depends(get_store),
    db: ConversationsDB = Depends(get_db),
) -> list[SessionInfo]:
    """List all sessions with their total event counts and project IDs."""
    session_ids: list[str] = await asyncio.to_thread(store.list_sessions)
    project_map = await db.get_project_ids_for_sessions(session_ids)
    result: list[SessionInfo] = []
    for sid in session_ids:
        count = await asyncio.to_thread(store.count_events, sid)
        result.append(
            SessionInfo(
                session_id=sid,
                event_count=count,
                project_id=project_map.get(sid),
            )
        )
    return result


@router.get("/sessions/{session_id}/stats", response_model=SessionStats)
async def get_session_stats(
    session_id: str,
    db: ConversationsDB = Depends(get_db),
    store: EventStore = Depends(get_store),
) -> SessionStats:
    """Return conversation and summary counts plus transcript backlog status."""
    stats = await db.get_session_stats(session_id)
    has_pending = await asyncio.to_thread(_has_pending_transcript, session_id)
    event_count = await asyncio.to_thread(store.count_events, session_id)

    # has_unanalyzed: are there store events not covered by any DB conversation record?
    # Summing covered ranges handles both contiguous gaps and merged-conversation cases
    # without false positives from turn-count comparisons.
    ranges = await db.get_conversation_index_ranges(session_id)
    total_covered = sum(end - start + 1 for start, end in ranges)
    has_unanalyzed = event_count > 0 and event_count > total_covered

    return SessionStats(
        session_id=session_id,
        conversation_count=stats["conversation_count"],
        summarized_count=stats["summarized_count"],
        has_pending_transcript=has_pending,
        has_unanalyzed_events=has_unanalyzed,
    )
