"""Tests for src/replay/db.py"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from src.replay.db import ConversationsDB


def _ts(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def _cid() -> str:
    return str(uuid.uuid4())


async def _insert(
    db: ConversationsDB,
    *,
    session_id: str = "sess_a",
    created_at: datetime,
    event_index_start: int = 0,
    event_index_end: int = 9,
    message_count: int = 2,
    chunk_first: str = "events_0001.jsonl",
    chunk_last: str = "events_0001.jsonl",
) -> str:
    cid = _cid()
    await db.insert_conversation(
        conversation_id=cid,
        session_id=session_id,
        chunk_file_first=chunk_first,
        chunk_file_last=chunk_last,
        event_index_start=event_index_start,
        event_index_end=event_index_end,
        created_at=created_at,
        message_count=message_count,
    )
    return cid


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> ConversationsDB:
    async with ConversationsDB(db_path=tmp_path / "replay.db") as database:
        yield database


class TestInitSchema:
    @pytest.mark.asyncio
    async def test_init_schema_creates_tables(self, tmp_path: Path) -> None:
        async with ConversationsDB(tmp_path / "r.db") as db:
            cur = await db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"
            )
            row = await cur.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_init_schema_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "r.db"
        async with ConversationsDB(path):
            pass
        async with ConversationsDB(path):
            pass

    @pytest.mark.asyncio
    async def test_init_schema_creates_index(self, tmp_path: Path) -> None:
        async with ConversationsDB(tmp_path / "r.db") as db:
            cur = await db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_conversations_session_created'"
            )
            row = await cur.fetchone()
            assert row is not None


class TestInsertAndQuery:
    @pytest.mark.asyncio
    async def test_insert_and_retrieve(self, db: ConversationsDB) -> None:
        cid = await _insert(db, created_at=_ts(0))
        rows = await db.get_latest_conversations("sess_a", limit=10)
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == cid
        assert rows[0]["session_id"] == "sess_a"
        assert rows[0]["chunk_file_first"] == "events_0001.jsonl"

    @pytest.mark.asyncio
    async def test_get_latest_conversations_newest_first(self, db: ConversationsDB) -> None:
        cid_old = await _insert(db, created_at=_ts(0))
        cid_new = await _insert(db, created_at=_ts(60))
        rows = await db.get_latest_conversations("sess_a", limit=10)
        assert rows[0]["conversation_id"] == cid_new
        assert rows[1]["conversation_id"] == cid_old

    @pytest.mark.asyncio
    async def test_get_latest_conversations_respects_limit(self, db: ConversationsDB) -> None:
        for i in range(5):
            await _insert(db, created_at=_ts(i * 10))
        rows = await db.get_latest_conversations("sess_a", limit=3)
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_get_latest_conversations_empty_session(self, db: ConversationsDB) -> None:
        rows = await db.get_latest_conversations("no_such_session", limit=10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_get_latest_conversations_isolates_sessions(self, db: ConversationsDB) -> None:
        await _insert(db, session_id="sess_a", created_at=_ts(0))
        await _insert(db, session_id="sess_b", created_at=_ts(0))
        rows = await db.get_latest_conversations("sess_a", limit=10)
        assert all(r["session_id"] == "sess_a" for r in rows)
        assert len(rows) == 1


class TestCursorPaging:
    @pytest.mark.asyncio
    async def test_cursor_paging_returns_older_rows(self, db: ConversationsDB) -> None:
        cid_1 = await _insert(db, created_at=_ts(0))
        cid_2 = await _insert(db, created_at=_ts(30))
        cid_3 = await _insert(db, created_at=_ts(60))

        first_page = await db.get_latest_conversations("sess_a", limit=1)
        assert first_page[0]["conversation_id"] == cid_3

        second_page = await db.get_latest_conversations(
            "sess_a", limit=1, before_conversation_id=cid_3
        )
        assert second_page[0]["conversation_id"] == cid_2

        third_page = await db.get_latest_conversations(
            "sess_a", limit=1, before_conversation_id=cid_2
        )
        assert third_page[0]["conversation_id"] == cid_1

    @pytest.mark.asyncio
    async def test_cursor_paging_unknown_id_returns_empty(self, db: ConversationsDB) -> None:
        await _insert(db, created_at=_ts(0))
        rows = await db.get_latest_conversations(
            "sess_a", limit=10, before_conversation_id="non-existent-id"
        )
        assert rows == []


class TestGetLastIndexedEvent:
    @pytest.mark.asyncio
    async def test_get_last_indexed_event_no_rows(self, db: ConversationsDB) -> None:
        result = await db.get_last_indexed_event("sess_a")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_indexed_event_returns_max(self, db: ConversationsDB) -> None:
        await _insert(db, created_at=_ts(0), event_index_start=0, event_index_end=99)
        await _insert(db, created_at=_ts(60), event_index_start=100, event_index_end=249)
        result = await db.get_last_indexed_event("sess_a")
        assert result == 249

    @pytest.mark.asyncio
    async def test_get_last_indexed_event_isolates_sessions(self, db: ConversationsDB) -> None:
        await _insert(
            db,
            session_id="sess_a",
            created_at=_ts(0),
            event_index_start=0,
            event_index_end=100,
        )
        await _insert(
            db,
            session_id="sess_b",
            created_at=_ts(0),
            event_index_start=0,
            event_index_end=9999,
        )
        result = await db.get_last_indexed_event("sess_a")
        assert result == 100


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager_closes_connection(self, tmp_path: Path) -> None:
        db = ConversationsDB(tmp_path / "r.db")
        async with db:
            assert db._conn is not None
        assert db._conn is None


class TestConversationSummaries:
    @pytest.mark.asyncio
    async def test_summary_table_created(self, tmp_path: Path) -> None:
        async with ConversationsDB(tmp_path / "r.db") as db:
            cur = await db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='conversation_summaries'"
            )
            assert await cur.fetchone() is not None

    @pytest.mark.asyncio
    async def test_insert_and_get_summary(self, db: ConversationsDB) -> None:
        cid = await _insert(db, created_at=_ts(0))
        await db.insert_summary(
            conversation_id=cid,
            summary_short="Short summary.",
            summary_long="Long summary with more detail.",
            topics=["Python", "FastAPI"],
            model_used="gemma-4-31b-it@q6_k",
        )
        row = await db.get_summary(cid)
        assert row is not None
        assert row["conversation_id"] == cid
        assert row["summary_short"] == "Short summary."
        assert row["topics"] == ["Python", "FastAPI"]
        assert row["model_used"] == "gemma-4-31b-it@q6_k"
        assert "generated_at" in row

    @pytest.mark.asyncio
    async def test_get_summary_returns_none_when_missing(self, db: ConversationsDB) -> None:
        cid = await _insert(db, created_at=_ts(0))
        assert await db.get_summary(cid) is None

    @pytest.mark.asyncio
    async def test_insert_summary_replace_on_rerun(self, db: ConversationsDB) -> None:
        cid = await _insert(db, created_at=_ts(0))
        await db.insert_summary(
            conversation_id=cid,
            summary_short="v1",
            summary_long="v1 long",
            topics=["A"],
            model_used="m1",
        )
        await db.insert_summary(
            conversation_id=cid,
            summary_short="v2",
            summary_long="v2 long",
            topics=["B", "C"],
            model_used="m2",
        )
        row = await db.get_summary(cid)
        assert row is not None
        assert row["summary_short"] == "v2"
        assert row["topics"] == ["B", "C"]

    @pytest.mark.asyncio
    async def test_get_unsummarized_returns_conversations_without_summary(
        self, db: ConversationsDB
    ) -> None:
        cid_a = await _insert(db, created_at=_ts(0), event_index_start=0, event_index_end=9)
        cid_b = await _insert(db, created_at=_ts(60), event_index_start=10, event_index_end=19)
        await db.insert_summary(
            conversation_id=cid_a,
            summary_short="done",
            summary_long="done long",
            topics=[],
            model_used="m",
        )
        rows = await db.get_unsummarized_conversations("sess_a")
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == cid_b

    @pytest.mark.asyncio
    async def test_get_unsummarized_empty_when_all_summarized(self, db: ConversationsDB) -> None:
        cid = await _insert(db, created_at=_ts(0))
        await db.insert_summary(
            conversation_id=cid,
            summary_short="s",
            summary_long="l",
            topics=[],
            model_used="m",
        )
        rows = await db.get_unsummarized_conversations("sess_a")
        assert rows == []

    @pytest.mark.asyncio
    async def test_get_unsummarized_ordered_oldest_first(self, db: ConversationsDB) -> None:
        cid_old = await _insert(db, created_at=_ts(0), event_index_start=0, event_index_end=9)
        cid_new = await _insert(db, created_at=_ts(120), event_index_start=10, event_index_end=19)
        rows = await db.get_unsummarized_conversations("sess_a")
        assert rows[0]["conversation_id"] == cid_old
        assert rows[1]["conversation_id"] == cid_new

    @pytest.mark.asyncio
    async def test_topics_json_roundtrip(self, db: ConversationsDB) -> None:
        cid = await _insert(db, created_at=_ts(0))
        topics = ["Python", "FastAPI", "Event Sourcing", "SQLite"]
        await db.insert_summary(
            conversation_id=cid,
            summary_short="s",
            summary_long="l",
            topics=topics,
            model_used="m",
        )
        row = await db.get_summary(cid)
        assert row is not None
        assert row["topics"] == topics
