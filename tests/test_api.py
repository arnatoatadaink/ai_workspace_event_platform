"""Tests for FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.adapters.base import AdapterPlugin
from src.api.main import app
from src.replay.db import ConversationsDB
from src.schemas.internal_event_v1 import EventSource, EventType, StopEvent
from src.store.event_store import EventStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_store(tmp_path: Path) -> EventStore:
    return EventStore(base_path=tmp_path / "sessions")


@pytest.fixture()
def sample_stop_event(tmp_store: EventStore) -> StopEvent:
    event = StopEvent(
        source=EventSource.CLAUDE_CLI,
        session_id="ses_001",
        stop_reason="end_turn",
    )
    tmp_store.append(event)
    return event


@pytest_asyncio.fixture()
async def client(tmp_store: EventStore, tmp_path: Path) -> AsyncGenerator[AsyncClient, None]:
    """Async test client with isolated store and DB."""
    db = ConversationsDB(db_path=tmp_path / "test.db")
    await db.connect()

    # Minimal adapter stub
    stub_adapter = MagicMock(spec=AdapterPlugin)
    stub_adapter.source_name = "claude_cli"
    stub_adapter.parse.return_value = []

    app.state.store = tmp_store
    app.state.db = db
    app.state.adapters = {"claude_cli": stub_adapter}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await db.close()


# ---------------------------------------------------------------------------
# GET /sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_empty(client: AsyncClient) -> None:
    resp = await client.get("/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_sessions_lists_session(client: AsyncClient, sample_stop_event: StopEvent) -> None:
    resp = await client.get("/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "ses_001"
    assert data[0]["event_count"] == 1


# ---------------------------------------------------------------------------
# GET /events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_returns_page(client: AsyncClient, sample_stop_event: StopEvent) -> None:
    resp = await client.get("/events", params={"session_id": "ses_001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["event_type"] == EventType.STOP.value


@pytest.mark.asyncio
async def test_events_pagination(client: AsyncClient, tmp_store: EventStore) -> None:
    for i in range(5):
        tmp_store.append(StopEvent(source=EventSource.CLAUDE_CLI, session_id="ses_002"))
    resp = await client.get("/events", params={"session_id": "ses_002", "limit": 2, "offset": 1})
    body = resp.json()
    assert body["total"] == 5
    assert body["offset"] == 1
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_events_unknown_session(client: AsyncClient) -> None:
    resp = await client.get("/events", params={"session_id": "no_such"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /topics helpers
# ---------------------------------------------------------------------------


async def _seed_summary(
    db: ConversationsDB,
    *,
    conversation_id: str,
    session_id: str,
    topics: list[str],
    created_at: datetime,
    summary_short: str = "test summary",
) -> None:
    """Insert a conversation + summary row directly into the DB for testing."""
    await db.insert_conversation(
        conversation_id=conversation_id,
        session_id=session_id,
        chunk_file_first="events_0001.jsonl",
        chunk_file_last="events_0001.jsonl",
        event_index_start=0,
        event_index_end=0,
        created_at=created_at,
        message_count=1,
    )
    await db.insert_summary(
        conversation_id=conversation_id,
        summary_short=summary_short,
        summary_long="",
        topics=topics,
        model_used="test",
    )


# ---------------------------------------------------------------------------
# GET /topics — scope=conversation (default)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_empty(client: AsyncClient) -> None:
    resp = await client.get("/topics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "conversation"
    assert body["data"] == []


@pytest.mark.asyncio
async def test_topics_conversation_scope(client: AsyncClient) -> None:
    db: ConversationsDB = app.state.db
    ts = datetime(2026, 5, 9, 10, 0, 0, tzinfo=timezone.utc)
    await _seed_summary(
        db,
        conversation_id="conv_1",
        session_id="ses_A",
        topics=["FastAPI", "Python"],
        created_at=ts,
    )
    resp = await client.get("/topics")
    body = resp.json()
    assert body["scope"] == "conversation"
    assert len(body["data"]) == 1
    assert body["data"][0]["conversation_id"] == "conv_1"
    assert set(body["data"][0]["topics"]) == {"FastAPI", "Python"}


@pytest.mark.asyncio
async def test_topics_with_counts_conversation(client: AsyncClient) -> None:
    db: ConversationsDB = app.state.db
    ts = datetime(2026, 5, 9, 11, 0, 0, tzinfo=timezone.utc)
    await _seed_summary(
        db,
        conversation_id="conv_c",
        session_id="ses_X",
        topics=["Docker"],
        created_at=ts,
    )
    resp = await client.get("/topics", params={"with_counts": "true"})
    entries = [e for e in resp.json()["data"] if e["conversation_id"] == "conv_c"]
    assert entries[0]["topic_counts"] == {"Docker": 1}


# ---------------------------------------------------------------------------
# GET /topics — scope=session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_session_scope_aggregates(client: AsyncClient) -> None:
    db: ConversationsDB = app.state.db
    ts1 = datetime(2026, 5, 9, 8, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 9, 9, 0, 0, tzinfo=timezone.utc)
    await _seed_summary(
        db, conversation_id="s_c1", session_id="ses_B", topics=["Python", "FastAPI"], created_at=ts1
    )
    await _seed_summary(
        db, conversation_id="s_c2", session_id="ses_B", topics=["Python", "Docker"], created_at=ts2
    )

    resp = await client.get(
        "/topics", params={"scope": "session", "session_id": "ses_B", "with_counts": "true"}
    )
    body = resp.json()
    assert body["scope"] == "session"
    entries = [e for e in body["data"] if e["session_id"] == "ses_B"]
    assert len(entries) == 1
    e = entries[0]
    assert e["conversation_count"] == 2
    # Python appears in both conversations
    assert e["topic_counts"]["Python"] == 2
    assert e["topic_counts"]["FastAPI"] == 1
    # topics list is sorted by frequency
    assert e["topics"][0] == "Python"


# ---------------------------------------------------------------------------
# GET /topics — scope=global
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_global_scope(client: AsyncClient) -> None:
    db: ConversationsDB = app.state.db
    ts = datetime(2026, 5, 9, 7, 0, 0, tzinfo=timezone.utc)
    await _seed_summary(
        db, conversation_id="g_c1", session_id="ses_G1", topics=["EventSourcing"], created_at=ts
    )
    await _seed_summary(
        db,
        conversation_id="g_c2",
        session_id="ses_G2",
        topics=["EventSourcing", "CQRS"],
        created_at=ts,
    )

    resp = await client.get("/topics", params={"scope": "global", "with_counts": "true"})
    body = resp.json()
    assert body["scope"] == "global"
    assert len(body["data"]) == 1
    g = body["data"][0]
    assert g["session_count"] >= 2
    assert g["topic_counts"]["EventSourcing"] >= 2


# ---------------------------------------------------------------------------
# GET /topics — time filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_within_minutes_filters(client: AsyncClient) -> None:
    db: ConversationsDB = app.state.db
    now = datetime.now(timezone.utc)
    old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)

    await _seed_summary(
        db, conversation_id="t_recent", session_id="ses_T", topics=["Recent"], created_at=now
    )
    await _seed_summary(
        db, conversation_id="t_old", session_id="ses_T", topics=["Old"], created_at=old_ts
    )

    resp = await client.get("/topics", params={"within_minutes": "60", "session_id": "ses_T"})
    ids = [e["conversation_id"] for e in resp.json()["data"]]
    assert "t_recent" in ids
    assert "t_old" not in ids


@pytest.mark.asyncio
async def test_topics_within_days_and_hours_additive(client: AsyncClient) -> None:
    """within_days=1 and within_hours=2 should give a 26-hour window."""
    resp = await client.get("/topics", params={"within_days": "1", "within_hours": "2"})
    body = resp.json()
    assert body["within_minutes"] == pytest.approx(26 * 60)


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_unknown_source(client: AsyncClient) -> None:
    resp = await client.post("/ingest", json={"source": "not_a_source", "payload": {}})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_zero_events(client: AsyncClient) -> None:
    """Adapter returning [] still returns 200 with stored=0."""
    resp = await client.post(
        "/ingest",
        json={"source": "claude_cli", "payload": {"hook_event_name": "Unknown"}},
    )
    assert resp.status_code == 200
    assert resp.json()["stored"] == 0


@pytest.mark.asyncio
async def test_ingest_stores_events(client: AsyncClient, tmp_store: EventStore) -> None:
    """Adapter returning events stores them in the EventStore."""
    stop = StopEvent(source=EventSource.CLAUDE_CLI, session_id="ses_ingest")
    app.state.adapters["claude_cli"].parse.return_value = [stop]

    resp = await client.post(
        "/ingest",
        json={"source": "claude_cli", "payload": {"hook_event_name": "Stop"}},
    )
    assert resp.status_code == 200
    assert resp.json()["stored"] == 1
    assert tmp_store.count_events("ses_ingest") == 1
