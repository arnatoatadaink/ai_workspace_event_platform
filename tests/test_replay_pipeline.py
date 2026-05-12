"""Tests for src/replay/pipeline.py"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from src.replay.db import ConversationsDB
from src.replay.pipeline import SummaryTopicPipeline
from src.replay.snapshot_store import SnapshotStore
from src.replay.summarizer import SummaryResult
from src.schemas.internal_event_v1 import EventSource, MessageEvent, StopEvent
from src.store.event_store import EventStore

_SRC = EventSource.CLAUDE_CLI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(n: int, session_id: str) -> MessageEvent:
    return MessageEvent(
        source=_SRC,
        session_id=session_id,
        role="user",
        content=f"message {n}",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _stop(session_id: str) -> StopEvent:
    return StopEvent(
        source=_SRC,
        session_id=session_id,
        stop_reason="end_turn",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class _FakeBackend:
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, conversation_text: str) -> SummaryResult:
        self.calls.append(conversation_text)
        return SummaryResult(
            summary_short="Fake summary.",
            summary_long="Fake long summary.",
            topics=["TopicA", "TopicB"],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> EventStore:
    return EventStore(base_path=tmp_path / "sessions")


@pytest_asyncio.fixture()
async def db(tmp_path: Path) -> ConversationsDB:
    async with ConversationsDB(db_path=tmp_path / "replay.db") as database:
        yield database


@pytest_asyncio.fixture()
async def snap_store(tmp_path: Path) -> SnapshotStore:
    async with SnapshotStore(
        snap_dir=tmp_path / "snapshots",
        db_path=tmp_path / "replay.db",
    ) as ss:
        yield ss


def _make_pipeline(
    store: EventStore,
    db: ConversationsDB,
    snap_store: SnapshotStore,
    summarizer: Any = None,
    interval: float = 0.05,
) -> SummaryTopicPipeline:
    return SummaryTopicPipeline(
        store=store,
        db=db,
        snapshot_store=snap_store,
        summarizer=summarizer,
        interval_seconds=interval,
    )


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------


class TestRunOnce:
    @pytest.mark.asyncio
    async def test_run_once_when_no_sessions_then_returns_empty_list(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        result = await _make_pipeline(store, db, snap_store).run_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_run_once_when_one_complete_conversation_then_returns_session(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        sid = "sess_a"
        store.append(_msg(0, sid))
        store.append(_stop(sid))

        result = await _make_pipeline(store, db, snap_store).run_once()

        assert result == [sid]

    @pytest.mark.asyncio
    async def test_run_once_when_no_stop_event_then_returns_empty_list(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        sid = "sess_b"
        store.append(_msg(0, sid))  # no StopEvent — no complete conversation

        result = await _make_pipeline(store, db, snap_store).run_once()

        assert result == []

    @pytest.mark.asyncio
    async def test_run_once_when_two_sessions_then_both_updated(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        for sid in ("sess_x", "sess_y"):
            store.append(_msg(0, sid))
            store.append(_stop(sid))

        result = await _make_pipeline(store, db, snap_store).run_once()

        assert sorted(result) == ["sess_x", "sess_y"]

    @pytest.mark.asyncio
    async def test_run_once_when_called_twice_then_second_returns_empty(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        sid = "sess_c"
        store.append(_msg(0, sid))
        store.append(_stop(sid))

        pipeline = _make_pipeline(store, db, snap_store)
        first = await pipeline.run_once()
        second = await pipeline.run_once()

        assert first == [sid]
        assert second == []

    @pytest.mark.asyncio
    async def test_run_once_when_summarizer_provided_then_summaries_persisted(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        sid = "sess_d"
        store.append(_msg(0, sid))
        store.append(_msg(1, sid))
        store.append(_stop(sid))

        backend = _FakeBackend()
        await _make_pipeline(store, db, snap_store, summarizer=backend).run_once()

        rows = await db.get_conversations_with_summaries(session_id=sid)
        assert len(rows) == 1
        assert rows[0]["summary_short"] == "Fake summary."
        assert "TopicA" in rows[0]["topics"]

    @pytest.mark.asyncio
    async def test_run_once_when_session_raises_then_other_session_still_processed(
        self,
        store: EventStore,
        db: ConversationsDB,
        snap_store: SnapshotStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An exception in one session must not prevent the remaining sessions."""
        for sid in ("sess_ok", "sess_bad"):
            store.append(_msg(0, sid))
            store.append(_stop(sid))

        from src.replay import snapshot as snapshot_mod

        original = snapshot_mod.run_incremental_update

        async def _failing(session_id: str, *args: Any, **kwargs: Any) -> Any:
            if session_id == "sess_bad":
                raise RuntimeError("Simulated failure")
            return await original(session_id, *args, **kwargs)

        import src.replay.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "run_incremental_update", _failing)

        result = await _make_pipeline(store, db, snap_store).run_once()

        assert "sess_ok" in result
        assert "sess_bad" not in result

    @pytest.mark.asyncio
    async def test_run_once_when_new_events_added_between_calls_then_incremental(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        sid = "sess_e"
        store.append(_msg(0, sid))
        store.append(_stop(sid))

        pipeline = _make_pipeline(store, db, snap_store)
        first = await pipeline.run_once()
        assert first == [sid]

        store.append(_msg(1, sid))
        store.append(_stop(sid))

        second = await pipeline.run_once()
        assert second == [sid]  # new conversation was indexed


# ---------------------------------------------------------------------------
# run_loop / stop
# ---------------------------------------------------------------------------


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_loop_when_stop_called_then_task_completes(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        pipeline = _make_pipeline(store, db, snap_store, interval=0.05)
        task = asyncio.create_task(pipeline.run_loop())
        await asyncio.sleep(0.1)  # let at least one pass run

        pipeline.stop()
        await asyncio.wait_for(task, timeout=2.0)

        assert task.done()
        assert not task.cancelled()

    @pytest.mark.asyncio
    async def test_run_loop_when_sessions_exist_then_indexed_during_loop(
        self, store: EventStore, db: ConversationsDB, snap_store: SnapshotStore
    ) -> None:
        sid = "sess_loop"
        store.append(_msg(0, sid))
        store.append(_stop(sid))

        pipeline = _make_pipeline(store, db, snap_store, interval=0.05)
        task = asyncio.create_task(pipeline.run_loop())
        await asyncio.sleep(0.15)  # enough time for at least two passes
        pipeline.stop()
        await asyncio.wait_for(task, timeout=2.0)

        rows = await db.get_all_conversations()
        assert any(r["session_id"] == sid for r in rows)
