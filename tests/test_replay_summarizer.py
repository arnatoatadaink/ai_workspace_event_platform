"""Tests for src/replay/summarizer.py"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from src.replay.db import ConversationsDB
from src.replay.summarizer import (
    ClaudeBackend,
    OpenAICompatBackend,
    SummarizerBackend,
    SummaryResult,
    _build_conversation_text,
    summarize_conversation,
)
from src.schemas.internal_event_v1 import (
    EventSource,
    EventType,
    MessageEvent,
    StopEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from src.store.event_store import EventStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content: str, session_id: str = "s") -> MessageEvent:
    return MessageEvent(
        source=EventSource.CLAUDE_CLI,
        session_id=session_id,
        role=role,  # type: ignore[arg-type]
        content=content,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _tool(name: str, session_id: str = "s") -> ToolCallEvent:
    return ToolCallEvent(
        source=EventSource.CLAUDE_CLI,
        session_id=session_id,
        tool_name=name,
        tool_input={"arg": "value"},
        tool_use_id=str(uuid.uuid4()),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _stop(session_id: str = "s") -> StopEvent:
    return StopEvent(
        source=EventSource.CLAUDE_CLI,
        session_id=session_id,
        stop_reason="end_turn",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class _FakeBackend:
    """Backend that returns a fixed SummaryResult without network calls."""

    model_name = "fake-model"

    def __init__(self, result: SummaryResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def generate(self, conversation_text: str) -> SummaryResult:
        self.calls.append(conversation_text)
        return self._result


_FIXED_RESULT: SummaryResult = SummaryResult(
    summary_short="User asked about FastAPI.",
    summary_long="User asked about FastAPI routing. Assistant explained path parameters.",
    topics=["FastAPI", "Python", "API Design"],
)


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> ConversationsDB:
    async with ConversationsDB(db_path=tmp_path / "replay.db") as database:
        yield database


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(base_path=tmp_path / "sessions")


async def _seed_conversation(
    db: ConversationsDB,
    store: EventStore,
    session_id: str = "sess_a",
    events: list[Any] | None = None,
) -> dict[str, Any]:
    """Write events to store and insert a conversation index row."""
    if events is None:
        events = [
            _msg("user", "How do path params work?", session_id),
            _msg("assistant", "Path params are declared with {name} in the route.", session_id),
            _stop(session_id),
        ]
    for ev in events:
        store.append(ev)

    cid = str(uuid.uuid4())
    await db.insert_conversation(
        conversation_id=cid,
        session_id=session_id,
        chunk_file_first="events_0001.jsonl",
        chunk_file_last="events_0001.jsonl",
        event_index_start=0,
        event_index_end=len(events) - 1,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_count=sum(1 for e in events if e.event_type == EventType.MESSAGE),
    )
    return {
        "conversation_id": cid,
        "session_id": session_id,
        "event_index_start": 0,
        "event_index_end": len(events) - 1,
    }


# ---------------------------------------------------------------------------
# _build_conversation_text
# ---------------------------------------------------------------------------


class TestBuildConversationText:
    def test_includes_user_and_assistant_messages(self) -> None:
        events = [_msg("user", "Hello"), _msg("assistant", "Hi there")]
        text = _build_conversation_text(events)
        assert "[User] Hello" in text
        assert "[Assistant] Hi there" in text

    def test_includes_tool_call(self) -> None:
        events = [_tool("read_file")]
        text = _build_conversation_text(events)
        assert "[Tool: read_file]" in text

    def test_includes_stop_marker(self) -> None:
        events = [_stop()]
        text = _build_conversation_text(events)
        assert "[End of conversation]" in text

    def test_skips_tool_result(self) -> None:
        result_ev = ToolResultEvent(
            source=EventSource.CLAUDE_CLI,
            session_id="s",
            tool_use_id="id1",
            content="file contents",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        text = _build_conversation_text([result_ev])
        assert text == ""

    def test_truncates_long_content_per_message(self) -> None:
        long_msg = _msg("user", "x" * 600)
        text = _build_conversation_text([long_msg])
        assert "..." in text
        assert len(text) < 600

    def test_truncates_total_text_at_max_chars(self) -> None:
        # 20 messages × ~510 chars/line = ~10 200 chars → exceeds _MAX_TEXT_CHARS
        events = [_msg("user", "word " * 300)] * 20
        text = _build_conversation_text(events)
        assert len(text) <= 6_050
        assert "[truncated]" in text

    def test_empty_events_returns_empty_string(self) -> None:
        assert _build_conversation_text([]) == ""


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestSummarizerBackendProtocol:
    def test_fake_backend_satisfies_protocol(self) -> None:
        backend = _FakeBackend(_FIXED_RESULT)
        assert isinstance(backend, SummarizerBackend)

    def test_openai_compat_backend_satisfies_protocol(self) -> None:
        backend = OpenAICompatBackend()
        assert isinstance(backend, SummarizerBackend)

    def test_claude_backend_satisfies_protocol(self) -> None:
        backend = ClaudeBackend()
        assert isinstance(backend, SummarizerBackend)

    def test_openai_compat_backend_exposes_model_name(self) -> None:
        backend = OpenAICompatBackend(model="my-model")
        assert backend.model_name == "my-model"

    def test_claude_backend_exposes_model_name(self) -> None:
        backend = ClaudeBackend(model="claude-haiku-4-5-20251001")
        assert backend.model_name == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# summarize_conversation
# ---------------------------------------------------------------------------


class TestSummarizeConversation:
    @pytest.mark.asyncio
    async def test_persists_summary_to_db(self, db: ConversationsDB, store: EventStore) -> None:
        row = await _seed_conversation(db, store)
        backend = _FakeBackend(_FIXED_RESULT)

        await summarize_conversation(row, store, db, backend)

        stored = await db.get_summary(row["conversation_id"])
        assert stored is not None
        assert stored["summary_short"] == _FIXED_RESULT["summary_short"]
        assert stored["topics"] == _FIXED_RESULT["topics"]
        assert stored["model_used"] == "fake-model"

    @pytest.mark.asyncio
    async def test_returns_summary_result(self, db: ConversationsDB, store: EventStore) -> None:
        row = await _seed_conversation(db, store)
        result = await summarize_conversation(row, store, db, _FakeBackend(_FIXED_RESULT))
        assert result == _FIXED_RESULT

    @pytest.mark.asyncio
    async def test_passes_conversation_text_to_backend(
        self, db: ConversationsDB, store: EventStore
    ) -> None:
        row = await _seed_conversation(db, store)
        backend = _FakeBackend(_FIXED_RESULT)

        await summarize_conversation(row, store, db, backend)

        assert len(backend.calls) == 1
        assert "[User]" in backend.calls[0]
        assert "[Assistant]" in backend.calls[0]

    @pytest.mark.asyncio
    async def test_uses_correct_event_slice(self, db: ConversationsDB, store: EventStore) -> None:
        """Events outside event_index_start..end must not appear in the text."""
        session_id = "sess_slice"
        # Prepend a "noise" event that belongs to a previous conversation
        noise = _msg("user", "NOISE_EVENT", session_id)
        store.append(noise)

        target_events = [
            _msg("user", "TARGET_QUESTION", session_id),
            _msg("assistant", "TARGET_ANSWER", session_id),
            _stop(session_id),
        ]
        for ev in target_events:
            store.append(ev)

        cid = str(uuid.uuid4())
        await db.insert_conversation(
            conversation_id=cid,
            session_id=session_id,
            chunk_file_first="events_0001.jsonl",
            chunk_file_last="events_0001.jsonl",
            event_index_start=1,
            event_index_end=3,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            message_count=2,
        )
        row = {
            "conversation_id": cid,
            "session_id": session_id,
            "event_index_start": 1,
            "event_index_end": 3,
        }
        backend = _FakeBackend(_FIXED_RESULT)
        await summarize_conversation(row, store, db, backend)

        text = backend.calls[0]
        assert "NOISE_EVENT" not in text
        assert "TARGET_QUESTION" in text

    @pytest.mark.asyncio
    async def test_removes_conversation_from_unsummarized_list(
        self, db: ConversationsDB, store: EventStore
    ) -> None:
        row = await _seed_conversation(db, store)
        assert len(await db.get_unsummarized_conversations("sess_a")) == 1

        await summarize_conversation(row, store, db, _FakeBackend(_FIXED_RESULT))

        assert await db.get_unsummarized_conversations("sess_a") == []
