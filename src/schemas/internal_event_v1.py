"""Internal Event Schema v1.

Source-independent event models. Adapters MUST convert to these before
passing to EventStore. Never expose source-specific fields to GUI or Replay.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EventSource(str, Enum):
    CLAUDE_CLI = "claude_cli"
    WEBCHAT = "webchat"
    DISCORD_BOT = "discord_bot"
    GEMINI_CLI = "gemini_cli"
    SYSTEM = "system"
    FRONTEND = "frontend"


class EventType(str, Enum):
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUIRED = "approval_required"
    STOP = "stop"
    SUMMARY_UPDATE = "summary_update"
    TOPIC_EXTRACTION = "topic_extraction"
    STATE_UPDATE = "state_update"
    FRONTEND_DEBUG = "frontend_debug"


def _new_event_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TranscriptRef(BaseModel):
    """Pointer into the raw transcript; avoids embedding full text in events."""

    session_id: str
    message_index: int


class InternalEvent(BaseModel):
    """Base model for all internal events.

    All adapter output must be converted to this schema before storage.
    schema_version is fixed at 'v1'; breaking changes require a new module.
    """

    event_id: str = Field(default_factory=_new_event_id)
    event_type: EventType
    source: EventSource
    session_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    schema_version: Literal["v1"] = "v1"


class MessageEvent(InternalEvent):
    """A single user or assistant turn."""

    event_type: Literal[EventType.MESSAGE] = EventType.MESSAGE
    role: Literal["user", "assistant"]
    content: str
    transcript_ref: Optional[TranscriptRef] = None


class ToolCallEvent(InternalEvent):
    """Claude invoking a tool (pre-execution)."""

    event_type: Literal[EventType.TOOL_CALL] = EventType.TOOL_CALL
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str


class ToolResultEvent(InternalEvent):
    """Result returned from a tool execution."""

    event_type: Literal[EventType.TOOL_RESULT] = EventType.TOOL_RESULT
    tool_use_id: str
    content: Any
    is_error: bool = False


class ApprovalEvent(InternalEvent):
    """Tool use approval request (PreToolUse hook)."""

    event_type: Literal[EventType.APPROVAL_REQUIRED] = EventType.APPROVAL_REQUIRED
    tool_name: str
    tool_input: dict[str, Any]
    decision: Optional[Literal["approved", "denied"]] = None


class StopEvent(InternalEvent):
    """Session stop signal (Stop hook)."""

    event_type: Literal[EventType.STOP] = EventType.STOP
    stop_reason: Optional[str] = None


class SummaryUpdateEvent(InternalEvent):
    """Emitted when a conversation summary is generated or updated."""

    event_type: Literal[EventType.SUMMARY_UPDATE] = EventType.SUMMARY_UPDATE
    summary_short: str
    summary_long: str
    topics: list[str] = Field(default_factory=list)


class TopicExtractionEvent(InternalEvent):
    """Emitted when topics are extracted from a conversation."""

    event_type: Literal[EventType.TOPIC_EXTRACTION] = EventType.TOPIC_EXTRACTION
    topics: list[str]
    conversation_id: Optional[str] = None


class FrontendDebugEvent(InternalEvent):
    """Debug event emitted by the React frontend (dev-only)."""

    event_type: Literal[EventType.FRONTEND_DEBUG] = EventType.FRONTEND_DEBUG
    source: Literal[EventSource.FRONTEND] = EventSource.FRONTEND  # type: ignore[assignment]
    component: str
    lifecycle: str
    data: dict[str, Any] = Field(default_factory=dict)


# Discriminated union for deserialization
AnyEvent = (
    MessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | ApprovalEvent
    | StopEvent
    | SummaryUpdateEvent
    | TopicExtractionEvent
    | FrontendDebugEvent
    | InternalEvent
)

_EVENT_TYPE_MAP: dict[EventType, type[InternalEvent]] = {
    EventType.MESSAGE: MessageEvent,
    EventType.TOOL_CALL: ToolCallEvent,
    EventType.TOOL_RESULT: ToolResultEvent,
    EventType.APPROVAL_REQUIRED: ApprovalEvent,
    EventType.STOP: StopEvent,
    EventType.SUMMARY_UPDATE: SummaryUpdateEvent,
    EventType.TOPIC_EXTRACTION: TopicExtractionEvent,
    EventType.FRONTEND_DEBUG: FrontendDebugEvent,
}


def parse_event(data: dict[str, Any]) -> InternalEvent:
    """Deserialize a raw dict to the appropriate InternalEvent subclass."""
    event_type = EventType(data["event_type"])
    model_cls = _EVENT_TYPE_MAP.get(event_type, InternalEvent)
    return model_cls.model_validate(data)
