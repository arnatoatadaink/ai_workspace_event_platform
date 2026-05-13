"""Replay Engine: SQLite-backed conversation index database.

DB location: runtime/replay.db — single global DB to support cross-session
queries (UMAP, topic graph) in later steps without schema migration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

_DEFAULT_DB_PATH = Path("runtime/replay.db")

_COLUMNS = (
    "conversation_id",
    "session_id",
    "chunk_file_first",
    "chunk_file_last",
    "event_index_start",
    "event_index_end",
    "created_at",
    "message_count",
)

_SUMMARY_COLUMNS = (
    "conversation_id",
    "summary_short",
    "summary_long",
    "topics",
    "generated_at",
    "model_used",
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(zip(_COLUMNS, row))


def _row_to_summary_dict(row: Any) -> dict[str, Any]:
    d = dict(zip(_SUMMARY_COLUMNS, row))
    d["topics"] = json.loads(d["topics"])
    return d


_CONV_SUMMARY_COLUMNS = (
    "conversation_id",
    "session_id",
    "created_at",
    "message_count",
    "summary_short",
    "topics",
    "generated_at",
    "model_used",
)


def _row_to_conv_summary(row: Any) -> dict[str, Any]:
    d = dict(zip(_CONV_SUMMARY_COLUMNS, row))
    d["topics"] = json.loads(d["topics"])
    return d


_CONV_LEFT_JOIN_COLUMNS = (
    "conversation_id",
    "session_id",
    "created_at",
    "message_count",
    "event_index_start",
    "event_index_end",
    "summary_short",
    "topics",
)


def _row_to_conv_left_join(row: Any) -> dict[str, Any]:
    d = dict(zip(_CONV_LEFT_JOIN_COLUMNS, row))
    raw = d["topics"]
    d["topics"] = json.loads(raw) if raw is not None else None
    return d


class ConversationsDB:
    """Async SQLite index of conversation boundaries extracted from JSONL chunks.

    Usage::

        async with ConversationsDB() as db:
            await db.insert_conversation(...)
            rows = await db.get_latest_conversations("session_x", limit=10)
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Open the connection and ensure schema exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._init_schema()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> ConversationsDB:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def _init_schema(self) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id   TEXT PRIMARY KEY,
                session_id        TEXT NOT NULL,
                chunk_file_first  TEXT NOT NULL,
                chunk_file_last   TEXT NOT NULL,
                event_index_start INTEGER NOT NULL,
                event_index_end   INTEGER NOT NULL,
                created_at        TEXT NOT NULL,
                message_count     INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversations_session_created
            ON conversations (session_id, created_at DESC)
            """
        )
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                conversation_id  TEXT PRIMARY KEY
                                     REFERENCES conversations(conversation_id),
                summary_short    TEXT NOT NULL,
                summary_long     TEXT NOT NULL,
                topics           TEXT NOT NULL,
                generated_at     TEXT NOT NULL,
                model_used       TEXT NOT NULL
            )
            """
        )
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_embeddings (
                topic        TEXT PRIMARY KEY,
                vector       BLOB NOT NULL,
                model        TEXT NOT NULL,
                generated_at TEXT NOT NULL
            )
            """
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def insert_conversation(
        self,
        *,
        conversation_id: str,
        session_id: str,
        chunk_file_first: str,
        chunk_file_last: str,
        event_index_start: int,
        event_index_end: int,
        created_at: datetime,
        message_count: int,
    ) -> None:
        """Insert a new conversation index record."""
        assert self._conn is not None
        await self._conn.execute(
            """
            INSERT INTO conversations
              (conversation_id, session_id, chunk_file_first, chunk_file_last,
               event_index_start, event_index_end, created_at, message_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                session_id,
                chunk_file_first,
                chunk_file_last,
                event_index_start,
                event_index_end,
                created_at.isoformat(),
                message_count,
            ),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_latest_conversations(
        self,
        session_id: str,
        limit: int = 10,
        before_conversation_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return conversations newest-first with optional cursor paging.

        Args:
            session_id: Target session.
            limit: Maximum rows to return.
            before_conversation_id: If given, return only conversations whose
                ``created_at`` is strictly before that conversation (keyset
                pagination — avoids offset skew on concurrent inserts).

        Returns:
            List of row dicts ordered newest-first.
        """
        assert self._conn is not None

        if before_conversation_id is None:
            cur = await self._conn.execute(
                """
                SELECT conversation_id, session_id, chunk_file_first, chunk_file_last,
                       event_index_start, event_index_end, created_at, message_count
                FROM conversations
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
        else:
            ref_cur = await self._conn.execute(
                "SELECT created_at FROM conversations WHERE conversation_id = ?",
                (before_conversation_id,),
            )
            ref_row = await ref_cur.fetchone()
            if ref_row is None:
                return []
            before_ts: str = ref_row[0]
            cur = await self._conn.execute(
                """
                SELECT conversation_id, session_id, chunk_file_first, chunk_file_last,
                       event_index_start, event_index_end, created_at, message_count
                FROM conversations
                WHERE session_id = ? AND created_at < ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, before_ts, limit),
            )

        rows = await cur.fetchall()
        return [_row_to_dict(row) for row in rows]

    async def get_conversation_by_id(self, conversation_id: str) -> Optional[dict[str, Any]]:
        """Return a single conversation row by its ID, or None if not found."""
        assert self._conn is not None
        cur = await self._conn.execute(
            """
            SELECT conversation_id, session_id, chunk_file_first, chunk_file_last,
                   event_index_start, event_index_end, created_at, message_count
            FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None

    async def get_last_indexed_event(self, session_id: str) -> Optional[int]:
        """Return the highest ``event_index_end`` for a session.

        Used by the incremental indexer (1-n) to detect unprocessed events.
        Returns ``None`` if no conversations have been indexed yet.
        """
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT MAX(event_index_end) FROM conversations WHERE session_id = ?",
            (session_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    async def get_conversation_index_ranges(self, session_id: str) -> list[tuple[int, int]]:
        """Return (event_index_start, event_index_end) for every conversation in a session.

        Ordered by event_index_start ascending.  Used by the pipeline analyzer
        to determine which store events are not yet covered by any DB record.
        """
        assert self._conn is not None
        cur = await self._conn.execute(
            """
            SELECT event_index_start, event_index_end
            FROM conversations
            WHERE session_id = ?
            ORDER BY event_index_start
            """,
            (session_id,),
        )
        rows = await cur.fetchall()
        return [(int(row[0]), int(row[1])) for row in rows]

    # ------------------------------------------------------------------
    # Summary write/read
    # ------------------------------------------------------------------

    async def insert_summary(
        self,
        *,
        conversation_id: str,
        summary_short: str,
        summary_long: str,
        topics: list[str],
        model_used: str,
    ) -> None:
        """Insert or replace a summary for a conversation."""
        assert self._conn is not None
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO conversation_summaries
              (conversation_id, summary_short, summary_long, topics, generated_at, model_used)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                summary_short,
                summary_long,
                json.dumps(topics, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
                model_used,
            ),
        )
        await self._conn.commit()

    async def get_summary(self, conversation_id: str) -> Optional[dict[str, Any]]:
        """Return the summary row for a conversation, or None if not yet generated."""
        assert self._conn is not None
        cur = await self._conn.execute(
            """
            SELECT conversation_id, summary_short, summary_long, topics, generated_at, model_used
            FROM conversation_summaries
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        row = await cur.fetchone()
        return _row_to_summary_dict(row) if row else None

    async def get_all_conversations(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Return all conversations across all sessions, newest-first."""
        assert self._conn is not None
        cur = await self._conn.execute(
            """
            SELECT conversation_id, session_id, chunk_file_first, chunk_file_last,
                   event_index_start, event_index_end, created_at, message_count
            FROM conversations
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [_row_to_dict(row) for row in rows]

    async def get_conversations_with_summaries(
        self,
        session_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return conversations INNER JOINed with their summaries.

        Only conversations that already have a generated summary are returned.
        Filtered by *session_id* and/or *since* (UTC datetime) when provided.
        Ordered newest-first.
        """
        assert self._conn is not None
        conditions: list[str] = []
        params: list[Any] = []

        if session_id is not None:
            conditions.append("c.session_id = ?")
            params.append(session_id)

        if since is not None:
            conditions.append("c.created_at >= ?")
            params.append(since.isoformat())

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        cur = await self._conn.execute(
            f"""
            SELECT c.conversation_id, c.session_id, c.created_at, c.message_count,
                   cs.summary_short, cs.topics, cs.generated_at, cs.model_used
            FROM conversations c
            INNER JOIN conversation_summaries cs
                    ON c.conversation_id = cs.conversation_id
            {where}
            ORDER BY c.created_at DESC
            LIMIT ?
            """,
            params,
        )
        rows = await cur.fetchall()
        return [_row_to_conv_summary(row) for row in rows]

    async def get_latest_conversations_with_summaries_cursor(
        self,
        session_id: str,
        limit: int = 10,
        before_conversation_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Newest-first conversations with optional summary data (LEFT JOIN).

        Conversations without summaries are included with ``summary_short=None``
        and ``topics=None``, ensuring the GUI always sees the freshest entries
        even when the summary pipeline is lagging behind ingest.

        Supports keyset cursor paging via ``before_conversation_id`` — identical
        semantics to :meth:`get_latest_conversations`.
        """
        assert self._conn is not None

        if before_conversation_id is None:
            cur = await self._conn.execute(
                """
                SELECT c.conversation_id, c.session_id, c.created_at, c.message_count,
                       c.event_index_start, c.event_index_end,
                       cs.summary_short, cs.topics
                FROM conversations c
                LEFT JOIN conversation_summaries cs
                       ON c.conversation_id = cs.conversation_id
                WHERE c.session_id = ?
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
        else:
            ref_cur = await self._conn.execute(
                "SELECT created_at FROM conversations WHERE conversation_id = ?",
                (before_conversation_id,),
            )
            ref_row = await ref_cur.fetchone()
            if ref_row is None:
                return []
            before_ts: str = ref_row[0]
            cur = await self._conn.execute(
                """
                SELECT c.conversation_id, c.session_id, c.created_at, c.message_count,
                       c.event_index_start, c.event_index_end,
                       cs.summary_short, cs.topics
                FROM conversations c
                LEFT JOIN conversation_summaries cs
                       ON c.conversation_id = cs.conversation_id
                WHERE c.session_id = ? AND c.created_at < ?
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (session_id, before_ts, limit),
            )

        rows = await cur.fetchall()
        return [_row_to_conv_left_join(row) for row in rows]

    async def get_session_stats(self, session_id: str) -> dict[str, int]:
        """Return conversation_count and summarized_count for a session."""
        assert self._conn is not None
        cur = await self._conn.execute(
            """
            SELECT
                COUNT(*) AS conversation_count,
                SUM(CASE WHEN cs.conversation_id IS NOT NULL THEN 1 ELSE 0 END) AS summarized_count
            FROM conversations c
            LEFT JOIN conversation_summaries cs ON c.conversation_id = cs.conversation_id
            WHERE c.session_id = ?
            """,
            (session_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return {"conversation_count": 0, "summarized_count": 0}
        return {
            "conversation_count": int(row[0] or 0),
            "summarized_count": int(row[1] or 0),
        }

    async def get_unsummarized_conversations(self, session_id: str) -> list[dict[str, Any]]:
        """Return conversations for *session_id* that have no summary yet.

        Results are ordered oldest-first so the pipeline processes in
        chronological order.
        """
        assert self._conn is not None
        cur = await self._conn.execute(
            """
            SELECT c.conversation_id, c.session_id, c.chunk_file_first, c.chunk_file_last,
                   c.event_index_start, c.event_index_end, c.created_at, c.message_count
            FROM conversations c
            LEFT JOIN conversation_summaries cs
                   ON c.conversation_id = cs.conversation_id
            WHERE c.session_id = ?
              AND cs.conversation_id IS NULL
            ORDER BY c.created_at ASC
            """,
            (session_id,),
        )
        rows = await cur.fetchall()
        return [_row_to_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Topic embedding cache
    # ------------------------------------------------------------------

    async def get_embedding(self, topic: str) -> Optional[bytes]:
        """Return cached embedding bytes for *topic*, or None if not cached."""
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT vector FROM topic_embeddings WHERE topic = ?",
            (topic,),
        )
        row = await cur.fetchone()
        return bytes(row[0]) if row else None

    async def upsert_embedding(self, topic: str, vector: bytes, model: str) -> None:
        """Insert or replace an embedding record for *topic*."""
        assert self._conn is not None
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO topic_embeddings (topic, vector, model, generated_at)
            VALUES (?, ?, ?, ?)
            """,
            (topic, vector, model, datetime.now(timezone.utc).isoformat()),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # UMAP topic aggregation
    # ------------------------------------------------------------------

    async def get_topics_for_umap(
        self,
        session_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Return topic occurrences for UMAP projection.

        Each row: ``{topic, count, session_id, first_seen}``.
        Grouped by (topic, session_id) so color-by-session is natural.
        Only conversations with summaries are included.

        Args:
            session_id: Filter to a single session when provided.
            since: Include only conversations created at or after this UTC datetime.
            until: Include only conversations created before this UTC datetime.
        """
        assert self._conn is not None
        conditions: list[str] = []
        params: list[Any] = []

        if session_id is not None:
            conditions.append("c.session_id = ?")
            params.append(session_id)

        if since is not None:
            conditions.append("c.created_at >= ?")
            params.append(since.isoformat())

        if until is not None:
            conditions.append("c.created_at < ?")
            params.append(until.isoformat())

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cur = await self._conn.execute(
            f"""
            SELECT
                t.value     AS topic,
                COUNT(*)    AS count,
                c.session_id,
                MIN(c.created_at) AS first_seen
            FROM conversation_summaries cs
            INNER JOIN conversations c ON c.conversation_id = cs.conversation_id
            JOIN json_each(cs.topics) AS t
            {where}
            GROUP BY t.value, c.session_id
            ORDER BY count DESC
            """,
            params,
        )
        rows = await cur.fetchall()
        return [
            {
                "topic": row[0],
                "count": row[1],
                "session_id": row[2],
                "first_seen": row[3],
            }
            for row in rows
        ]
