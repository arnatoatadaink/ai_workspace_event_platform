"""FastAPI application for AI Workspace Event Platform.

Startup initialises shared resources (EventStore, ConversationsDB, adapter
registry) and mounts all routers. Run via:

    uvicorn src.api.main:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.adapters.claude.adapter import ClaudeAdapter
from src.api.routers import (
    claude_scan,
    conversations,
    dataflow,
    events,
    ingest,
    plugins,
    sessions,
    settings,
    summarize,
    topic_graph,
    topics,
    umap,
    ws,
)
from src.api.settings_store import build_backend, load_summarizer_settings
from src.api.summarization_throttle import SummarizationThrottle
from src.replay.db import ConversationsDB
from src.replay.pipeline import SummaryTopicPipeline
from src.replay.snapshot_store import SnapshotStore
from src.store.event_store import EventStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared state on startup; clean up on shutdown."""
    store = EventStore()
    db = ConversationsDB()
    await db.connect()

    snapshot_store = SnapshotStore()
    await snapshot_store.connect()

    summarizer = build_backend(load_summarizer_settings())
    pipeline = SummaryTopicPipeline(
        store=store,
        db=db,
        snapshot_store=snapshot_store,
        summarizer=summarizer,
    )
    pipeline_task = asyncio.create_task(pipeline.run_loop())

    # Adapter registry: add new adapters here as they are implemented.
    claude_adapter = ClaudeAdapter()
    app.state.adapters = {claude_adapter.source_name: claude_adapter}
    app.state.store = store
    app.state.db = db
    app.state.snapshot_store = snapshot_store
    app.state.pipeline = pipeline
    app.state.summarizer = summarizer
    app.state.throttle = SummarizationThrottle()

    yield

    pipeline.stop()
    pipeline_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
        await asyncio.wait_for(pipeline_task, timeout=5.0)
    await snapshot_store.close()
    await db.close()


app = FastAPI(
    title="AI Workspace Event Platform",
    description="Event sourcing API for Claude CLI AI interactions.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


app.include_router(ingest.router)
app.include_router(sessions.router)
app.include_router(conversations.router)
app.include_router(summarize.router)
app.include_router(events.router)
app.include_router(topics.router)
app.include_router(plugins.router)
app.include_router(ws.router)
app.include_router(claude_scan.router)
app.include_router(umap.router)
app.include_router(dataflow.router)
app.include_router(topic_graph.router)
app.include_router(settings.router)
