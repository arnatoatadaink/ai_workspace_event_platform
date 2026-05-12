"""Replay Engine: Topic embedding with DB-backed cache.

Embeds topic strings into dense vectors for UMAP projection.
Cache hits avoid re-embedding identical topic strings across runs.

Usage::

    backend = SentenceTransformerBackend()
    async with ConversationsDB() as db:
        vectors = await vectorize_topics(["FastAPI", "Python"], db, backend)
"""

from __future__ import annotations

import logging
import struct
from typing import Protocol, runtime_checkable

import numpy as np

from src.replay.db import ConversationsDB

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "data/models/all-MiniLM-L6-v2"


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Protocol for embedding backends."""

    model_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text (same order)."""
        ...


class SentenceTransformerBackend:
    """Local sentence-transformers embedding backend.

    Downloads the model on first use; subsequent runs use the local cache.

    Args:
        model: sentence-transformers model name.
    """

    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        self.model_name = model
        self._encoder: object | None = None

    def _get_encoder(self) -> object:
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode *texts* synchronously (sentence-transformers has no async API)."""
        import asyncio

        loop = asyncio.get_event_loop()
        encoder = self._get_encoder()
        vectors: np.ndarray = await loop.run_in_executor(
            None,
            lambda: encoder.encode(texts, show_progress_bar=False),  # type: ignore[union-attr]
        )
        return [v.tolist() for v in vectors]


def _pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(data: bytes) -> list[float]:
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


async def vectorize_topics(
    topics: list[str],
    db: ConversationsDB,
    backend: EmbeddingBackend,
) -> dict[str, np.ndarray]:
    """Return embedding arrays keyed by topic string, using DB cache.

    Topics already in the ``topic_embeddings`` table are returned from cache
    without calling the backend. New topics are embedded in batch and stored.

    Args:
        topics: List of topic strings to embed (duplicates deduplicated).
        db: Open ConversationsDB for cache read/write.
        backend: Backend used to embed uncached topics.

    Returns:
        Mapping of topic → 1-D numpy float32 array.
    """
    unique = list(dict.fromkeys(t.strip() for t in topics if t.strip()))
    if not unique:
        return {}

    result: dict[str, np.ndarray] = {}
    uncached: list[str] = []

    for topic in unique:
        cached = await db.get_embedding(topic)
        if cached is not None:
            result[topic] = np.array(_unpack_vector(cached), dtype=np.float32)
        else:
            uncached.append(topic)

    if uncached:
        logger.debug("Embedding %d uncached topics via %s", len(uncached), backend.model_name)
        vectors = await backend.embed(uncached)
        for topic, vec in zip(uncached, vectors):
            arr = np.array(vec, dtype=np.float32)
            await db.upsert_embedding(topic, _pack_vector(vec), backend.model_name)
            result[topic] = arr

    return result
