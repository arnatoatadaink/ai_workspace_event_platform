"""GET /claude/scan-sessions — discover Claude CLI transcript JSONL files.

POST /sessions/{session_id}/ingest  — ingest transcript messages into the event store.
POST /sessions/{session_id}/analyze — split ingested events into conversation records.

Pipeline design note
--------------------
Ingest and analyze form an independent pipeline separate from the stop-hook path.
The pipeline uses its own cursor (``{session_id}.pipeline.cursor``) so it never
interferes with the hook cursor, and relies on event_id deduplication to avoid
writing events that the hook already stored.  ``run_incremental_update`` (the
stop-hook indexer) is NOT called after pipeline ingest; conversation records are
created by the analyze endpoint which uses transcript turn_duration boundaries.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.adapters.claude.paths import cwd_to_claude_project_dir
from src.adapters.claude.transcript import parse_transcript_messages, write_cursor
from src.api.deps import get_db, get_store
from src.replay.db import ConversationsDB
from src.replay.transcript_analyzer import analyze_transcript_session
from src.store.event_store import EventStore

logger = logging.getLogger(__name__)

router = APIRouter()


class ProjectInfo(BaseModel):
    project_id: str
    session_count: int


class ScannedSession(BaseModel):
    session_id: str
    project_id: str
    message_count: int
    first_message_at: Optional[str] = None
    last_message_at: Optional[str] = None
    file_size_bytes: int


def _scan_jsonl(path: Path, project_id: str = "") -> ScannedSession:
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
        project_id=project_id,
        message_count=count,
        first_message_at=first_ts,
        last_message_at=last_ts,
        file_size_bytes=size,
    )


def _scan_dir(target: Path) -> list[ScannedSession]:
    """Synchronous directory scan — run in a thread."""
    if not target.is_dir():
        return []
    project_id = target.name
    files = sorted(target.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_scan_jsonl(p, project_id) for p in files]


def _scan_all_projects() -> list[ScannedSession]:
    """Scan all Claude CLI project directories under ~/.claude/projects/."""
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.is_dir():
        return []
    sessions: list[ScannedSession] = []
    for slug_dir in sorted(projects_root.iterdir()):
        if slug_dir.is_dir():
            sessions.extend(_scan_dir(slug_dir))
    sessions.sort(key=lambda s: s.last_message_at or "", reverse=True)
    return sessions


def _list_projects() -> list[ProjectInfo]:
    """List all Claude CLI projects (slug directories) under ~/.claude/projects/."""
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.is_dir():
        return []
    result: list[ProjectInfo] = []
    for slug_dir in sorted(projects_root.iterdir()):
        if slug_dir.is_dir():
            count = len(list(slug_dir.glob("*.jsonl")))
            result.append(ProjectInfo(project_id=slug_dir.name, session_count=count))
    return result


def _collect_existing_event_ids(store: EventStore, session_id: str) -> set[str]:
    """Return the set of event_ids already stored for *session_id*.

    Reads raw JSON without full Pydantic validation to minimise overhead.
    """
    ids: set[str] = set()
    for chunk in store.iter_chunks(session_id):
        with chunk.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(json.loads(line)["event_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    return ids


class IngestResponse(BaseModel):
    session_id: str
    ingested_count: int
    skipped_duplicates: int


@router.get("/claude/scan-projects", response_model=list[ProjectInfo])
async def list_projects() -> list[ProjectInfo]:
    """List all Claude CLI project directories under ~/.claude/projects/."""
    return await asyncio.to_thread(_list_projects)


@router.get("/claude/scan-sessions", response_model=list[ScannedSession])
async def scan_sessions(
    scan_dir: Optional[str] = Query(
        default=None,
        description="Directory to scan. Defaults to ~/.claude/projects/<cwd-slug>/",
    ),
    project_id: Optional[str] = Query(
        default=None,
        description="Project slug to scan. When set, overrides scan_dir.",
    ),
    all_projects: bool = Query(
        default=False,
        description="When true, scan all projects under ~/.claude/projects/.",
    ),
) -> list[ScannedSession]:
    """List Claude CLI transcript files found in the given directory.

    Returns session metadata without importing events into the store.
    """
    if all_projects:
        return await asyncio.to_thread(_scan_all_projects)
    if project_id:
        target = Path.home() / ".claude" / "projects" / project_id
    elif scan_dir:
        target = Path(scan_dir).expanduser().resolve()
    else:
        target = cwd_to_claude_project_dir()
    return await asyncio.to_thread(_scan_dir, target)


@router.post("/sessions/{session_id}/ingest", response_model=IngestResponse)
async def ingest_session_transcript(
    session_id: str,
    store: EventStore = Depends(get_store),
    db: ConversationsDB = Depends(get_db),
) -> IngestResponse:
    """Ingest unprocessed transcript messages for a session into the event store.

    Uses an independent pipeline cursor (``{session_id}.pipeline.cursor``) so
    this path never interferes with the stop-hook cursor.  Events already
    present in the store (matched by event_id) are skipped to avoid duplicates.

    After ingest, call ``POST /sessions/{session_id}/analyze`` to create
    conversation records from the newly stored events using transcript
    turn_duration boundaries.

    Returns the number of ingested events and skipped duplicates.
    """
    scan_dir = cwd_to_claude_project_dir()
    transcript_path: Optional[Path] = scan_dir / f"{session_id}.jsonl"
    if not transcript_path.exists():
        # Fall back to searching all project directories (mirrors analyze endpoint).
        projects_root = Path.home() / ".claude" / "projects"
        transcript_path = None
        if projects_root.is_dir():
            for slug_dir in projects_root.iterdir():
                candidate = slug_dir / f"{session_id}.jsonl"
                if candidate.exists():
                    transcript_path = candidate
                    scan_dir = slug_dir
                    break

    if transcript_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"Transcript not found for session {session_id} in any project directory",
        )

    pipeline_cursor_path = Path("runtime/transcript_cursors") / f"{session_id}.pipeline.cursor"
    store_base = Path("runtime/sessions")

    # Parse transcript from pipeline cursor; skip migration guard — rely on UUID dedup instead.
    msg_events, new_line_count = await asyncio.to_thread(
        parse_transcript_messages,
        transcript_path,
        session_id,
        pipeline_cursor_path,
        store_base,
        False,  # apply_migration_guard=False
    )

    # Deduplicate: skip events already written by the stop hook.
    existing_ids: set[str] = await asyncio.to_thread(_collect_existing_event_ids, store, session_id)
    new_events = [ev for ev in msg_events if ev.event_id not in existing_ids]
    skipped = len(msg_events) - len(new_events)

    for event in new_events:
        await asyncio.to_thread(store.append, event)

    await asyncio.to_thread(write_cursor, pipeline_cursor_path, new_line_count)

    logger.info(
        "Pipeline ingest %s: %d new events, %d duplicates skipped",
        session_id,
        len(new_events),
        skipped,
    )
    return IngestResponse(
        session_id=session_id,
        ingested_count=len(new_events),
        skipped_duplicates=skipped,
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
    """Create conversation records for pipeline-ingested events using transcript turn boundaries.

    Reads ``system/turn_duration`` markers from the session's Claude CLI
    transcript JSONL to determine conversation end times.  Events in the store
    that are not yet covered by any existing conversation record are grouped by
    those boundaries and inserted as new rows in the conversations table.

    Already-covered events (from stop-hook or a prior analyze run) are left
    untouched — this path only complements existing records, never deletes them.

    Returns the number of newly created conversation records.
    """
    # Resolve transcript from CWD's project dir first; fall back to scanning all projects.
    scan_dir = cwd_to_claude_project_dir()
    transcript_path: Optional[Path] = scan_dir / f"{session_id}.jsonl"
    if not transcript_path.exists():
        # Search other project directories.
        projects_root = Path.home() / ".claude" / "projects"
        transcript_path = None
        if projects_root.is_dir():
            for slug_dir in projects_root.iterdir():
                candidate = slug_dir / f"{session_id}.jsonl"
                if candidate.exists():
                    transcript_path = candidate
                    scan_dir = slug_dir
                    break

    # project_id is the slug directory name that contains the transcript.
    project_id = scan_dir.name

    created = await analyze_transcript_session(
        session_id=session_id,
        transcript_path=transcript_path,
        store=store,
        db=db,
        project_id=project_id,
    )

    logger.info("Analyze %s (project=%s): %d conversations created", session_id, project_id, created)
    return AnalyzeResponse(session_id=session_id, conversations_created=created)
