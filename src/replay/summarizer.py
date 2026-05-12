"""Replay Engine: Conversation summarizer.

Generates summary_short / summary_long / topics for a conversation using a
pluggable LLM backend and stores the result in ConversationsDB.

Two built-in backends:
  - OpenAICompatBackend: any OpenAI-compatible endpoint
      (default: local Gemma via LM Studio at http://192.168.2.104:52624/v1)
  - ClaudeBackend: Anthropic Claude API (tool-use for structured output)

Usage::

    backend = OpenAICompatBackend()
    async with ConversationsDB() as db:
        for row in await db.get_unsummarized_conversations("session_x"):
            await summarize_conversation(row, store, db, backend)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Protocol, TypedDict, runtime_checkable

from src.replay.db import ConversationsDB
from src.schemas.internal_event_v1 import (
    EventSource,
    EventType,
    InternalEvent,
    MessageEvent,
    SummaryUpdateEvent,
    ToolCallEvent,
    TopicExtractionEvent,
)
from src.store.event_store import EventStore

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 6_000

_SYSTEM_PROMPT = """\
You are a conversation analyst. Given an AI assistant conversation transcript,
extract a JSON object with exactly these fields:
  summary_short: string (1-2 sentences, the main task or topic)
  summary_long: string (2-4 sentences, key decisions and outcomes)
  topics: array of 3-7 specific topic strings (e.g. ["FastAPI", "Python", "Event Sourcing"])

Return ONLY valid JSON, no markdown fences, no other text."""

_USER_PROMPT_TEMPLATE = "Analyze this conversation:\n\n{text}"


class SummaryResult(TypedDict):
    summary_short: str
    summary_long: str
    topics: list[str]


@runtime_checkable
class SummarizerBackend(Protocol):
    """Protocol for LLM backends used by the summarizer pipeline."""

    model_name: str

    async def generate(self, conversation_text: str) -> SummaryResult:
        """Generate a SummaryResult from a plain-text conversation."""
        ...


class OpenAICompatBackend:
    """OpenAI-compatible API backend (LM Studio / Ollama / vLLM etc.).

    Args:
        base_url: Base URL of the OpenAI-compatible API server.
        api_key: API key (use any non-empty string for keyless servers).
        model: Model identifier as recognised by the server.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://192.168.2.104:52624/v1",
        api_key: str = "lm",
        model: str = "gemma-4-31b-it@q6_k",
    ) -> None:
        import openai

        self.model_name = model
        self._client = openai.AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=120.0
        )

    async def generate(self, conversation_text: str) -> SummaryResult:
        response = await self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_PROMPT_TEMPLATE.format(text=conversation_text),
                },
            ],
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "{}"
        # Strip markdown fences if the model wraps the JSON.
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()
        data: dict[str, Any] = json.loads(raw)
        return SummaryResult(
            summary_short=str(data.get("summary_short", "")),
            summary_long=str(data.get("summary_long", "")),
            topics=[str(t) for t in data.get("topics", [])],
        )


class ClaudeBackend:
    """Anthropic Claude API backend using tool-use for structured output.

    Args:
        model: Claude model ID.
        api_key: Anthropic API key (reads ANTHROPIC_API_KEY env var if omitted).
    """

    _TOOL_NAME = "store_summary"
    _TOOL_DEF: dict[str, Any] = {
        "name": _TOOL_NAME,
        "description": "Store the extracted conversation summary and topics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary_short": {
                    "type": "string",
                    "description": "1-2 sentence summary of the main task or topic",
                },
                "summary_long": {
                    "type": "string",
                    "description": "2-4 sentence detailed summary with key decisions and outcomes",
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-7 specific topic strings",
                },
            },
            "required": ["summary_short", "summary_long", "topics"],
        },
    }

    def __init__(
        self,
        *,
        model: str = "claude-haiku-4-5-20251001",
        api_key: Optional[str] = None,
    ) -> None:
        import anthropic

        self.model_name = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, conversation_text: str) -> SummaryResult:
        response = await self._client.messages.create(
            model=self.model_name,
            max_tokens=1024,
            tools=[self._TOOL_DEF],  # type: ignore[list-item]
            tool_choice={"type": "any"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{_SYSTEM_PROMPT}\n\n"
                        f"{_USER_PROMPT_TEMPLATE.format(text=conversation_text)}"
                    ),
                }
            ],
        )
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                data = block.input  # type: ignore[union-attr]
                return SummaryResult(
                    summary_short=str(data.get("summary_short", "")),
                    summary_long=str(data.get("summary_long", "")),
                    topics=[str(t) for t in data.get("topics", [])],
                )
        raise RuntimeError(
            f"Claude returned no tool_use block for conversation summary. "
            f"stop_reason={response.stop_reason}"
        )


def _build_conversation_text(events: list[InternalEvent]) -> str:
    """Build a readable text representation of a conversation's events."""
    lines: list[str] = []
    for ev in events:
        if isinstance(ev, MessageEvent):
            prefix = "User" if ev.role == "user" else "Assistant"
            content = ev.content[:500] + "..." if len(ev.content) > 500 else ev.content
            lines.append(f"[{prefix}] {content}")
        elif isinstance(ev, ToolCallEvent):
            lines.append(f"[Tool: {ev.tool_name}]")
        elif ev.event_type == EventType.STOP:
            lines.append("[End of conversation]")

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS] + "\n...[truncated]"
    return text


async def summarize_conversation(
    conversation_row: dict[str, Any],
    store: EventStore,
    db: ConversationsDB,
    backend: SummarizerBackend,
) -> SummaryResult:
    """Generate and persist a summary for one conversation.

    Reads the relevant events from the store, builds a text representation,
    calls *backend* to generate summary + topics, and persists the result in
    the ``conversation_summaries`` table.

    Args:
        conversation_row: A row dict from the ``conversations`` table.
        store: Source EventStore (read-only).
        db: Open ConversationsDB to write the summary into.
        backend: Backend that will call the LLM.

    Returns:
        The generated SummaryResult.
    """
    conversation_id: str = conversation_row["conversation_id"]
    session_id: str = conversation_row["session_id"]
    event_start: int = conversation_row["event_index_start"]
    event_end: int = conversation_row["event_index_end"]

    all_events = store.iter_events(session_id)
    conv_events = all_events[event_start : event_end + 1]

    text = _build_conversation_text(conv_events)
    logger.debug(
        "Summarizing conversation %s (%d events, %d chars)",
        conversation_id,
        len(conv_events),
        len(text),
    )

    result = await backend.generate(text)

    # Append derived events to the event store (source of truth).
    store.append(
        SummaryUpdateEvent(
            source=EventSource.SYSTEM,
            session_id=session_id,
            summary_short=result["summary_short"],
            summary_long=result["summary_long"],
            topics=result["topics"],
        )
    )
    store.append(
        TopicExtractionEvent(
            source=EventSource.SYSTEM,
            session_id=session_id,
            topics=result["topics"],
            conversation_id=conversation_id,
        )
    )

    # Write derived index to SQLite.
    await db.insert_summary(
        conversation_id=conversation_id,
        summary_short=result["summary_short"],
        summary_long=result["summary_long"],
        topics=result["topics"],
        model_used=backend.model_name,
    )
    return result
