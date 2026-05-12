"""FastAPI dependency functions for shared application state."""

from __future__ import annotations

from fastapi import Request

from src.adapters.base import AdapterPlugin
from src.replay.db import ConversationsDB
from src.replay.snapshot_store import SnapshotStore
from src.replay.summarizer import SummarizerBackend
from src.store.event_store import EventStore


def get_store(request: Request) -> EventStore:
    """Return the shared EventStore instance."""
    return request.app.state.store  # type: ignore[no-any-return]


def get_db(request: Request) -> ConversationsDB:
    """Return the shared ConversationsDB instance."""
    return request.app.state.db  # type: ignore[no-any-return]


def get_adapters(request: Request) -> dict[str, AdapterPlugin]:
    """Return the adapter registry keyed by source_name."""
    return request.app.state.adapters  # type: ignore[no-any-return]


def get_summarizer(request: Request) -> SummarizerBackend:
    """Return the active SummarizerBackend instance."""
    return request.app.state.summarizer  # type: ignore[no-any-return]


def get_snapshot_store(request: Request) -> SnapshotStore:
    """Return the shared SnapshotStore instance."""
    return request.app.state.snapshot_store  # type: ignore[no-any-return]
