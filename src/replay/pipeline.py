"""Replay Engine: Summary & Topic Pipeline.

Periodic orchestrator that indexes, summarizes, and extracts topics across all
sessions in the EventStore. Wraps run_incremental_update() in a multi-session
loop with per-session error isolation.

Usage::

    pipeline = SummaryTopicPipeline(
        store=event_store,
        db=conversations_db,
        snapshot_store=snapshot_store,
        summarizer=OpenAICompatBackend(),
        interval_seconds=60.0,
    )
    await pipeline.run_once()                         # single pass
    task = asyncio.create_task(pipeline.run_loop())   # background loop
    ...
    pipeline.stop()
    await task
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.replay.db import ConversationsDB
from src.replay.snapshot import run_incremental_update
from src.replay.snapshot_store import SnapshotStore
from src.replay.summarizer import SummarizerBackend
from src.store.event_store import EventStore

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 60.0  # seconds


class SummaryTopicPipeline:
    """Multi-session periodic pipeline for summary and topic extraction.

    Each call to run_once() discovers all sessions from the EventStore, then
    for each session runs: chunk-diff → index new conversations → summarize →
    snapshot.  Sessions that raise exceptions are logged and skipped so one
    bad session cannot block the rest.

    Args:
        store: Source EventStore (read-only by this pipeline).
        db: Open ConversationsDB for conversation index and summary persistence.
        snapshot_store: Open SnapshotStore for snapshot persistence.
        summarizer: Optional LLM backend. When None, summarization is skipped.
        interval_seconds: Seconds to wait between pipeline passes in run_loop().
    """

    def __init__(
        self,
        store: EventStore,
        db: ConversationsDB,
        snapshot_store: SnapshotStore,
        summarizer: Optional[SummarizerBackend] = None,
        interval_seconds: float = _DEFAULT_INTERVAL,
    ) -> None:
        self._store = store
        self._db = db
        self._snapshot_store = snapshot_store
        self._summarizer = summarizer
        self._interval = interval_seconds
        self._running = False
        self._stop_event: Optional[asyncio.Event] = None

    async def run_once(self) -> list[str]:
        """Process all known sessions once.

        For each session discovered in the EventStore, runs the full incremental
        update: new-chunk detection → conversation indexing → summarization →
        snapshot persistence.

        Returns:
            List of session IDs that had at least one new conversation indexed.
        """
        updated: list[str] = []
        for session_id in self._store.list_sessions():
            try:
                metadata = await run_incremental_update(
                    session_id,
                    self._store,
                    self._db,
                    self._snapshot_store,
                    self._summarizer,
                )
                if metadata is not None:
                    updated.append(session_id)
                    logger.info(
                        "Session %s: snapshot updated (%d events indexed).",
                        session_id,
                        metadata.context_length.event_count,
                    )
                else:
                    logger.debug("Session %s: no new conversations.", session_id)
            except Exception as exc:
                logger.error("Pipeline error for session %s: %s", session_id, exc)
        return updated

    async def run_loop(self) -> None:
        """Run pipeline passes in a loop until stop() is called.

        Designed to be launched as an asyncio background task::

            task = asyncio.create_task(pipeline.run_loop())
            ...
            pipeline.stop()
            await task
        """
        self._running = True
        self._stop_event = asyncio.Event()
        logger.info("Summary/Topic pipeline started (interval=%.1fs).", self._interval)
        try:
            while self._running:
                updated = await self.run_once()
                if updated:
                    logger.info(
                        "Pipeline pass complete: %d session(s) updated.", len(updated)
                    )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._interval
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("Summary/Topic pipeline stopped.")

    def stop(self) -> None:
        """Signal run_loop() to exit after the current pass finishes."""
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
