"""Replay Engine: Snapshot orchestration — chunk-tail diff + incremental update.

Public surface (re-exported for callers)::

    from src.replay.snapshot import (
        SnapshotMetadata, EventRange, ContextLength, TopicSummary,  # models
        SnapshotStore,                                               # storage
        detect_unprocessed_chunks,                                   # diff util
        run_incremental_update,                                      # orchestrator
    )

Lifecycle::

    new chunks arrive
      → detect_unprocessed_chunks()   # chunk-tail reverse diff
      → index_session()               # conversation boundary detection
      → summarize_conversation()      # LLM summary (optional)
      → SnapshotStore.save()          # persist metadata
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.replay.db import ConversationsDB
from src.replay.indexer import index_session
from src.replay.snapshot_models import (  # re-export
    ContextLength,
    EventRange,
    SnapshotMetadata,
    TopicSummary,
)
from src.replay.snapshot_store import SnapshotStore  # re-export
from src.replay.summarizer import SummarizerBackend, summarize_conversation
from src.store.event_store import EventStore, count_chunk_lines

__all__ = [
    "ContextLength",
    "EventRange",
    "SnapshotMetadata",
    "SnapshotStore",
    "TopicSummary",
    "detect_unprocessed_chunks",
    "run_incremental_update",
]

logger = logging.getLogger(__name__)


def detect_unprocessed_chunks(
    session_id: str,
    store: EventStore,
    last_indexed: Optional[int],
) -> tuple[list[Path], int]:
    """Return ``(chunks, global_idx_offset)`` for unprocessed events.

    Walks chunk files oldest→newest using cheap line counts (no JSON parsing)
    to find the boundary.  All chunks whose entire event range lies at or
    before *last_indexed* are skipped.

    Pass the returned values directly to ``index_session`` as ``chunks`` and
    ``global_idx_start`` to avoid re-reading fully-indexed chunk files.

    Args:
        session_id: Target session.
        store: Source EventStore (read-only).
        last_indexed: Highest global event index already in the DB, or None.

    Returns:
        Tuple of ``(unprocessed_chunks, global_idx_offset)``.
        An empty chunk list means nothing new to process.
    """
    chunks = store.iter_chunks(session_id)
    if not chunks or last_indexed is None:
        return chunks, 0

    cumulative = 0
    for i, path in enumerate(chunks):
        lines = count_chunk_lines(path)
        if cumulative + lines - 1 > last_indexed:
            return chunks[i:], cumulative
        cumulative += lines

    return [], cumulative  # all chunks fully processed


async def run_incremental_update(
    session_id: str,
    store: EventStore,
    db: ConversationsDB,
    snapshot_store: SnapshotStore,
    summarizer: Optional[SummarizerBackend] = None,
) -> Optional[SnapshotMetadata]:
    """Index new events, summarize, and persist a snapshot.

    Steps:

    1. Detect unprocessed chunks (chunk-tail reverse diff).
    2. Index new STOP-terminated conversations via ``index_session``.
    3. Summarize new conversations (skipped when *summarizer* is None).
    4. Build ``SnapshotMetadata`` from aggregated DB state and persist.

    Args:
        session_id: Target session.
        store: Source EventStore (read-only).
        db: Open ConversationsDB (conversation index + summaries).
        snapshot_store: Open SnapshotStore (snapshot persistence).
        summarizer: Optional LLM backend; step 3 is skipped if None.

    Returns:
        The new ``SnapshotMetadata``, or ``None`` if nothing was indexed.
    """
    # Step 1: chunk-tail reverse diff
    last_indexed = await db.get_last_indexed_event(session_id)
    new_chunks, offset = detect_unprocessed_chunks(session_id, store, last_indexed)
    if not new_chunks:
        logger.info("No new chunks for session %s; skipping update.", session_id)
        return None

    # Step 2: index only the new chunks (skips old ones entirely)
    new_count = await index_session(
        session_id, store, db, chunks=new_chunks, global_idx_start=offset
    )
    if new_count == 0:
        logger.info("No complete conversations in new chunks for session %s.", session_id)
        return None

    # Step 3: summarize newly indexed conversations
    if summarizer is not None:
        for row in await db.get_unsummarized_conversations(session_id):
            try:
                await summarize_conversation(row, store, db, summarizer)
            except Exception as exc:
                logger.warning("Summarization failed for %s: %s", row["conversation_id"], exc)

    # Step 4: build and persist snapshot
    er_row = await snapshot_store._get_session_event_range(session_id)
    if er_row is None:
        return None

    topics = await snapshot_store._get_all_topics(session_id)
    all_chunks = store.iter_chunks(session_id)
    event_count = er_row["event_index_end"] - er_row["event_index_start"] + 1

    metadata = SnapshotMetadata(
        event_range=EventRange(**er_row),
        context_length=ContextLength(
            event_count=event_count,
            estimated_tokens=event_count * 150,  # rough heuristic
        ),
        chunk_count=len(all_chunks),
        topic_summary=TopicSummary(topics=topics),
    )
    await snapshot_store.save(session_id, metadata)
    return metadata
