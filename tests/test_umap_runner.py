"""Tests for topic_vectorizer, umap_runner, and umap_render."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from src.replay.db import ConversationsDB
from src.replay.topic_vectorizer import _pack_vector, _unpack_vector, vectorize_topics
from src.replay.umap_render import _scale_size, build_plotly_figure
from src.replay.umap_runner import TopicPoint, run_umap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_db(path: str) -> ConversationsDB:
    db = ConversationsDB(path)
    await db.connect()
    return db


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


async def _seed_summaries(db: ConversationsDB, entries: list[dict[str, Any]]) -> None:
    """Insert conversations + summaries for UMAP queries."""
    for e in entries:
        await db._conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO conversations
              (conversation_id, session_id, chunk_file_first, chunk_file_last,
               event_index_start, event_index_end, created_at, message_count)
            VALUES (?, ?, 'c0.jsonl', 'c0.jsonl', 0, 1, ?, 1)
            """,
            (e["conversation_id"], e["session_id"], e["created_at"]),
        )
        await db._conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO conversation_summaries
              (conversation_id, summary_short, summary_long, topics, generated_at, model_used)
            VALUES (?, 'short', 'long', ?, datetime('now'), 'test-model')
            """,
            (e["conversation_id"], json.dumps(e["topics"])),
        )
    await db._conn.commit()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# vector pack/unpack
# ---------------------------------------------------------------------------


def test_pack_unpack_roundtrip() -> None:
    vec = [0.1, 0.2, 0.3, -1.5]
    packed = _pack_vector(vec)
    restored = _unpack_vector(packed)
    assert len(restored) == 4
    for a, b in zip(vec, restored):
        assert abs(a - b) < 1e-5


# ---------------------------------------------------------------------------
# vectorize_topics: cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vectorize_topics_cache_hit() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = await _make_db(f.name)
        vec = [float(i) for i in range(10)]
        await db.upsert_embedding("Python", _pack_vector(vec), "test-model")

        class _FakeBackend:
            model_name = "test-model"
            embed = AsyncMock(return_value=[])  # must not be called

        result = await vectorize_topics(["Python"], db, _FakeBackend())
        assert "Python" in result
        _FakeBackend.embed.assert_not_called()
        await db.close()


# ---------------------------------------------------------------------------
# vectorize_topics: cache miss → backend called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vectorize_topics_cache_miss() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = await _make_db(f.name)

        fake_vec = [0.1] * 10
        backend = AsyncMock()
        backend.model_name = "test-model"
        backend.embed = AsyncMock(return_value=[fake_vec])

        result = await vectorize_topics(["FastAPI"], db, backend)
        assert "FastAPI" in result
        backend.embed.assert_awaited_once()

        cached = await db.get_embedding("FastAPI")
        assert cached is not None
        await db.close()


# ---------------------------------------------------------------------------
# run_umap: empty DB → empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_umap_empty_db() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = await _make_db(f.name)
        backend = AsyncMock()
        backend.model_name = "test-model"
        result = await run_umap(db, backend)
        assert result == []
        await db.close()


# ---------------------------------------------------------------------------
# run_umap: too few topics (< 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_umap_too_few_topics() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = await _make_db(f.name)
        await _seed_summaries(
            db,
            [
                {
                    "conversation_id": "c1",
                    "session_id": "s1",
                    "created_at": "2026-05-01T10:00:00",
                    "topics": ["Python"],
                }
            ],
        )
        backend = AsyncMock()
        backend.model_name = "test-model"
        result = await run_umap(db, backend)
        assert result == []
        await db.close()


# ---------------------------------------------------------------------------
# run_umap: normal flow with mocked backend + mocked UMAP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_umap_normal() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = await _make_db(f.name)
        await _seed_summaries(
            db,
            [
                {
                    "conversation_id": "c1",
                    "session_id": "sess_a",
                    "created_at": "2026-05-01T10:00:00",
                    "topics": ["Python", "FastAPI", "Pydantic"],
                },
                {
                    "conversation_id": "c2",
                    "session_id": "sess_a",
                    "created_at": "2026-05-02T10:00:00",
                    "topics": ["Python", "SQLite"],
                },
            ],
        )

        dim = 4

        class _FakeBackend:
            model_name = "test-model"

            async def embed(self, texts: list[str]) -> list[list[float]]:
                rng = np.random.default_rng(0)
                return rng.random((len(texts), dim)).tolist()

        class _FakeUMAP:
            def __init__(self, **kwargs: Any) -> None:
                pass

            def fit_transform(self, X: np.ndarray) -> np.ndarray:
                n = X.shape[0]
                rng = np.random.default_rng(42)
                return rng.random((n, 2)).astype(np.float32)

        with patch("src.replay.umap_runner.umap") as mock_umap_mod:
            mock_umap_mod.UMAP = _FakeUMAP
            points = await run_umap(db, _FakeBackend())

        assert len(points) > 0
        for p in points:
            assert isinstance(p, TopicPoint)
            assert p.session_id == "sess_a"
            assert p.count >= 1
        await db.close()


# ---------------------------------------------------------------------------
# run_umap: time window filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_umap_time_filter() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = await _make_db(f.name)
        await _seed_summaries(
            db,
            [
                {
                    "conversation_id": "c1",
                    "session_id": "s1",
                    "created_at": "2026-04-01T10:00:00",
                    "topics": ["April", "Spring"],
                },
                {
                    "conversation_id": "c2",
                    "session_id": "s1",
                    "created_at": "2026-05-01T10:00:00",
                    "topics": ["May", "Summer"],
                },
            ],
        )

        rows = await db.get_topics_for_umap(since=_dt("2026-05-01T00:00:00"))
        topics_found = {r["topic"] for r in rows}
        assert "May" in topics_found
        assert "April" not in topics_found
        await db.close()


# ---------------------------------------------------------------------------
# build_plotly_figure: empty
# ---------------------------------------------------------------------------


def test_build_plotly_figure_empty() -> None:
    fig = build_plotly_figure([])
    assert fig["data"] == []
    assert "annotations" in fig["layout"]


# ---------------------------------------------------------------------------
# build_plotly_figure: normal
# ---------------------------------------------------------------------------


def test_build_plotly_figure_normal() -> None:
    points = [
        TopicPoint("Python", 0.1, 0.2, 3, "sess_a", "sess_a"),
        TopicPoint("FastAPI", 0.5, 0.7, 1, "sess_a", "sess_a"),
        TopicPoint("SQLite", -0.3, 0.4, 2, "sess_b", "sess_b"),
    ]
    fig = build_plotly_figure(points, color_by="session")
    assert len(fig["data"]) == 2  # sess_a, sess_b
    trace_names = {t["name"] for t in fig["data"]}
    assert "sess_a" in trace_names
    assert "sess_b" in trace_names


# ---------------------------------------------------------------------------
# _scale_size edge cases
# ---------------------------------------------------------------------------


def test_scale_size_zero_max() -> None:
    assert _scale_size(0, 0) == 4  # min size


def test_scale_size_max() -> None:
    assert _scale_size(10, 10) == 20  # max size
