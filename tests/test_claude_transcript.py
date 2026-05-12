"""Tests for src/adapters/claude/transcript.py and transcript-aware Stop parsing."""

from __future__ import annotations

import json
from pathlib import Path

from src.adapters.claude.adapter import ClaudeAdapter
from src.adapters.claude.transcript import (
    parse_transcript_messages,
    read_cursor,
    session_has_stored_events,
    write_cursor,
)
from src.schemas.internal_event_v1 import MessageEvent, StopEvent

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_transcript(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _user_entry(
    uuid_: str,
    content: str,
    ts: str = "2026-01-01T00:00:00.000Z",
    *,
    sidechain: bool = False,
) -> dict:
    return {
        "type": "user",
        "uuid": uuid_,
        "timestamp": ts,
        "sessionId": "sess-test",
        "isSidechain": sidechain,
        "message": {"role": "user", "content": content},
    }


def _assistant_entry(
    uuid_: str,
    texts: list[str],
    ts: str = "2026-01-01T00:00:01.000Z",
    *,
    sidechain: bool = False,
) -> dict:
    content = [{"type": "text", "text": t} for t in texts]
    return {
        "type": "assistant",
        "uuid": uuid_,
        "timestamp": ts,
        "sessionId": "sess-test",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "content": content},
    }


def _tool_result_user_entry(uuid_: str) -> dict:
    """User turn with tool_result list content — should be skipped."""
    return {
        "type": "user",
        "uuid": uuid_,
        "timestamp": "2026-01-01T00:00:02.000Z",
        "sessionId": "sess-test",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"}],
        },
    }


# ---------------------------------------------------------------------------
# Tests: cursor helpers
# ---------------------------------------------------------------------------


class TestCursorHelpers:
    def test_read_cursor_returns_none_when_missing(self, tmp_path: Path):
        assert read_cursor(tmp_path / "missing.cursor") is None

    def test_write_and_read_cursor_round_trips(self, tmp_path: Path):
        p = tmp_path / "sub" / "sess.cursor"
        write_cursor(p, 42)
        assert read_cursor(p) == 42

    def test_write_cursor_creates_parent_dirs(self, tmp_path: Path):
        p = tmp_path / "a" / "b" / "c.cursor"
        write_cursor(p, 0)
        assert p.exists()


# ---------------------------------------------------------------------------
# Tests: session_has_stored_events
# ---------------------------------------------------------------------------


class TestSessionHasStoredEvents:
    def test_returns_false_when_dir_missing(self, tmp_path: Path):
        assert not session_has_stored_events(tmp_path, "no-such-session")

    def test_returns_false_when_no_chunk_files(self, tmp_path: Path):
        (tmp_path / "my-session").mkdir()
        assert not session_has_stored_events(tmp_path, "my-session")

    def test_returns_true_when_chunk_exists(self, tmp_path: Path):
        d = tmp_path / "my-session"
        d.mkdir()
        (d / "events_0001.jsonl").write_text("")
        assert session_has_stored_events(tmp_path, "my-session")


# ---------------------------------------------------------------------------
# Tests: parse_transcript_messages
# ---------------------------------------------------------------------------


class TestParseTranscriptMessages:
    def test_returns_empty_when_transcript_missing(self, tmp_path: Path):
        events, new_count = parse_transcript_messages(
            transcript_path=tmp_path / "nonexistent.jsonl",
            session_id="s",
            cursor_path=tmp_path / "s.cursor",
            store_base=tmp_path / "store",
        )
        assert events == []
        assert new_count == 0

    def test_parses_user_and_assistant_messages(self, tmp_path: Path):
        t = tmp_path / "sess.jsonl"
        _write_transcript(
            t,
            [
                _user_entry("u1", "Hello"),
                _assistant_entry("a1", ["Hi there"]),
            ],
        )
        events, count = parse_transcript_messages(
            transcript_path=t,
            session_id="sess-test",
            cursor_path=tmp_path / "s.cursor",
            store_base=tmp_path / "store",
        )
        assert count == 2
        assert len(events) == 2
        assert isinstance(events[0], MessageEvent)
        assert events[0].role == "user"
        assert events[0].content == "Hello"
        assert events[0].event_id == "u1"
        assert events[1].role == "assistant"
        assert events[1].content == "Hi there"

    def test_skips_tool_result_user_turns(self, tmp_path: Path):
        t = tmp_path / "sess.jsonl"
        _write_transcript(t, [_tool_result_user_entry("u-tool")])
        events, _ = parse_transcript_messages(
            transcript_path=t,
            session_id="sess-test",
            cursor_path=tmp_path / "s.cursor",
            store_base=tmp_path / "store",
        )
        assert events == []

    def test_skips_sidechain_entries(self, tmp_path: Path):
        t = tmp_path / "sess.jsonl"
        _write_transcript(
            t,
            [
                _user_entry("sc-u", "subagent task", sidechain=True),
                _user_entry("main-u", "real message"),
            ],
        )
        events, _ = parse_transcript_messages(
            transcript_path=t,
            session_id="sess-test",
            cursor_path=tmp_path / "s.cursor",
            store_base=tmp_path / "store",
        )
        assert len(events) == 1
        assert events[0].event_id == "main-u"

    def test_skips_assistant_thinking_only_turns(self, tmp_path: Path):
        t = tmp_path / "sess.jsonl"
        thinking_entry = {
            "type": "assistant",
            "uuid": "a-think",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "sessionId": "sess-test",
            "isSidechain": False,
            "message": {
                "role": "assistant",
                "content": [{"type": "thinking", "thinking": "..."}],
            },
        }
        _write_transcript(t, [thinking_entry])
        events, _ = parse_transcript_messages(
            transcript_path=t,
            session_id="sess-test",
            cursor_path=tmp_path / "s.cursor",
            store_base=tmp_path / "store",
        )
        assert events == []

    def test_cursor_advances_so_second_call_returns_only_new_messages(self, tmp_path: Path):
        t = tmp_path / "sess.jsonl"
        cursor_path = tmp_path / "s.cursor"
        store_base = tmp_path / "store"
        session_id = "sess-test"

        # First call: 1 message
        _write_transcript(t, [_user_entry("u1", "First")])
        events1, count1 = parse_transcript_messages(t, session_id, cursor_path, store_base)
        write_cursor(cursor_path, count1)
        assert len(events1) == 1

        # Append a second message
        with t.open("a") as f:
            f.write(json.dumps(_user_entry("u2", "Second")) + "\n")

        # Second call: should only return the new message
        events2, count2 = parse_transcript_messages(t, session_id, cursor_path, store_base)
        assert len(events2) == 1
        assert events2[0].event_id == "u2"
        assert count2 == 2

    def test_migration_skips_backfill_when_session_has_stored_events(self, tmp_path: Path):
        t = tmp_path / "sess.jsonl"
        cursor_path = tmp_path / "s.cursor"
        store_base = tmp_path / "store"
        session_id = "sess-test"

        # Pre-existing stored events (simulates migration scenario)
        session_dir = store_base / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "events_0001.jsonl").write_text("")

        # Transcript has 2 messages but no cursor file exists
        _write_transcript(
            t,
            [
                _user_entry("u1", "Old message 1"),
                _user_entry("u2", "Old message 2"),
            ],
        )

        events, count = parse_transcript_messages(t, session_id, cursor_path, store_base)
        # Backfill must be skipped
        assert events == []
        # Cursor should advance to end of transcript
        assert count == 2

    def test_concatenates_multiple_text_blocks_in_assistant(self, tmp_path: Path):
        t = tmp_path / "sess.jsonl"
        entry = _assistant_entry("a1", ["Part one", "Part two"])
        _write_transcript(t, [entry])
        events, _ = parse_transcript_messages(
            t, "sess-test", tmp_path / "s.cursor", tmp_path / "store"
        )
        assert events[0].content == "Part one\nPart two"


# ---------------------------------------------------------------------------
# Tests: Stop hook with transcript_path in ClaudeAdapter
# ---------------------------------------------------------------------------


class TestClaudeAdapterStopWithTranscript:
    def test_stop_without_transcript_path_returns_only_stop_event(self, tmp_path: Path):
        adapter = ClaudeAdapter(
            cursor_dir=tmp_path / "cursors",
            store_base=tmp_path / "store",
        )
        payload = {"hook_event_name": "Stop", "session_id": "s1", "stop_reason": "end_turn"}
        events = adapter.parse(payload)
        assert len(events) == 1
        assert isinstance(events[0], StopEvent)

    def test_stop_with_transcript_path_returns_messages_then_stop(self, tmp_path: Path):
        t = tmp_path / "s1.jsonl"
        _write_transcript(
            t,
            [
                _user_entry("u1", "Hey Claude"),
                _assistant_entry("a1", ["Sure, I can help"]),
            ],
        )
        adapter = ClaudeAdapter(
            cursor_dir=tmp_path / "cursors",
            store_base=tmp_path / "store",
        )
        payload = {
            "hook_event_name": "Stop",
            "session_id": "s1",
            "stop_reason": "end_turn",
            "transcript_path": str(t),
        }
        events = adapter.parse(payload)
        assert len(events) == 3
        assert isinstance(events[0], MessageEvent)
        assert events[0].role == "user"
        assert isinstance(events[1], MessageEvent)
        assert events[1].role == "assistant"
        assert isinstance(events[2], StopEvent)
        assert events[2].stop_reason == "end_turn"

    def test_stop_with_nonexistent_transcript_path_returns_only_stop(self, tmp_path: Path):
        adapter = ClaudeAdapter(
            cursor_dir=tmp_path / "cursors",
            store_base=tmp_path / "store",
        )
        payload = {
            "hook_event_name": "Stop",
            "session_id": "s1",
            "transcript_path": str(tmp_path / "does_not_exist.jsonl"),
        }
        events = adapter.parse(payload)
        assert len(events) == 1
        assert isinstance(events[0], StopEvent)

    def test_stop_updates_cursor_so_second_call_returns_only_new_messages(self, tmp_path: Path):
        t = tmp_path / "s1.jsonl"
        cursor_dir = tmp_path / "cursors"
        store_base = tmp_path / "store"
        adapter = ClaudeAdapter(cursor_dir=cursor_dir, store_base=store_base)

        _write_transcript(t, [_user_entry("u1", "First")])
        payload = {
            "hook_event_name": "Stop",
            "session_id": "s1",
            "transcript_path": str(t),
        }
        events1 = adapter.parse(payload)
        msg_events1 = [e for e in events1 if isinstance(e, MessageEvent)]
        assert len(msg_events1) == 1

        # Append a new message and call again
        with t.open("a") as f:
            f.write(json.dumps(_user_entry("u2", "Second")) + "\n")

        events2 = adapter.parse(payload)
        msg_events2 = [e for e in events2 if isinstance(e, MessageEvent)]
        assert len(msg_events2) == 1
        assert msg_events2[0].event_id == "u2"
