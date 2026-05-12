"""Tests for GET /sessions/{session_id}/conversations and
GET /sessions/{session_id}/topics/active endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.adapters.base import AdapterPlugin
from src.api.main import app
from src.api.routers.conversations import _compute_active_topics
from src.replay.db import ConversationsDB
from src.store.event_store import EventStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _ts(offset_seconds: int = 0) -> datetime:
    return _BASE_TS + timedelta(seconds=offset_seconds)


def _cid() -> str:
    return str(uuid.uuid4())


async def _insert_conv(
    db: ConversationsDB,
    *,
    session_id: str = "sess_a",
    created_at: datetime,
    event_index_start: int = 0,
    event_index_end: int = 9,
    message_count: int = 2,
) -> str:
    cid = _cid()
    await db.insert_conversation(
        conversation_id=cid,
        session_id=session_id,
        chunk_file_first="events_0001.jsonl",
        chunk_file_last="events_0001.jsonl",
        event_index_start=event_index_start,
        event_index_end=event_index_end,
        created_at=created_at,
        message_count=message_count,
    )
    return cid


async def _insert_summary(
    db: ConversationsDB,
    conversation_id: str,
    topics: list[str],
    summary_short: str = "short summary",
) -> None:
    await db.insert_summary(
        conversation_id=conversation_id,
        summary_short=summary_short,
        summary_long="long summary",
        topics=topics,
        model_used="test-model",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_store(tmp_path: Path) -> EventStore:
    return EventStore(base_path=tmp_path / "sessions")


@pytest_asyncio.fixture()
async def db(tmp_path: Path) -> AsyncGenerator[ConversationsDB, None]:
    async with ConversationsDB(db_path=tmp_path / "replay.db") as database:
        yield database


@pytest_asyncio.fixture()
async def client(
    tmp_store: EventStore,
    tmp_path: Path,
) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client wired to isolated store + DB."""
    _db = ConversationsDB(db_path=tmp_path / "test.db")
    await _db.connect()

    stub_adapter = MagicMock(spec=AdapterPlugin)
    stub_adapter.source_name = "claude_cli"
    stub_adapter.parse.return_value = []

    app.state.store = tmp_store
    app.state.db = _db
    app.state.adapters = {"claude_cli": stub_adapter}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await _db.close()


# ---------------------------------------------------------------------------
# DB unit tests: get_latest_conversations_with_summaries_cursor
# ---------------------------------------------------------------------------


class TestGetLatestConversationsWithSummariesCursor:
    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_session(self, db: ConversationsDB) -> None:
        rows = await db.get_latest_conversations_with_summaries_cursor("no_such", limit=10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_returns_conversation_without_summary(self, db: ConversationsDB) -> None:
        cid = await _insert_conv(db, created_at=_ts(0))
        rows = await db.get_latest_conversations_with_summaries_cursor("sess_a", limit=10)
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == cid
        assert rows[0]["summary_short"] is None
        assert rows[0]["topics"] is None

    @pytest.mark.asyncio
    async def test_includes_summary_when_present(self, db: ConversationsDB) -> None:
        cid = await _insert_conv(db, created_at=_ts(0))
        await _insert_summary(db, cid, topics=["FastAPI", "SQLite"])
        rows = await db.get_latest_conversations_with_summaries_cursor("sess_a", limit=10)
        assert rows[0]["summary_short"] == "short summary"
        assert rows[0]["topics"] == ["FastAPI", "SQLite"]

    @pytest.mark.asyncio
    async def test_orders_newest_first(self, db: ConversationsDB) -> None:
        cid_old = await _insert_conv(db, created_at=_ts(0))
        cid_new = await _insert_conv(db, created_at=_ts(10))
        rows = await db.get_latest_conversations_with_summaries_cursor("sess_a", limit=10)
        assert rows[0]["conversation_id"] == cid_new
        assert rows[1]["conversation_id"] == cid_old

    @pytest.mark.asyncio
    async def test_limit_respected(self, db: ConversationsDB) -> None:
        for i in range(5):
            await _insert_conv(db, created_at=_ts(i))
        rows = await db.get_latest_conversations_with_summaries_cursor("sess_a", limit=3)
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_cursor_paging_returns_older_rows(self, db: ConversationsDB) -> None:
        cids = []
        for i in range(5):
            cids.append(await _insert_conv(db, created_at=_ts(i * 10)))
        # newest-first: cids[4], cids[3], cids[2], cids[1], cids[0]
        first_page = await db.get_latest_conversations_with_summaries_cursor("sess_a", limit=2)
        assert first_page[0]["conversation_id"] == cids[4]
        cursor = first_page[-1]["conversation_id"]
        second_page = await db.get_latest_conversations_with_summaries_cursor(
            "sess_a", limit=2, before_conversation_id=cursor
        )
        assert second_page[0]["conversation_id"] == cids[2]

    @pytest.mark.asyncio
    async def test_cursor_unknown_id_returns_empty(self, db: ConversationsDB) -> None:
        await _insert_conv(db, created_at=_ts(0))
        rows = await db.get_latest_conversations_with_summaries_cursor(
            "sess_a", limit=10, before_conversation_id="nonexistent-id"
        )
        assert rows == []

    @pytest.mark.asyncio
    async def test_isolates_sessions(self, db: ConversationsDB) -> None:
        await _insert_conv(db, session_id="sess_a", created_at=_ts(0))
        await _insert_conv(db, session_id="sess_b", created_at=_ts(1))
        rows = await db.get_latest_conversations_with_summaries_cursor("sess_a", limit=10)
        assert all(r["session_id"] == "sess_a" for r in rows)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_mixed_summarised_and_unsummarised(self, db: ConversationsDB) -> None:
        cid_no_sum = await _insert_conv(db, created_at=_ts(20))
        cid_has_sum = await _insert_conv(db, created_at=_ts(10))
        await _insert_summary(db, cid_has_sum, topics=["Pydantic"])
        rows = await db.get_latest_conversations_with_summaries_cursor("sess_a", limit=10)
        assert rows[0]["conversation_id"] == cid_no_sum
        assert rows[0]["topics"] is None
        assert rows[1]["conversation_id"] == cid_has_sum
        assert rows[1]["topics"] == ["Pydantic"]


# ---------------------------------------------------------------------------
# API: GET /sessions/{session_id}/conversations
# ---------------------------------------------------------------------------


class TestListConversationsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_session(self, client: AsyncClient) -> None:
        resp = await client.get("/sessions/no_such/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_conversation_with_null_summary(
        self, client: AsyncClient, tmp_path: Path
    ) -> None:
        db: ConversationsDB = app.state.db
        cid = await _insert_conv(db, created_at=_ts(0))
        resp = await client.get("/sessions/sess_a/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["conversation_id"] == cid
        assert data[0]["summary_short"] is None
        assert data[0]["topics"] is None

    @pytest.mark.asyncio
    async def test_returns_conversation_with_summary(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        cid = await _insert_conv(db, created_at=_ts(0))
        await _insert_summary(db, cid, topics=["FastAPI"])
        resp = await client.get("/sessions/sess_a/conversations")
        data = resp.json()
        assert data[0]["summary_short"] == "short summary"
        assert data[0]["topics"] == ["FastAPI"]

    @pytest.mark.asyncio
    async def test_default_limit_is_10(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        for i in range(15):
            await _insert_conv(db, created_at=_ts(i))
        resp = await client.get("/sessions/sess_a/conversations")
        assert resp.status_code == 200
        assert len(resp.json()) == 10

    @pytest.mark.asyncio
    async def test_custom_limit(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        for i in range(5):
            await _insert_conv(db, created_at=_ts(i))
        resp = await client.get("/sessions/sess_a/conversations?limit=3")
        assert len(resp.json()) == 3

    @pytest.mark.asyncio
    async def test_cursor_paging(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        cids = [await _insert_conv(db, created_at=_ts(i * 10)) for i in range(4)]
        # newest first: cids[3], cids[2], cids[1], cids[0]
        first = await client.get("/sessions/sess_a/conversations?limit=2")
        cursor = first.json()[-1]["conversation_id"]
        second = await client.get(
            f"/sessions/sess_a/conversations?limit=2&before_conversation_id={cursor}"
        )
        assert second.status_code == 200
        returned_ids = [r["conversation_id"] for r in second.json()]
        assert cids[1] in returned_ids
        assert cids[0] in returned_ids

    @pytest.mark.asyncio
    async def test_invalid_limit_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/sessions/sess_a/conversations?limit=0")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Unit tests: _compute_active_topics
# ---------------------------------------------------------------------------


def _make_rows(topics_per_conv: list[list[str]]) -> list[dict]:
    """Build newest-first rows matching DB output.

    Input: topics_per_conv ordered oldest-first.
    Output: rows ordered newest-first (largest created_at first),
            matching ORDER BY created_at DESC from the DB.
    """
    n = len(topics_per_conv)
    rows = []
    for i, topics in enumerate(reversed(topics_per_conv)):
        # i=0 is newest → highest timestamp; i=n-1 is oldest → ts=0
        ts_secs = (n - 1 - i) * 10
        rows.append(
            {
                "conversation_id": str(i),
                "session_id": "sess",
                "created_at": (_BASE_TS + timedelta(seconds=ts_secs)).isoformat(),
                "summary_short": "s",
                "topics": topics,
            }
        )
    return rows


class TestComputeActiveTopics:
    def test_empty_rows_returns_empty(self) -> None:
        result = _compute_active_topics([], window=10, top_k=5)
        assert result.active_topics == []
        assert result.window.conversations == 0

    def test_window_size_in_response(self) -> None:
        rows = _make_rows([["A"], ["B"], ["A"]])
        result = _compute_active_topics(rows, window=10, top_k=5)
        assert result.window.conversations == 3

    def test_top_k_limits_results(self) -> None:
        rows = _make_rows([["A", "B", "C", "D", "E", "F"]])
        result = _compute_active_topics(rows, window=10, top_k=3)
        assert len(result.active_topics) <= 3

    def test_weight_equals_count_over_window(self) -> None:
        rows = _make_rows([["A"], ["A"], ["B"]])
        result = _compute_active_topics(rows, window=3, top_k=5)
        a = next(t for t in result.active_topics if t.topic == "A")
        assert abs(a.weight - 2 / 3) < 0.01

    def test_trend_new_when_absent_in_prior_half(self) -> None:
        # 4 rows (oldest-first input): prior half = [A, A], recent half = [A, A+X]
        # "X" only in recent half → new
        rows = _make_rows([["A"], ["A"], ["A"], ["A", "X"]])
        result = _compute_active_topics(rows, window=4, top_k=5)
        x = next((t for t in result.active_topics if t.topic == "X"), None)
        assert x is not None
        assert x.trend == "new"

    def test_trend_rising_when_more_frequent_in_recent_half(self) -> None:
        # prior half = [A, B], recent half = [A, A] → A rising
        rows = _make_rows([["A"], ["B"], ["A"], ["A"]])
        result = _compute_active_topics(rows, window=4, top_k=5)
        a = next((t for t in result.active_topics if t.topic == "A"), None)
        assert a is not None
        assert a.trend == "rising"

    def test_trend_stable_for_equal_frequency(self) -> None:
        # "A" appears equally in both halves → stable
        rows = _make_rows([["A"], ["A"], ["A"], ["A"]])
        result = _compute_active_topics(rows, window=4, top_k=5)
        a = next(t for t in result.active_topics if t.topic == "A")
        assert a.trend == "stable"

    def test_window_capped_to_available_rows(self) -> None:
        rows = _make_rows([["A"], ["B"]])
        result = _compute_active_topics(rows, window=100, top_k=5)
        assert result.window.conversations == 2

    def test_from_and_to_set_correctly(self) -> None:
        rows = _make_rows([["A"], ["B"], ["C"]])
        result = _compute_active_topics(rows, window=3, top_k=5)
        assert result.window.from_ is not None
        assert result.window.to is not None
        assert result.window.from_ <= result.window.to


# ---------------------------------------------------------------------------
# API: GET /sessions/{session_id}/topics/active
# ---------------------------------------------------------------------------


class TestActiveTopicsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_session_returns_empty_topics(self, client: AsyncClient) -> None:
        resp = await client.get("/sessions/sess_a/topics/active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_topics"] == []

    @pytest.mark.asyncio
    async def test_returns_topics_with_weight_and_trend(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        for i, topics in enumerate([["FastAPI", "Pydantic"], ["FastAPI"], ["SQLite"]]):
            cid = await _insert_conv(db, created_at=_ts(i * 10))
            await _insert_summary(db, cid, topics=topics)
        resp = await client.get("/sessions/sess_a/topics/active?window=10&top_k=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["active_topics"]) <= 3
        assert all("topic" in t and "weight" in t and "trend" in t for t in data["active_topics"])

    @pytest.mark.asyncio
    async def test_window_param_limits_conversations(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        for i in range(8):
            cid = await _insert_conv(db, created_at=_ts(i * 10))
            await _insert_summary(db, cid, topics=["Topic"])
        resp = await client.get("/sessions/sess_a/topics/active?window=3")
        data = resp.json()
        assert data["window"]["conversations"] == 3

    @pytest.mark.asyncio
    async def test_top_k_limits_active_topics(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        cid = await _insert_conv(db, created_at=_ts(0))
        await _insert_summary(db, cid, topics=["A", "B", "C", "D", "E"])
        resp = await client.get("/sessions/sess_a/topics/active?top_k=2")
        data = resp.json()
        assert len(data["active_topics"]) <= 2

    @pytest.mark.asyncio
    async def test_unsummarised_conversations_excluded(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        # One with summary, one without
        cid1 = await _insert_conv(db, created_at=_ts(0))
        await _insert_summary(db, cid1, topics=["FastAPI"])
        await _insert_conv(db, created_at=_ts(10))  # no summary
        resp = await client.get("/sessions/sess_a/topics/active?window=10")
        data = resp.json()
        # Only conversations with summaries count in active topics
        assert data["window"]["conversations"] == 1

    @pytest.mark.asyncio
    async def test_invalid_window_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/sessions/sess_a/topics/active?window=0")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_response_has_window_metadata(self, client: AsyncClient) -> None:
        db: ConversationsDB = app.state.db
        cid = await _insert_conv(db, created_at=_ts(0))
        await _insert_summary(db, cid, topics=["Event Sourcing"])
        resp = await client.get("/sessions/sess_a/topics/active")
        data = resp.json()
        assert "window" in data
        assert "conversations" in data["window"]
