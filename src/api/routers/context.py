"""Context injection API: recent conversation context for Claude CLI hooks.

Endpoint
--------
GET /context/recent
    Returns the N most recent summarised conversations as a compact JSON payload
    suitable for injection into Claude's context via Claude Code hooks.

Usage from a hook (bash):
    curl -sf "http://localhost:8001/context/recent?session_id=$SESSION_ID&n=5"

Usage from UserPromptSubmit hook (stdout is appended to the user turn):
    #!/bin/bash
    curl -sf "http://localhost:8001/context/recent?n=5" \\
      | python3 -c "
    import json,sys
    data = json.load(sys.stdin)
    if data['count'] == 0:
        sys.exit(0)
    print('## 過去の会話コンテキスト')
    for c in reversed(data['conversations']):
        print(f\"- [{c['created_at'][:10]}] {c['summary_short']} (topics: {', '.join(c['topics'])})\")
    "
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_db
from src.replay.db import ConversationsDB

router = APIRouter()


class ContextConversation(BaseModel):
    conversation_id: str
    session_id: str
    project_id: str
    created_at: str
    summary_short: str
    topics: list[str]


class RecentContextResponse(BaseModel):
    count: int
    session_id: Optional[str]
    project_id: Optional[str]
    conversations: list[ContextConversation]


@router.get("/context/recent", response_model=RecentContextResponse)
async def get_recent_context(
    n: int = Query(
        default=5,
        ge=1,
        le=20,
        description="Number of recent summarised conversations to return",
    ),
    session_id: Optional[str] = Query(
        default=None,
        description="Return context from this session only",
    ),
    project_id: Optional[str] = Query(
        default=None,
        description="Return context from this project (ignored when session_id is set)",
    ),
    db: ConversationsDB = Depends(get_db),
) -> RecentContextResponse:
    """Return the N most recent summarised conversations for context injection.

    Intended for Claude Code hooks (e.g. ``UserPromptSubmit``) to inject
    recent conversation context into Claude's prompt.

    Scoping rules:
    - ``session_id`` provided → context from that session only
    - ``project_id`` provided (no session_id) → context from that project
    - neither provided → global most-recent context across all projects

    Conversations are returned newest-first.  Reverse the list in the hook
    script to present them chronologically.
    """
    rows = await db.get_recent_context(
        n=n,
        session_id=session_id,
        project_id=project_id,
    )
    return RecentContextResponse(
        count=len(rows),
        session_id=session_id,
        project_id=project_id,
        conversations=[ContextConversation(**r) for r in rows],
    )
