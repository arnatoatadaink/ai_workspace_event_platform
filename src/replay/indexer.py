"""Replay Engine: Conversation boundary indexer.

Reads JSONL chunks from EventStore and writes one row per completed
(STOP-terminated) conversation into ConversationsDB.

Trailing events with no terminating StopEvent are skipped; they will be
indexed when their StopEvent arrives on the next run.

``created_at`` for each conversation is set to the first event's timestamp.
Zero-event conversations (a StopEvent immediately following a reset) are
skipped.
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


def _new_conversation_id() -> str:
    return str(uuid.uuid4())


def _read_chunk(chunk_path: Path) -> list[InternalEvent]:
    """Parse all valid events from a JSONL chunk file, skipping malformed lines."""
    events: list[InternalEvent] = []
    with chunk_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(parse_event(json.loads(line)))
            except Exception as exc:
                logger.warning(
                    "Skipping malformed event at %s line %d: %s", chunk_path, lineno, exc
                )
    return events


async def index_session(
    session_id: str,
    store: EventStore,
    db: ConversationsDB,
    *,
    chunks: Optional[list[Path]] = None,
    global_idx_start: int = 0,
) -> int:
    """Index unprocessed, STOP-terminated conversations into the DB.

    Reads all chunks for *session_id* (or only *chunks* when provided),
    detects conversation boundaries (each conversation ends at a StopEvent),
    and inserts one row per new conversation into the ``conversations`` table.

    Uses ``get_last_indexed_event`` to resume incrementally — global event
    indices up to and including the previously indexed ``event_index_end``
    are skipped so no duplicate rows are inserted.

    Args:
        session_id: The session to index.
        store: Source EventStore (read-only).
        db: Open ConversationsDB to write index rows into.
        chunks: Optional pre-filtered chunk list (from detect_unprocessed_chunks).
            Pass alongside *global_idx_start* so indices are globally correct.
        global_idx_start: Starting global event index when *chunks* is provided.

    Returns:
        Number of new conversation rows inserted.
    """
    last_indexed: Optional[int] = await db.get_last_indexed_event(session_id)

    # ── per-conversation accumulation state ───────────────────────────────
    conv_start_idx: Optional[int] = None
    conv_chunk_first: Optional[str] = None
    conv_chunk_last: Optional[str] = None
    conv_first_ts: Optional[datetime] = None
    conv_message_count: int = 0

    global_idx: int = global_idx_start
    new_rows: int = 0

    chunk_list = chunks if chunks is not None else store.iter_chunks(session_id)
    for chunk_path in chunk_list:
        chunk_name = chunk_path.name
        for event in _read_chunk(chunk_path):
            if last_indexed is not None and global_idx <= last_indexed:
                global_idx += 1
                continue

            # ── open a new conversation on first unindexed event ─────────
            if conv_start_idx is None:
                conv_start_idx = global_idx
                conv_chunk_first = chunk_name
                conv_chunk_last = chunk_name
                conv_first_ts = event.timestamp
                conv_message_count = 0

            conv_chunk_last = chunk_name
            if event.event_type == EventType.MESSAGE:
                conv_message_count += 1

            # ── close conversation on StopEvent ───────────────────────────
            if event.event_type == EventType.STOP:
                # Skip zero-event conversations (STOP is the only event)
                if conv_start_idx < global_idx:
                    assert conv_chunk_first is not None
                    assert conv_chunk_last is not None
                    assert conv_first_ts is not None
                    await db.insert_conversation(
                        conversation_id=_new_conversation_id(),
                        session_id=session_id,
                        chunk_file_first=conv_chunk_first,
                        chunk_file_last=conv_chunk_last,
                        event_index_start=conv_start_idx,
                        event_index_end=global_idx,
                        created_at=conv_first_ts,
                        message_count=conv_message_count,
                    )
                    new_rows += 1

                conv_start_idx = None
                conv_chunk_first = None
                conv_chunk_last = None
                conv_first_ts = None
                conv_message_count = 0

            global_idx += 1

    return new_rows
