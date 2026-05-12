"""Replay Engine: Snapshot Pydantic models (v1.2 §Replay Snapshot Metadata)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class EventRange(BaseModel):
    chunk_first: str
    chunk_last: str
    event_index_start: int
    event_index_end: int


class ContextLength(BaseModel):
    event_count: int
    estimated_tokens: int  # heuristic: event_count * 150


class TopicSummary(BaseModel):
    topics: list[str]
    umap_projection: Optional[list[list[float]]] = None  # populated in STEP 4


class SnapshotMetadata(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_range: EventRange
    context_length: ContextLength
    chunk_count: int
    topic_summary: TopicSummary
