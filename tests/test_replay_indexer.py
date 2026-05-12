"""Tests for src/replay/indexer.py"""

from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio

from src.replay.db import ConversationsDB
from src.replay.indexer import index_session
from src.schemas.internal_event_v1 import EventSource, MessageEvent, StopEvent, ToolCallEvent
from src.store.event_store import EventStore

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> EventStore:
    """EventStore with chunk_size=3 to exercise multi-chunk scenarios easily."""
    return EventStore(base_path=tmp_path / "sessions", chunk_size=3)


@pytest_asyncio.fixture()
async def db(tmp_path: Path) -> AsyncGenerator[ConversationsDB, None]:
    async with ConversationsDB(db_path=tmp_path / "replay.db") as database:
        yield database


_SID = "sess_test"
_SRC = EventSource.CLAUDE_CLI


def _msg(n: int = 0) -> MessageEvent:
    return MessageEvent(source=_SRC, session_id=_SID, role="user", content=f"msg{n}")


def _stop() -> StopEvent:
    return StopEvent(source=_SRC, session_id=_SID)


def _tool_call() -> ToolCallEvent:
    return ToolCallEvent(
        source=_SRC,
        session_id=_SID,
        tool_name="bash",
        tool_input={"command": "ls"},
        tool_use_id="tu1",
    )


# ── tests ─────────────────────────────────────────────────────────────────────


class TestIndexSessionNoEvents:
    @pytest.mark.asyncio
    async def test_index_session_when_no_events_then_zero(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        count = await index_session(_SID, store, db)
        assert count == 0
        rows = await db.get_latest_conversations(_SID)
        assert rows == []


class TestIndexSessionSingleConversation:
    @pytest.mark.asyncio
    async def test_index_session_when_single_stop_terminated_conversation_then_one_row(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        store.append(_msg(0))
        store.append(_msg(1))
        store.append(_stop())

        count = await index_session(_SID, store, db)
        assert count == 1

        rows = await db.get_latest_conversations(_SID)
        assert len(rows) == 1
        row = rows[0]
        assert row["session_id"] == _SID
        assert row["event_index_start"] == 0
        assert row["event_index_end"] == 2
        assert row["message_count"] == 2

    @pytest.mark.asyncio
    async def test_index_session_when_message_count_then_counts_message_events_only(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        store.append(_msg(0))
        store.append(_tool_call())
        store.append(_msg(1))
        store.append(_stop())

        await index_session(_SID, store, db)

        rows = await db.get_latest_conversations(_SID)
        assert rows[0]["message_count"] == 2  # tool_call not counted

    @pytest.mark.asyncio
    async def test_index_session_when_created_at_then_uses_first_event_timestamp(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        first = _msg(0)
        store.append(first)
        store.append(_stop())

        await index_session(_SID, store, db)

        rows = await db.get_latest_conversations(_SID)
        assert rows[0]["created_at"] == first.timestamp.isoformat()


class TestIndexSessionMultipleConversations:
    @pytest.mark.asyncio
    async def test_index_session_when_two_stops_then_two_rows_with_correct_indices(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        # Conversation 1: indices 0-2
        store.append(_msg(0))
        store.append(_msg(1))
        store.append(_stop())
        # Conversation 2: indices 3-5
        store.append(_msg(2))
        store.append(_msg(3))
        store.append(_stop())

        count = await index_session(_SID, store, db)
        assert count == 2

        rows = await db.get_latest_conversations(_SID, limit=10)
        assert len(rows) == 2
        # newest first
        assert rows[0]["event_index_start"] == 3
        assert rows[0]["event_index_end"] == 5
        assert rows[1]["event_index_start"] == 0
        assert rows[1]["event_index_end"] == 2


class TestIndexSessionTrailingEvents:
    @pytest.mark.asyncio
    async def test_index_session_when_trailing_no_stop_then_skipped(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())
        # trailing events without STOP
        store.append(_msg(1))
        store.append(_msg(2))

        count = await index_session(_SID, store, db)
        assert count == 1  # only the first conversation indexed


class TestIndexSessionChunkSpanning:
    @pytest.mark.asyncio
    async def test_index_session_when_conversation_spans_chunks_then_chunk_first_last_differ(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        # chunk_size=3; write 4 events before STOP so conversation spans 2 chunks
        store.append(_msg(0))
        store.append(_msg(1))
        store.append(_msg(2))  # chunk 1 full (3 events, rotates)
        store.append(_msg(3))  # chunk 2 starts
        store.append(_stop())  # STOP in chunk 2

        await index_session(_SID, store, db)

        rows = await db.get_latest_conversations(_SID)
        assert len(rows) == 1
        row = rows[0]
        assert row["chunk_file_first"] == "events_0001.jsonl"
        assert row["chunk_file_last"] == "events_0002.jsonl"
        assert row["event_index_start"] == 0
        assert row["event_index_end"] == 4


class TestIndexSessionIncremental:
    @pytest.mark.asyncio
    async def test_index_session_when_called_twice_then_no_duplicates(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())

        first = await index_session(_SID, store, db)
        assert first == 1

        second = await index_session(_SID, store, db)
        assert second == 0

        rows = await db.get_latest_conversations(_SID)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_index_session_when_new_conversation_added_then_only_new_row_inserted(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())

        await index_session(_SID, store, db)

        store.append(_msg(1))
        store.append(_msg(2))
        store.append(_stop())

        count = await index_session(_SID, store, db)
        assert count == 1

        rows = await db.get_latest_conversations(_SID, limit=10)
        assert len(rows) == 2
        assert rows[0]["event_index_start"] == 2
        assert rows[0]["event_index_end"] == 4

    @pytest.mark.asyncio
    async def test_index_session_when_trailing_then_indexed_after_stop_arrives(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())
        store.append(_msg(1))  # trailing, no STOP yet

        first = await index_session(_SID, store, db)
        assert first == 1

        store.append(_stop())  # STOP arrives

        second = await index_session(_SID, store, db)
        assert second == 1

        rows = await db.get_latest_conversations(_SID, limit=10)
        assert len(rows) == 2


class TestIndexSessionZeroEventConversation:
    @pytest.mark.asyncio
    async def test_index_session_when_stop_only_conversation_then_skipped(
        self, store: EventStore, db: ConversationsDB
    ) -> None:
        store.append(_msg(0))
        store.append(_stop())
        store.append(_stop())  # zero-event "conversation"

        count = await index_session(_SID, store, db)
        assert count == 1  # second STOP alone is skipped

        rows = await db.get_latest_conversations(_SID)
        assert len(rows) == 1
