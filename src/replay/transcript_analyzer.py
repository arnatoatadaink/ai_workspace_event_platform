"""Transcript-based conversation analyzer.

Reads ``system/turn_duration`` boundary markers from a Claude CLI transcript
JSONL and groups ingested event-store events into conversation records in
ConversationsDB.

Called by the ``POST /sessions/{session_id}/analyze`` endpoint.  Complements
the hook-driven ``index_session`` indexer — use this when a session was
recorded while the server was offline (no Stop hooks, no StopEvents in store).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.replay.db import ConversationsDB
from src.schemas.internal_event_v1 import EventType, InternalEvent, parse_event
from src.store.event_store import EventStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def read_turn_end_times(transcript_path: Path) -> list[datetime]:
    """Return timestamps of ``system/turn_duration`` entries from a transcript JSONL.

    Each entry marks the end of a completed Claude CLI stop event, equivalent
    to what the Stop hook sends when the server is online.
    """
    turn_ends: list[datetime] = []
    try:
        with transcript_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") == "system" and entry.get("subtype") == "turn_duration":
                    ts_str = entry.get("timestamp", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            turn_ends.append(ts)
                        except ValueError:
                            pass
    except OSError:
        logger.warning("Cannot read transcript at %s", transcript_path)
    return turn_ends


# ---------------------------------------------------------------------------
# Event collection
# ---------------------------------------------------------------------------


def _collect_unindexed_events(
    store: EventStore,
    session_id: str,
    start_from_idx: int,
) -> list[tuple[int, str, InternalEvent]]:
    """Return ``(global_idx, chunk_name, event)`` for events from *start_from_idx* onward."""
    results: list[tuple[int, str, InternalEvent]] = []
    global_idx = 0
    for chunk_path in store.iter_chunks(session_id):
        chunk_name = chunk_path.name
        with chunk_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    global_idx += 1
                    continue
                if global_idx >= start_from_idx:
                    try:
                        results.append((global_idx, chunk_name, parse_event(json.loads(line))))
                    except Exception as exc:
                        logger.warning(
                            "Skipping malformed event at %s idx %d: %s",
                            chunk_name,
                            global_idx,
                            exc,
                        )
                global_idx += 1
    return results


# ---------------------------------------------------------------------------
# Conversation grouping
# ---------------------------------------------------------------------------


async def _insert_conversation(
    session_id: str,
    events: list[tuple[int, str, InternalEvent]],
    db: ConversationsDB,
) -> None:
    """Insert one conversation record for the given event slice."""
    msg_count = sum(1 for _, _, ev in events if ev.event_type == EventType.MESSAGE)
    if msg_count == 0:
        return
    start_idx = events[0][0]
    end_idx = events[-1][0]
    first_ts: datetime = events[0][2].timestamp
    chunk_first: str = events[0][1]
    chunk_last: str = events[-1][1]
    await db.insert_conversation(
        conversation_id=str(uuid.uuid4()),
        session_id=session_id,
        chunk_file_first=chunk_first,
        chunk_file_last=chunk_last,
        event_index_start=start_idx,
        event_index_end=end_idx,
        created_at=first_ts,
        message_count=msg_count,
    )


async def _analyze_by_turn_ends(
    session_id: str,
    events: list[tuple[int, str, InternalEvent]],
    turn_ends: list[datetime],
    db: ConversationsDB,
) -> int:
    """Group *events* into conversations using ``turn_duration`` boundary timestamps."""
    sorted_ends = sorted(turn_ends)
    remaining = list(events)
    new_rows = 0

    for turn_end in sorted_ends:
        turn_events = [
            (idx, cn, ev) for idx, cn, ev in remaining if ev.timestamp <= turn_end
        ]
        if not turn_events:
            continue
        remaining = [(idx, cn, ev) for idx, cn, ev in remaining if ev.timestamp > turn_end]
        before = await _count_conversations(db, session_id)
        await _insert_conversation(session_id, turn_events, db)
        after = await _count_conversations(db, session_id)
        new_rows += after - before

    return new_rows


async def _count_conversations(db: ConversationsDB, session_id: str) -> int:
    stats = await db.get_session_stats(session_id)
    return int(stats["conversation_count"])


async def _analyze_as_single_conversation(
    session_id: str,
    events: list[tuple[int, str, InternalEvent]],
    db: ConversationsDB,
) -> int:
    """Treat all events as one conversation (fallback for sessions without turn markers)."""
    before = await _count_conversations(db, session_id)
    await _insert_conversation(session_id, events, db)
    after = await _count_conversations(db, session_id)
    return after - before


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def analyze_transcript_session(
    session_id: str,
    transcript_path: Optional[Path],
    store: EventStore,
    db: ConversationsDB,
) -> int:
    """Create conversation records by matching event-store events to transcript turn boundaries.

    Reads ``system/turn_duration`` entries from *transcript_path* (when
    provided and present) to determine conversation end times, then groups
    unindexed events from the event store into conversation records in *db*.

    Falls back to treating all unindexed events as a single conversation when
    no turn_duration markers exist or *transcript_path* is None / missing.

    Args:
        session_id: Target session.
        transcript_path: Path to the Claude CLI transcript JSONL, or None.
        store: Source EventStore (read-only).
        db: Open ConversationsDB to write index rows into.

    Returns:
        Number of new conversation rows inserted.
    """
    last_indexed = await db.get_last_indexed_event(session_id)
    start_from = (last_indexed + 1) if last_indexed is not None else 0

    events = _collect_unindexed_events(store, session_id, start_from)
    if not events:
        logger.info("No unindexed events for session %s", session_id)
        return 0

    turn_ends: list[datetime] = []
    if transcript_path is not None and transcript_path.exists():
        turn_ends = read_turn_end_times(transcript_path)

    if turn_ends:
        logger.info(
            "Analyzing session %s: %d events, %d turn boundaries",
            session_id,
            len(events),
            len(turn_ends),
        )
        return await _analyze_by_turn_ends(session_id, events, turn_ends, db)

    logger.info(
        "Analyzing session %s: %d events, no turn boundaries — using single-conversation fallback",
        session_id,
        len(events),
    )
    return await _analyze_as_single_conversation(session_id, events, db)
