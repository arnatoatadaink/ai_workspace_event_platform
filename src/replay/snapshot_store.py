"""Replay Engine: SnapshotStore — file-backed snapshot persistence with SQLite index.

Storage layout:
  DB  : runtime/replay.db  — ``snapshots`` table (path index)
  File: runtime/snapshots/<session_id>/<snapshot_id>.json  — immutable JSON blob

Used internally by ``snapshot.run_incremental_update``.  Import
``SnapshotStore`` from ``src.replay.snapshot`` for external use.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from src.replay.snapshot_models import SnapshotMetadata

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("runtime/replay.db")
_DEFAULT_SNAP_DIR = Path("runtime/snapshots")


class SnapshotStore:
    """File-backed snapshot storage with SQLite index.

    Opens an independent connection to the shared ``runtime/replay.db`` to
    manage the ``snapshots`` table.  Helper private methods also query
    ``conversations`` and ``conversation_summaries`` (owned by ConversationsDB)
    to build snapshot metadata without loading event files.
    """

    def __init__(
        self,
        snap_dir: str | Path = _DEFAULT_SNAP_DIR,
        db_path: str | Path = _DEFAULT_DB_PATH,
    ) -> None:
        self._snap_dir = Path(snap_dir)
        self._db_path = Path(db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Open the connection and ensure the snapshots table exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._init_schema()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> SnapshotStore:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _init_schema(self) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "  snapshot_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,"
            "  file_path TEXT NOT NULL, created_at TEXT NOT NULL,"
            "  chunk_first TEXT NOT NULL, chunk_last TEXT NOT NULL,"
            "  event_index_start INTEGER NOT NULL, event_index_end INTEGER NOT NULL"
            ")"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_session_created"
            " ON snapshots (session_id, created_at DESC)"
        )
        await self._conn.commit()

    async def _insert_snapshot_row(
        self, session_id: str, metadata: SnapshotMetadata, file_path: Path
    ) -> None:
        assert self._conn is not None
        er = metadata.event_range
        await self._conn.execute(
            "INSERT INTO snapshots"
            "  (snapshot_id, session_id, file_path, created_at,"
            "   chunk_first, chunk_last, event_index_start, event_index_end)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                metadata.snapshot_id,
                session_id,
                str(file_path),
                metadata.created_at.isoformat(),
                er.chunk_first,
                er.chunk_last,
                er.event_index_start,
                er.event_index_end,
            ),
        )
        await self._conn.commit()

    async def _get_latest_snapshot_row(self, session_id: str) -> Optional[dict[str, Any]]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT snapshot_id, file_path FROM snapshots"
            " WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        row = await cur.fetchone()
        return {"snapshot_id": row[0], "file_path": row[1]} if row else None

    async def _get_session_event_range(self, session_id: str) -> Optional[dict[str, Any]]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT MIN(event_index_start), MAX(event_index_end),"
            "       MIN(chunk_file_first),  MAX(chunk_file_last)"
            " FROM conversations WHERE session_id = ?",
            (session_id,),
        )
        row = await cur.fetchone()
        if row is None or row[0] is None:
            return None
        return {
            "event_index_start": int(row[0]),
            "event_index_end": int(row[1]),
            "chunk_first": str(row[2]),
            "chunk_last": str(row[3]),
        }

    async def _get_all_topics(self, session_id: str) -> list[str]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT cs.topics"
            " FROM conversation_summaries cs"
            " JOIN conversations c ON cs.conversation_id = c.conversation_id"
            " WHERE c.session_id = ?",
            (session_id,),
        )
        rows = await cur.fetchall()
        topics: set[str] = set()
        for (topics_json,) in rows:
            topics.update(json.loads(topics_json))
        return sorted(topics)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(self, session_id: str, metadata: SnapshotMetadata) -> Path:
        """Persist *metadata* to a JSON file and record the path in the DB.

        Files are immutable once written; old snapshots are archived in-place.

        Returns:
            Path to the written JSON file.
        """
        snap_dir = self._snap_dir / session_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        file_path = snap_dir / f"{metadata.snapshot_id}.json"
        file_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
        await self._insert_snapshot_row(session_id, metadata, file_path)
        return file_path

    async def load(self, session_id: str, snapshot_id: str) -> Optional[SnapshotMetadata]:
        """Load a specific snapshot by ID from its JSON file."""
        file_path = self._snap_dir / session_id / f"{snapshot_id}.json"
        if not file_path.exists():
            return None
        return SnapshotMetadata.model_validate_json(file_path.read_text(encoding="utf-8"))

    async def get_latest(self, session_id: str) -> Optional[SnapshotMetadata]:
        """Return the most recently created snapshot for *session_id*, or None."""
        row = await self._get_latest_snapshot_row(session_id)
        if row is None:
            return None
        return await self.load(session_id, row["snapshot_id"])
