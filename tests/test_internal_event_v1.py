"""Tests for src/schemas/internal_event_v1.py"""

import json

from src.schemas.internal_event_v1 import (
    ApprovalEvent,
    EventSource,
    EventType,
    MessageEvent,
    StopEvent,
    ToolCallEvent,
    TranscriptRef,
    parse_event,
)


class TestMessageEvent:
    def test_create_user_message_sets_defaults(self):
        ev = MessageEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="sess-1",
            role="user",
            content="hello",
        )
        assert ev.event_type == EventType.MESSAGE
        assert ev.schema_version == "v1"
        assert ev.event_id  # auto-generated UUID
        assert ev.timestamp.tzinfo is not None

    def test_create_assistant_message_with_transcript_ref(self):
        ref = TranscriptRef(session_id="sess-1", message_index=5)
        ev = MessageEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="sess-1",
            role="assistant",
            content="world",
            transcript_ref=ref,
        )
        assert ev.transcript_ref.message_index == 5

    def test_serialise_roundtrip(self):
        ev = MessageEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="sess-1",
            role="user",
            content="roundtrip",
        )
        raw = json.loads(ev.model_dump_json())
        restored = MessageEvent.model_validate(raw)
        assert restored.content == ev.content
        assert restored.event_id == ev.event_id


class TestStopEvent:
    def test_stop_event_no_reason(self):
        ev = StopEvent(source=EventSource.CLAUDE_CLI, session_id="sess-2")
        assert ev.event_type == EventType.STOP
        assert ev.stop_reason is None

    def test_stop_event_with_reason(self):
        ev = StopEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="sess-2",
            stop_reason="end_turn",
        )
        assert ev.stop_reason == "end_turn"


class TestApprovalEvent:
    def test_approval_pending_decision_is_none(self):
        ev = ApprovalEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="sess-3",
            tool_name="Bash",
            tool_input={"command": "rm -rf /"},
        )
        assert ev.decision is None
        assert ev.tool_name == "Bash"

    def test_approval_denied(self):
        ev = ApprovalEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="sess-3",
            tool_name="Bash",
            tool_input={},
            decision="denied",
        )
        assert ev.decision == "denied"


class TestToolCallEvent:
    def test_tool_call_fields(self):
        ev = ToolCallEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="sess-4",
            tool_name="Read",
            tool_input={"file_path": "/tmp/x.py"},
            tool_use_id="tu-abc",
        )
        assert ev.tool_use_id == "tu-abc"
        assert ev.tool_input["file_path"] == "/tmp/x.py"


class TestParseEvent:
    def test_parse_message_event(self):
        data = {
            "event_id": "e1",
            "event_type": "message",
            "source": "claude_cli",
            "session_id": "s1",
            "timestamp": "2026-05-07T00:00:00+00:00",
            "schema_version": "v1",
            "role": "user",
            "content": "hi",
        }
        ev = parse_event(data)
        assert isinstance(ev, MessageEvent)
        assert ev.content == "hi"

    def test_parse_stop_event(self):
        data = {
            "event_id": "e2",
            "event_type": "stop",
            "source": "claude_cli",
            "session_id": "s1",
            "timestamp": "2026-05-07T00:00:00+00:00",
            "schema_version": "v1",
            "stop_reason": "end_turn",
        }
        ev = parse_event(data)
        assert isinstance(ev, StopEvent)
        assert ev.stop_reason == "end_turn"

    def test_parse_unknown_event_type_falls_back_to_base(self):
        data = {
            "event_id": "e3",
            "event_type": "state_update",
            "source": "claude_cli",
            "session_id": "s1",
            "timestamp": "2026-05-07T00:00:00+00:00",
            "schema_version": "v1",
        }
        from src.schemas.internal_event_v1 import InternalEvent

        ev = parse_event(data)
        assert isinstance(ev, InternalEvent)
