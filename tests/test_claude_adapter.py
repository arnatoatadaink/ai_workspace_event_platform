"""Tests for src/adapters/claude/adapter.py"""

import pytest

from src.adapters.claude.adapter import ClaudeAdapter
from src.schemas.internal_event_v1 import (
    ApprovalEvent,
    EventSource,
    StopEvent,
    ToolCallEvent,
    ToolResultEvent,
)


@pytest.fixture()
def adapter() -> ClaudeAdapter:
    return ClaudeAdapter()


class TestClaudeAdapterSourceName:
    def test_source_name_is_claude_cli(self, adapter: ClaudeAdapter):
        assert adapter.source_name == "claude_cli"


class TestParseStop:
    def test_stop_hook_returns_stop_event(self, adapter: ClaudeAdapter):
        payload = {
            "hook_event_name": "Stop",
            "session_id": "sess-abc",
            "stop_reason": "end_turn",
        }
        events = adapter.parse(payload)
        # No transcript_path → only StopEvent
        assert len(events) == 1
        ev = events[-1]
        assert isinstance(ev, StopEvent)
        assert ev.session_id == "sess-abc"
        assert ev.stop_reason == "end_turn"
        assert ev.source == EventSource.CLAUDE_CLI

    def test_stop_hook_missing_reason_is_none(self, adapter: ClaudeAdapter):
        events = adapter.parse({"hook_event_name": "Stop", "session_id": "s1"})
        stop = events[-1]
        assert isinstance(stop, StopEvent)
        assert stop.stop_reason is None


class TestParsePreToolUse:
    def test_pre_tool_use_returns_approval_event(self, adapter: ClaudeAdapter):
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "sess-xyz",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        events = adapter.parse(payload)
        assert len(events) == 1
        ev = events[0]
        assert isinstance(ev, ApprovalEvent)
        assert ev.tool_name == "Bash"
        assert ev.tool_input == {"command": "ls"}
        assert ev.decision is None

    def test_pre_tool_use_missing_session_uses_unknown(self, adapter: ClaudeAdapter):
        events = adapter.parse(
            {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}}
        )
        assert events[0].session_id == "unknown"


class TestParsePostToolUse:
    def test_post_tool_use_returns_tool_call_and_result(self, adapter: ClaudeAdapter):
        payload = {
            "hook_event_name": "PostToolUse",
            "session_id": "sess-p",
            "tool_use_id": "tu-1",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x"},
            "tool_response": "file contents",
            "is_error": False,
        }
        events = adapter.parse(payload)
        assert len(events) == 2
        assert isinstance(events[0], ToolCallEvent)
        assert isinstance(events[1], ToolResultEvent)
        assert events[0].tool_use_id == "tu-1"
        assert events[1].tool_use_id == "tu-1"
        assert events[1].content == "file contents"
        assert events[1].is_error is False

    def test_post_tool_use_error_flag(self, adapter: ClaudeAdapter):
        payload = {
            "hook_event_name": "PostToolUse",
            "session_id": "sess-p",
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": "command not found",
            "is_error": True,
        }
        events = adapter.parse(payload)
        result = events[1]
        assert isinstance(result, ToolResultEvent)
        assert result.is_error is True


class TestParseUnknownHook:
    def test_unknown_hook_returns_empty(self, adapter: ClaudeAdapter):
        events = adapter.parse({"hook_event_name": "SomeNewHook", "session_id": "s"})
        assert events == []

    def test_missing_hook_name_returns_empty(self, adapter: ClaudeAdapter):
        events = adapter.parse({"session_id": "s"})
        assert events == []


class TestParseErrorHandling:
    def test_malformed_payload_returns_empty_not_raises(self, adapter: ClaudeAdapter):
        events = adapter.parse({"hook_event_name": "Stop", "session_id": None})
        assert isinstance(events, list)
