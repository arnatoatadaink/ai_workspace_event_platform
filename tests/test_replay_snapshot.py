"""Tests for src/replay/snapshot.py"""

from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio

from src.replay.db import ConversationsDB
from src.replay.snapshot import (
    ContextLength,
    EventRange,
    SnapshotMetadata,
    SnapshotStore,
    TopicSummary,
    detect_unprocessed_chunks,
    run_incremental_update,
)
from src.schemas.internal_event_v1 import EventSource, MessageEvent, StopEvent
from src.store.event_store import EventStore

# ── shared constants ──────────────────────────────────────────────────────────

_SID = "sess_snap_test"
_SRC = EventSource.CLAUDE_CLI


def _msg(n: int = 0) -> MessageEvent:
    return MessageEvent(source=_SRC, session_id=_SID, role="user", content=f"msg{n}")


def _stop() -> StopEvent:
    return StopEvent(source=_SRC, session_id=_SID)


def _make_metadata() -> SnapshotMetadata:
    return SnapshotMetadata(
        event_range=EventRange(
            chunk_first="events_0001.jsonl",
            chunk_last="events_0002.jsonl",
            event_index_start=0,
            event_index_end=199,
        ),
        context_length=ContextLength(event_count=200, estimated_tokens=30000),
        chunk_count=2,
        topic_summary=TopicSummary(topics=["Python", "FastAPI"]),
    )


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> EventStore:
    """EventStore with chunk_size=3 for easy multi-chunk tests."""
    return EventStore(base_path=tmp_path / "sessions", chunk_size=3)


@pytest_asyncio.fixture()
async def db(tmp_path: Path) -> AsyncGenerator[ConversationsDB, None]:
    async with ConversationsDB(db_path=tmp_path / "replay.db") as database:
        yield database


@pytest_asyncio.fixture()
async def snap_store(tmp_path: Path) -> AsyncGenerator[SnapshotStore, None]:
    async with SnapshotStore(
        snap_dir=tmp_path / "snapshots",
        db_path=tmp_path / "replay.db",
    ) as ss:
        yield ss


# ── SnapshotMetadata ──────────────────────────────────────────────────────────


class TestSnapshotMetadata:
    def test_snapshot_metadata_when_serialized_then_round_trips(self) -> None:
        meta = _make_metadata()
        restored = SnapshotMetadata.model_validate_json(meta.model_dump_json())
        assert restored.snapshot_id == meta.snapshot_id
        assert restored.event_range.event_index_end == 199
        assert restored.topic_summary.topics == ["Python", "FastAPI"]

    def test_snapshot_metadata_when_umap_none_then_omitted_from_json(self) -> None:
        meta = _make_metadata()
        assert meta.topic_summary.umap_projection is None
        data = meta.model_dump()
        assert data["topic_summary"]["umap_projection"] is None

    def test_snapshot_metadata_when_umap_provided_then_preserved(self) -> None:
        meta = SnapshotMetadata(
            event_range=EventRange(
                chunk_first="events_0001.jsonl",
                chunk_last="events_0001.jsonl",
                event_index_start=0,
                event_index_end=9,
            ),
            context_length=ContextLength(event_count=10, estimated_tokens=1500),
            chunk_count=1,
            topic_summary=TopicSummary(
                topics=["UMAP"],
                umap_projection=[[0.1, 0.2], [0.3, 0.4]],
            ),
        )
        restored = SnapshotMetadata.model_validate_json(meta.model_dump_json())
        assert restored.topic_summary.umap_projection == [[0.1, 0.2], [0.3, 0.4]]

    def test_snapshot_metadata_when_default_factory_then_unique_ids(self) -> None:
        a = _make_metadata()
        b = _make_metadata()
        assert a.snapshot_id != b.snapshot_id


# ── SnapshotStore save / load ─────────────────────────────────────────────────


class TestSnapshotStoreSaveLoad:
    @pytest.mark.asyncio
    async def test_snapshot_store_when_saved_then_file_exists(
        self, snap_store: SnapshotStore, tmp_path: Path
    ) -> None:
        meta = _make_metadata()
        file_path = await snap_store.save(_SID, meta)
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_snapshot_store_when_loaded_then_matches_saved(
        self, snap_store: SnapshotStore
    ) -> None:
        meta = _make_metadata()
        await snap_store.save(_SID, meta)
        loaded = await snap_store.load(_SID, meta.snapshot_id)
        assert loaded is not None
        assert loaded.snapshot_id == meta.snapshot_id
        assert loaded.event_range.event_index_end == 199
        assert loaded.chunk_count == 2

    @pytest.mark.asyncio
    async def test_snapshot_store_when_load_unknown_id_then_none(
        self, snap_store: SnapshotStore
    ) -> None:
        result = await snap_store.load(_SID, "nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_snapshot_store_when_multiple_saves_then_files_archived(
        self, snap_store: SnapshotStore, tmp_path: Path
    ) -> None:
        meta1 = _make_metadata()
        meta2 = _make_metadata()
        await snap_store.save(_SID, meta1)
        await snap_store.save(_SID, meta2)
        snap_dir = tmp_path / "snapshots" / _SID
        files = list(snap_dir.glob("*.json"))
        assert len(files) == 2


class TestSnapshotStoreGetLatest:
    @pytest.mark.asyncio
    async def test_snapshot_store_when_no_snapshots_then_none(
        self, snap_store: SnapshotStore
    ) -> None:
        result = await snap_store.get_latest(_SID)
        assert result is None

    @pytest.mark.asyncio
    async def test_snapshot_store_when_one_snapshot_then_returns_it(
        self, snap_store: SnapshotStore
    ) -> None:
        meta = _make_metadata()
        await snap_store.save(_SID, meta)
        latest = await snap_store.get_latest(_SID)
        assert latest is not None
        assert latest.snapshot_id == meta.snapshot_id

    @pytest.mark.asyncio
    async def test_snapshot_store_when_two_snapshots_then_returns_newer(
        self, snap_store: SnapshotStore
    ) -> None:
        old = SnapshotMetadata(
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            event_range=EventRange(
                chunk_first="events_0001.jsonl",
                chunk_last="events_0001.jsonl",
                event_index_start=0,
                event_index_end=9,
            ),
            context_length=ContextLength(event_count=10, estimated_tokens=1500),
            chunk_count=1,
            topic_summary=TopicSummary(topics=[]),
        )
        new = SnapshotMetadata(
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            event_range=EventRange(
                chunk_first="events_0001.jsonl",
                chunk_last="events_0002.jsonl",
                event_index_start=0,
                event_index_end=99,
            ),
            context_length=ContextLength(event_count=100, estimated_tokens=15000),
            chunk_count=2,
            topic_summary=TopicSummary(topics=["Python"]),
        )
        await snap_store.save(_SID, old)
        await snap_store.save(_SID, new)
        latest = await snap_store.get_latest(_SID)
        assert latest is not None
        assert latest.snapshot_id == new.snapshot_id


# ── detect_unprocessed_chunks ─────────────────────────────────────────────────


class TestDetectUnprocessedChunks:
    def test_detect_when_no_chunks_then_empty(self, store: EventStore) -> None:
        result, offset = detect_unprocessed_chunks(_SID, store, last_indexed=None)
        assert result == []
        assert offset == 0

    def test_detect_when_last_indexed_none_then_all_chunks_returned(
        self, store: EventStore
    ) -> None:
        # chunk_size=3; write 6 events → 2 chunks
        for _ in range(6):
            store.append(_msg())
        chunks, offset = detect_unprocessed_chunks(_SID, store, last_indexed=None)
        assert len(chunks) == 2
        assert offset == 0

    def test_detect_when_all_indexed_then_empty(self, store: EventStore) -> None:
        # 6 events in 2 chunks (3 each); last_indexed covers all
        for _ in range(6):
            store.append(_msg())
        chunks, offset = detect_unprocessed_chunks(_SID, store, last_indexed=5)
        assert chunks == []

    def test_detect_when_first_chunk_processed_then_returns_second(self, store: EventStore) -> None:
        # chunk 1: events 0-2, chunk 2: events 3-5
        for _ in range(6):
            store.append(_msg())
        # last_indexed=2 → chunk 1 (0-2) fully processed, chunk 2 unprocessed
        chunks, offset = detect_unprocessed_chunks(_SID, store, last_indexed=2)
        assert len(chunks) == 1
        assert chunks[0].name == "events_0002.jsonl"
        assert offset == 3

    def test_detect_when_partial_first_chunk_then_returns_first(self, store: EventStore) -> None:
        # 4 events: chunk 1 (3 events), chunk 2 (1 event); last_indexed=1
        for _ in range(4):
            store.append(_msg())
        # last_indexed=1 → event 2 in chunk 1 is unprocessed
        chunks, offset = detect_unprocessed_chunks(_SID, store, last_indexed=1)
        assert len(chunks) == 2  # both chunks needed
        assert chunks[0].name == "events_0001.jsonl"
        assert offset == 0

    def test_detect_offset_matches_skipped_event_count(self, store: EventStore) -> None:
        # 9 events → 3 chunks (3 each); last_indexed=5 → skip chunks 0001 and 0002
        for _ in range(9):
            store.append(_msg())
        chunks, offset = detect_unprocessed_chunks(_SID, store, last_indexed=5)
        assert len(chunks) == 1
        assert chunks[0].name == "events_0003.jsonl"
        assert offset == 6  # events 0-5 are in skipped chunks


# ── run_incremental_update ────────────────────────────────────────────────────


class TestRunIncrementalUpdate:
    @pytest.mark.asyncio
    async def test_run_when_no_events_then_none(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
    ) -> None:
        result = await run_incremental_update(_SID, store, db, snap_store)
        assert result is None

    @pytest.mark.asyncio
    async def test_run_when_no_stop_event_then_none(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
    ) -> None:
        store.append(_msg(0))
        store.append(_msg(1))  # no StopEvent → no complete conversation
        result = await run_incremental_update(_SID, store, db, snap_store)
        assert result is None

    @pytest.mark.asyncio
    async def test_run_when_one_conversation_then_snapshot_created(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
    ) -> None:
        store.append(_msg(0))
        store.append(_msg(1))
        store.append(_stop())

        result = await run_incremental_update(_SID, store, db, snap_store)

        assert result is not None
        assert result.event_range.event_index_start == 0
        assert result.event_range.event_index_end == 2
        assert result.context_length.event_count == 3
        assert result.chunk_count == 1

    @pytest.mark.asyncio
    async def test_run_when_called_twice_then_second_returns_none_if_no_new_chunks(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())

        first = await run_incremental_update(_SID, store, db, snap_store)
        assert first is not None

        second = await run_incremental_update(_SID, store, db, snap_store)
        assert second is None

    @pytest.mark.asyncio
    async def test_run_when_new_conversation_added_then_snapshot_updated(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
    ) -> None:
        # First run
        store.append(_msg(0))
        store.append(_stop())
        await run_incremental_update(_SID, store, db, snap_store)

        # Add second conversation
        store.append(_msg(1))
        store.append(_msg(2))
        store.append(_stop())

        second = await run_incremental_update(_SID, store, db, snap_store)
        assert second is not None
        # event_range should now cover both conversations (0-4)
        assert second.event_range.event_index_end == 4

    @pytest.mark.asyncio
    async def test_run_when_snapshot_saved_then_get_latest_returns_it(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())

        result = await run_incremental_update(_SID, store, db, snap_store)
        assert result is not None

        latest = await snap_store.get_latest(_SID)
        assert latest is not None
        assert latest.snapshot_id == result.snapshot_id

    @pytest.mark.asyncio
    async def test_run_when_no_summarizer_then_topics_empty(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())

        result = await run_incremental_update(_SID, store, db, snap_store, summarizer=None)
        assert result is not None
        assert result.topic_summary.topics == []
