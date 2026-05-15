"""Claude CLI adapter.

Parses Claude Code hook payloads (Stop, PreToolUse, PostToolUse)
and converts them to InternalEvent instances.

Hook payload arrives via stdin as JSON when a hook fires.
We minimise stdout-parsing; only structured hook payloads are consumed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.adapters.base import AdapterPlugin
from src.adapters.claude.paths import transcript_path_for_session
from src.adapters.claude.transcript import parse_transcript_messages, write_cursor
from src.schemas.internal_event_v1 import (
    ApprovalEvent,
    EventSource,
    InternalEvent,
    StopEvent,
    ToolCallEvent,
    ToolResultEvent,
)

logger = logging.getLogger(__name__)

_SOURCE = EventSource.CLAUDE_CLI
_DEFAULT_CURSOR_DIR = "runtime/transcript_cursors"
_DEFAULT_STORE_BASE = "runtime/sessions"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


class ClaudeAdapter(AdapterPlugin):
    """Adapter for Claude Code hook payloads.

    Args:
        cursor_dir: Directory for per-session transcript cursor files.
        store_base: Root of the event store (used to detect existing sessions
            for the migration heuristic).
    """

    def __init__(
        self,
        cursor_dir: str | Path = _DEFAULT_CURSOR_DIR,
        store_base: str | Path = _DEFAULT_STORE_BASE,
        claude_project_dir: str | Path | None = None,
    ) -> None:
        self._cursor_dir = Path(cursor_dir)
        self._store_base = Path(store_base)
        # Capture CWD at init time; used to derive transcript_path when the
        # Stop hook payload omits it (older Claude Code versions don't include it).
        self._claude_project_dir: Path | None = (
            Path(claude_project_dir) if claude_project_dir else None
        )

    @property
    def source_name(self) -> str:
        return _SOURCE.value

    @property
    def description(self) -> str:
        return "Claude CLI (Claude Code) hook events — Stop / PreToolUse / PostToolUse"

    def parse(self, raw_payload: dict) -> list[InternalEvent]:
        """Dispatch by hook_event_name. Returns [] on any error."""
        try:
            hook = raw_payload.get("hook_event_name", "")
            session_id = raw_payload.get("session_id", "unknown")
            if hook == "Stop":
                return self._parse_stop(raw_payload, session_id)
            if hook == "PreToolUse":
                return [self._parse_pre_tool_use(raw_payload, session_id)]
            if hook == "PostToolUse":
                return self._parse_post_tool_use(raw_payload, session_id)
            logger.debug("ClaudeAdapter: unhandled hook_event_name=%r", hook)
            return []
        except Exception:
            logger.exception("ClaudeAdapter.parse failed for payload=%r", raw_payload)
            return []

    # ------------------------------------------------------------------
    # Hook-specific parsers
    # ------------------------------------------------------------------

    def _parse_stop(self, payload: dict, session_id: str) -> list[InternalEvent]:
        """Parse Stop hook: emit MessageEvents from transcript, then StopEvent."""
        events: list[InternalEvent] = []

        transcript_path_str = payload.get("transcript_path")
        if not transcript_path_str and self._claude_project_dir is None:
            # Derive from CWD captured at init time (older Claude Code versions omit
            # transcript_path from the Stop payload).
            derived = transcript_path_for_session(session_id)
            if derived.exists():
                transcript_path_str = str(derived)
                logger.debug(
                    "ClaudeAdapter: transcript_path absent in payload; derived %s",
                    transcript_path_str,
                )
        elif not transcript_path_str and self._claude_project_dir is not None:
            derived = self._claude_project_dir / f"{session_id}.jsonl"
            if derived.exists():
                transcript_path_str = str(derived)

        if transcript_path_str:
            transcript_path = Path(transcript_path_str)
            cursor_path = self._cursor_dir / f"{session_id}.cursor"
            try:
                msg_events, new_line_count = parse_transcript_messages(
                    transcript_path=transcript_path,
                    session_id=session_id,
                    cursor_path=cursor_path,
                    store_base=self._store_base,
                )
                events.extend(msg_events)
                write_cursor(cursor_path, new_line_count)
            except Exception:
                logger.exception(
                    "ClaudeAdapter: transcript parse failed for session=%r", session_id
                )

        events.append(
            StopEvent(
                event_id=_uid(),
                source=_SOURCE,
                session_id=session_id,
                timestamp=_now(),
                stop_reason=payload.get("stop_reason"),
            )
        )
        return events

    def _parse_pre_tool_use(self, payload: dict, session_id: str) -> ApprovalEvent:
        return ApprovalEvent(
            event_id=_uid(),
            source=_SOURCE,
            session_id=session_id,
            timestamp=_now(),
            tool_name=payload.get("tool_name", ""),
            tool_input=payload.get("tool_input", {}),
        )

    def _parse_post_tool_use(self, payload: dict, session_id: str) -> list[InternalEvent]:
        tool_use_id = payload.get("tool_use_id") or _uid()
        tool_call = ToolCallEvent(
            event_id=_uid(),
            source=_SOURCE,
            session_id=session_id,
            timestamp=_now(),
            tool_name=payload.get("tool_name", ""),
            tool_input=payload.get("tool_input", {}),
            tool_use_id=tool_use_id,
        )
        tool_result = ToolResultEvent(
            event_id=_uid(),
            source=_SOURCE,
            session_id=session_id,
            timestamp=_now(),
            tool_use_id=tool_use_id,
            content=payload.get("tool_response", ""),
            is_error=bool(payload.get("is_error", False)),
        )
        return [tool_call, tool_result]
