"""Claude transcript JSONL parser with cursor-based deduplication.

Parses ``user`` and ``assistant`` entries from Claude CLI transcript files
and emits ``MessageEvent`` instances for new messages only.

Cursor files live in ``runtime/transcript_cursors/<session_id>.cursor`` and
record the number of transcript lines already processed.  On the very first
invocation for a session that already has stored events (migration case) the
cursor is initialized to the current transcript length, skipping backfill.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.schemas.internal_event_v1 import EventSource, MessageEvent

logger = logging.getLogger(__name__)

_SOURCE = EventSource.CLAUDE_CLI


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def read_cursor(cursor_path: Path) -> Optional[int]:
    """Return the stored cursor value, or None if the file does not exist."""
    if not cursor_path.exists():
        return None
    try:
        return int(cursor_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def write_cursor(cursor_path: Path, lines: int) -> None:
    """Persist the cursor (lines processed so far)."""
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(str(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Session detection (migration guard)
# ---------------------------------------------------------------------------


def session_has_stored_events(store_base: Path, session_id: str) -> bool:
    """Return True if the session directory already contains event chunks."""
    session_dir = store_base / session_id
    if not session_dir.exists():
        return False
    return any(session_dir.glob("events_*.jsonl"))


# ---------------------------------------------------------------------------
# Content extraction helpers
# ---------------------------------------------------------------------------


def _extract_user_text(content: object) -> Optional[str]:
    """Return user message text, or None for non-text turns (tool-result blocks)."""
    if isinstance(content, str):
        return content.strip() or None
    # List content means tool_result blocks — skip these (already captured by PostToolUse).
    return None


def _extract_assistant_text(content: object) -> Optional[str]:
    """Concatenate ``text`` blocks from an assistant content list; skip thinking/tool_use."""
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts).strip() or None


def _parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_transcript_messages(
    transcript_path: Path,
    session_id: str,
    cursor_path: Path,
    store_base: Path,
) -> tuple[list[MessageEvent], int]:
    """Parse new main-thread messages from *transcript_path* since the last cursor.

    Migration heuristic: if no cursor file exists but the session already has
    stored events, skip backfill by advancing the cursor to the current end of
    the transcript.  This prevents flooding existing sessions with retrospective
    MessageEvents.

    Returns:
        (message_events, new_line_count)  — caller must persist new_line_count.
    """
    if not transcript_path.exists():
        stored_cursor = read_cursor(cursor_path)
        return [], stored_cursor if stored_cursor is not None else 0

    # Read all lines once (transcripts are small — typically < 10 K lines).
    try:
        with transcript_path.open(encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
    except OSError:
        logger.exception("Cannot read transcript at %s", transcript_path)
        stored_cursor = read_cursor(cursor_path)
        return [], stored_cursor if stored_cursor is not None else 0

    total_lines = len(all_lines)
    stored_cursor = read_cursor(cursor_path)

    # Migration guard: cursor file absent + session already has stored events → skip backfill.
    if stored_cursor is None and session_has_stored_events(store_base, session_id):
        logger.debug(
            "Transcript migration: initialising cursor to %d for existing session %s",
            total_lines,
            session_id,
        )
        return [], total_lines

    start_line = stored_cursor if stored_cursor is not None else 0
    events: list[MessageEvent] = []

    for lineno, raw_line in enumerate(all_lines):
        if lineno < start_line:
            continue

        line = raw_line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Malformed transcript line %d in %s", lineno, transcript_path)
            continue

        # Only main-thread user/assistant messages.
        if entry.get("isSidechain", False):
            continue
        entry_type = entry.get("type")
        if entry_type not in ("user", "assistant"):
            continue

        ts_str = entry.get("timestamp")
        timestamp = _parse_ts(ts_str) if ts_str else datetime.now(timezone.utc)
        entry_uuid = entry.get("uuid") or str(uuid.uuid4())
        msg = entry.get("message", {})
        role = msg.get("role")

        if role == "user":
            text = _extract_user_text(msg.get("content", ""))
            if text is None:
                continue
            events.append(
                MessageEvent(
                    event_id=entry_uuid,
                    source=_SOURCE,
                    session_id=session_id,
                    timestamp=timestamp,
                    role="user",
                    content=text,
                )
            )

        elif role == "assistant":
            text = _extract_assistant_text(msg.get("content", []))
            if text is None:
                continue
            events.append(
                MessageEvent(
                    event_id=entry_uuid,
                    source=_SOURCE,
                    session_id=session_id,
                    timestamp=timestamp,
                    role="assistant",
                    content=text,
                )
            )

    return events, total_lines
