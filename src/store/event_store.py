"""Append-only JSONL Event Store.

Storage layout:
  runtime/sessions/<session_id>/events_<NNNN>.jsonl

Rules:
  - Append-only: stored events are never mutated or deleted.
  - Chunk rotation: new chunk file when current exceeds CHUNK_SIZE lines.
  - Downstream layers (Replay, GUI) read from this store; they never write back.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.schemas.internal_event_v1 import InternalEvent, parse_event

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10_000
_CHUNK_GLOB = "events_*.jsonl"


def count_chunk_lines(path: Path) -> int:
    """Return the number of non-empty lines in a JSONL chunk file."""
    count = 0
    with path.open("rb") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


class EventStore:
    """Append-only JSONL event store with per-session chunk files."""

    def __init__(
        self,
        base_path: str | Path = "runtime/sessions",
        chunk_size: int = CHUNK_SIZE,
    ) -> None:
        self._base = Path(base_path)
        self._chunk_size = chunk_size

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, event: InternalEvent) -> Path:
        """Append one event to the current chunk. Returns the chunk path."""
        chunk = self._current_chunk(event.session_id)
        with chunk.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return chunk

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def iter_events(self, session_id: str) -> list[InternalEvent]:
        """Read all events for a session in chronological order."""
        events: list[InternalEvent] = []
        for chunk in self._sorted_chunks(session_id):
            events.extend(self._read_chunk(chunk))
        return events

    def iter_chunks(self, session_id: str) -> list[Path]:
        """Return sorted chunk paths for a session."""
        return self._sorted_chunks(session_id)

    def list_sessions(self) -> list[str]:
        """Return all session IDs that have stored events."""
        if not self._base.exists():
            return []
        return [p.name for p in self._base.iterdir() if p.is_dir()]

    def count_events(self, session_id: str) -> int:
        """Count total events for a session without parsing JSON."""
        return sum(self._line_count(c) for c in self._sorted_chunks(session_id))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        path = self._base / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _sorted_chunks(self, session_id: str) -> list[Path]:
        session_dir = self._base / session_id
        if not session_dir.exists():
            return []
        return sorted(session_dir.glob(_CHUNK_GLOB))

    def _current_chunk(self, session_id: str) -> Path:
        session_dir = self._session_dir(session_id)
        chunks = sorted(session_dir.glob(_CHUNK_GLOB))
        if not chunks:
            return session_dir / "events_0001.jsonl"
        latest = chunks[-1]
        if self._line_count(latest) >= self._chunk_size:
            n = int(latest.stem.split("_")[1]) + 1
            return session_dir / f"events_{n:04d}.jsonl"
        return latest

    @staticmethod
    def _line_count(path: Path) -> int:
        return count_chunk_lines(path)

    @staticmethod
    def _read_chunk(path: Path) -> list[InternalEvent]:
        events: list[InternalEvent] = []
        with path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    import json

                    events.append(parse_event(json.loads(line)))
                except Exception as exc:
                    logger.warning("Skipping malformed event at %s line %d: %s", path, lineno, exc)
        return events
