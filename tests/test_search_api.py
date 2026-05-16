"""Tests for search and context injection endpoints.

Covers:
- GET /search/conversations  (FTS5 trigram)
- GET /search/topics         (json_each LIKE)
- GET /context/recent        (recent summaries for hook injection)
- ConversationsDB.backfill_fts()
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
from src.replay.db import ConversationsDB
from src.store.event_store import EventStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(offset: int = 0) -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset)


async def _add_conv(
    db: ConversationsDB,
    *,
    session_id: str = "sess_a",
    project_id: str = "proj_a",
    offset: int = 0,
    summary_short: str = "Test summary",
    summary_long: str = "Long summary text",
    topics: list[str] | None = None,
) -> str:
    cid = str(uuid.uuid4())
    await db.insert_conversation(
        conversation_id=cid,
        session_id=session_id,
        chunk_file_first="events_0001.jsonl",
        chunk_file_last="events_0001.jsonl",
        event_index_start=0,
        event_index_end=9,
        created_at=_ts(offset),
        message_count=2,
        project_id=project_id,
    )
    await db.insert_summary(
        conversation_id=cid,
        summary_short=summary_short,
        summary_long=summary_long,
        topics=topics or [],
        model_used="test-model",
    )
    return cid


# ---------------------------------------------------------------------------
# DB-level fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[ConversationsDB, None]:
    async with ConversationsDB(db_path=tmp_path / "replay.db") as database:
        yield database


# ---------------------------------------------------------------------------
# API-level fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncGenerator[AsyncClient, None]:
    tmp_db = ConversationsDB(db_path=tmp_path / "test.db")
    await tmp_db.connect()
    tmp_store = EventStore(base_path=tmp_path / "sessions")

    stub_adapter = MagicMock(spec=AdapterPlugin)
    stub_adapter.source_name = "claude_cli"
    stub_adapter.parse.return_value = []

    app.state.store = tmp_store
    app.state.db = tmp_db
    app.state.adapters = {"claude_cli": stub_adapter}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await tmp_db.close()


# ---------------------------------------------------------------------------
# backfill_fts tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_fts_inserts_existing_summaries(db: ConversationsDB) -> None:
    """backfill_fts should index summaries that predate FTS setup."""
    await _add_conv(db, summary_short="Machine learning pipeline")
    await _add_conv(db, summary_short="FAISS vector index", offset=1)

    # Simulate pre-FTS state by wiping FTS table
    assert db._conn is not None
    await db._conn.execute("DELETE FROM conversations_fts")
    await db._conn.commit()

    inserted = await db.backfill_fts()
    assert inserted == 2


@pytest.mark.asyncio
async def test_backfill_fts_skips_already_indexed(db: ConversationsDB) -> None:
    """backfill_fts should not re-insert rows already in the FTS index."""
    await _add_conv(db, summary_short="Already indexed")
    # insert_summary already populated FTS, so backfill should add 0
    inserted = await db.backfill_fts()
    assert inserted == 0


# ---------------------------------------------------------------------------
# FTS search tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_fts_returns_match(db: ConversationsDB) -> None:
    """FTS search should return conversations whose summary matches the query."""
    await _add_conv(db, summary_short="Transformer attention mechanism", topics=["transformers"])
    await _add_conv(db, summary_short="UMAP dimensionality reduction", offset=1, topics=["umap"])

    results = await db.search_conversations_fts("Transformer")
    assert len(results) == 1
    assert "Transformer" in results[0]["summary_short"]


@pytest.mark.asyncio
async def test_search_fts_japanese(db: ConversationsDB) -> None:
    """FTS5 trigram tokenizer matches Japanese substrings of 3+ characters.

    Trigram tokenizer requires at least 3 characters — 2-char CJK queries
    return no results by design.  Use 3+ char queries for Japanese search.
    """
    await _add_conv(db, summary_short="要約処理を追加した会話", topics=["要約"])
    await _add_conv(db, summary_short="Other English summary", offset=1)

    # 3-character Japanese query works
    results = await db.search_conversations_fts("処理を")
    assert len(results) == 1
    assert "処理" in results[0]["summary_short"]

    # 2-character query returns nothing (trigram minimum is 3)
    empty = await db.search_conversations_fts("処理")
    assert empty == []


@pytest.mark.asyncio
async def test_search_fts_no_match(db: ConversationsDB) -> None:
    """FTS search should return empty list when no match exists."""
    await _add_conv(db, summary_short="Some summary text")
    results = await db.search_conversations_fts("xyzxyzxyz")
    assert results == []


@pytest.mark.asyncio
async def test_search_fts_project_filter(db: ConversationsDB) -> None:
    """FTS search with project_id should only return matching project."""
    await _add_conv(db, summary_short="shared keyword", project_id="proj_a")
    await _add_conv(db, summary_short="shared keyword", project_id="proj_b", offset=1)

    results = await db.search_conversations_fts("shared", project_id="proj_a")
    assert len(results) == 1
    assert results[0]["project_id"] == "proj_a"


@pytest.mark.asyncio
async def test_search_fts_since_filter(db: ConversationsDB) -> None:
    """FTS search with since filter should exclude older conversations."""
    await _add_conv(db, summary_short="old keyword summary", offset=0)
    await _add_conv(db, summary_short="new keyword summary", offset=100)

    cutoff = _ts(50)
    results = await db.search_conversations_fts("keyword", since=cutoff)
    assert len(results) == 1
    assert "new" in results[0]["summary_short"]


# ---------------------------------------------------------------------------
# Topic keyword search tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_topic_exact(db: ConversationsDB) -> None:
    """Topic search should find conversations with matching topic."""
    await _add_conv(db, topics=["transformers", "attention"])
    await _add_conv(db, topics=["umap", "clustering"], offset=1)

    results = await db.search_by_topic("transformers")
    assert len(results) == 1
    assert "transformers" in results[0]["topics"]


@pytest.mark.asyncio
async def test_search_by_topic_partial(db: ConversationsDB) -> None:
    """Topic search should support partial keyword matching."""
    await _add_conv(db, topics=["transformer_attention"])
    results = await db.search_by_topic("transform")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_by_topic_no_match(db: ConversationsDB) -> None:
    """Topic search returns empty when no topics match."""
    await _add_conv(db, topics=["umap"])
    results = await db.search_by_topic("transformer")
    assert results == []


@pytest.mark.asyncio
async def test_search_by_topic_project_filter(db: ConversationsDB) -> None:
    """Topic search with project_id filter."""
    await _add_conv(db, topics=["shared_topic"], project_id="proj_a")
    await _add_conv(db, topics=["shared_topic"], project_id="proj_b", offset=1)

    results = await db.search_by_topic("shared_topic", project_id="proj_b")
    assert len(results) == 1
    assert results[0]["project_id"] == "proj_b"


# ---------------------------------------------------------------------------
# get_recent_context tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recent_context_returns_n(db: ConversationsDB) -> None:
    """get_recent_context should return at most n conversations."""
    for i in range(7):
        await _add_conv(db, offset=i * 10)
    results = await db.get_recent_context(n=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_get_recent_context_newest_first(db: ConversationsDB) -> None:
    """get_recent_context should order newest-first."""
    await _add_conv(db, summary_short="older", offset=0)
    await _add_conv(db, summary_short="newer", offset=100)
    results = await db.get_recent_context(n=5)
    assert results[0]["summary_short"] == "newer"


@pytest.mark.asyncio
async def test_get_recent_context_session_filter(db: ConversationsDB) -> None:
    """get_recent_context with session_id scopes to that session."""
    await _add_conv(db, session_id="sess_a", summary_short="session A conv")
    await _add_conv(db, session_id="sess_b", summary_short="session B conv", offset=1)

    results = await db.get_recent_context(n=10, session_id="sess_a")
    assert all(r["session_id"] == "sess_a" for r in results)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_get_recent_context_project_filter(db: ConversationsDB) -> None:
    """get_recent_context with project_id scopes to that project."""
    await _add_conv(db, project_id="proj_x", session_id="s1")
    await _add_conv(db, project_id="proj_y", session_id="s2", offset=1)

    results = await db.get_recent_context(n=10, project_id="proj_x")
    assert all(r["project_id"] == "proj_x" for r in results)


@pytest.mark.asyncio
async def test_get_recent_context_empty(db: ConversationsDB) -> None:
    """get_recent_context returns empty list when no summaries exist."""
    results = await db.get_recent_context(n=5)
    assert results == []


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_search_conversations(client: AsyncClient, tmp_path: Path) -> None:
    """GET /search/conversations returns FTS matches."""
    db: ConversationsDB = app.state.db
    await _add_conv(db, summary_short="Neural network training")
    await _add_conv(db, summary_short="UMAP cluster", offset=1)

    resp = await client.get("/search/conversations?q=Neural")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert "Neural" in data["results"][0]["summary_short"]


@pytest.mark.asyncio
async def test_api_search_conversations_no_results(client: AsyncClient, tmp_path: Path) -> None:
    """GET /search/conversations returns empty results for non-matching query."""
    db: ConversationsDB = app.state.db
    await _add_conv(db, summary_short="Some text")

    resp = await client.get("/search/conversations?q=zzzzznotsuchterm")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_api_search_topics(client: AsyncClient, tmp_path: Path) -> None:
    """GET /search/topics returns conversations with matching topics."""
    db: ConversationsDB = app.state.db
    await _add_conv(db, topics=["machine_learning", "python"])
    await _add_conv(db, topics=["database", "sql"], offset=1)

    resp = await client.get("/search/topics?q=machine")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert "machine_learning" in data["results"][0]["topics"]


@pytest.mark.asyncio
async def test_api_context_recent(client: AsyncClient, tmp_path: Path) -> None:
    """GET /context/recent returns recent summarised conversations."""
    db: ConversationsDB = app.state.db
    for i in range(3):
        await _add_conv(db, offset=i * 10, summary_short=f"Conv {i}")

    resp = await client.get("/context/recent?n=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert len(data["conversations"]) == 2


@pytest.mark.asyncio
async def test_api_context_recent_session_scope(client: AsyncClient, tmp_path: Path) -> None:
    """GET /context/recent?session_id= scopes results to that session."""
    db: ConversationsDB = app.state.db
    await _add_conv(db, session_id="sess_target", summary_short="target session conv")
    await _add_conv(db, session_id="sess_other", summary_short="other session conv", offset=1)

    resp = await client.get("/context/recent?n=10&session_id=sess_target")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["conversations"][0]["session_id"] == "sess_target"


@pytest.mark.asyncio
async def test_api_context_recent_empty(client: AsyncClient, tmp_path: Path) -> None:
    """GET /context/recent returns count=0 when no summaries exist."""
    resp = await client.get("/context/recent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["conversations"] == []
