"""Tests for src/store/event_store.py"""

import json
from pathlib import Path

import pytest

from src.schemas.internal_event_v1 import EventSource, MessageEvent, StopEvent
from src.store.event_store import EventStore


@pytest.fixture()
def tmp_store(tmp_path: Path) -> EventStore:
    return EventStore(base_path=tmp_path, chunk_size=5)


class TestEventStoreAppend:
    def test_append_creates_chunk_file(self, tmp_store: EventStore, tmp_path: Path):
        ev = MessageEvent(source=EventSource.CLAUDE_CLI, session_id="s1", role="user", content="a")
        chunk = tmp_store.append(ev)
        assert chunk.exists()
        assert chunk.name == "events_0001.jsonl"

    def test_append_multiple_events_same_file(self, tmp_store: EventStore):
        for i in range(3):
            ev = MessageEvent(
                source=EventSource.CLAUDE_CLI,
                session_id="s1",
                role="user",
                content=str(i),
            )
            tmp_store.append(ev)
        chunks = tmp_store.iter_chunks("s1")
        assert len(chunks) == 1
        assert chunks[0].name == "events_0001.jsonl"

    def test_chunk_rotation_on_size_limit(self, tmp_store: EventStore):
        for i in range(6):  # chunk_size=5 → rotate after 5
            ev = StopEvent(source=EventSource.CLAUDE_CLI, session_id="s2")
            tmp_store.append(ev)
        chunks = tmp_store.iter_chunks("s2")
        assert len(chunks) == 2
        assert chunks[1].name == "events_0002.jsonl"

    def test_appended_json_is_valid(self, tmp_store: EventStore):
        ev = StopEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="s3",
            stop_reason="end_turn",
        )
        chunk = tmp_store.append(ev)
        lines = [ln for ln in chunk.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "stop"
        assert data["stop_reason"] == "end_turn"


class TestEventStoreRead:
    def test_iter_events_roundtrip(self, tmp_store: EventStore):
        events = [
            MessageEvent(source=EventSource.CLAUDE_CLI, session_id="s4", role="user", content="x"),
            StopEvent(source=EventSource.CLAUDE_CLI, session_id="s4"),
        ]
        for ev in events:
            tmp_store.append(ev)
        loaded = tmp_store.iter_events("s4")
        assert len(loaded) == 2
        assert loaded[0].event_id == events[0].event_id
        assert loaded[1].event_id == events[1].event_id

    def test_iter_events_across_chunks(self, tmp_store: EventStore):
        # chunk_size=5; write 7 events across 2 chunks
        for i in range(7):
            ev = MessageEvent(
                source=EventSource.CLAUDE_CLI,
                session_id="s5",
                role="user",
                content=str(i),
            )
            tmp_store.append(ev)
        loaded = tmp_store.iter_events("s5")
        assert len(loaded) == 7
        # order preserved
        contents = [e.content for e in loaded if isinstance(e, MessageEvent)]  # type: ignore[union-attr]
        assert contents == [str(i) for i in range(7)]

    def test_iter_events_empty_session_returns_empty(self, tmp_store: EventStore):
        assert tmp_store.iter_events("nonexistent") == []

    def test_list_sessions(self, tmp_store: EventStore):
        MessageEvent(source=EventSource.CLAUDE_CLI, session_id="s6", role="user", content="y")
        ev = MessageEvent(source=EventSource.CLAUDE_CLI, session_id="s6", role="user", content="y")
        tmp_store.append(ev)
        sessions = tmp_store.list_sessions()
        assert "s6" in sessions

    def test_skips_malformed_lines(self, tmp_store: EventStore, tmp_path: Path):
        session_dir = tmp_path / "s7"
        session_dir.mkdir()
        chunk = session_dir / "events_0001.jsonl"
        ev = StopEvent(source=EventSource.CLAUDE_CLI, session_id="s7")
        chunk.write_text(ev.model_dump_json() + "\n{bad json\n")
        loaded = tmp_store.iter_events("s7")
        assert len(loaded) == 1
