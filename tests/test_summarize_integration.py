"""Integration tests: summarize conversations via LM Studio.

Requires:
  - LM Studio running at http://192.168.2.104:52624/v1
  - model: gemma-4-31b-it@q6_k
  - At least one conversation in runtime/replay.db

Run with:
    poetry run python -m pytest tests/test_summarize_integration.py -v -s
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.replay.db import ConversationsDB
from src.replay.summarizer import OpenAICompatBackend, summarize_conversation
from src.schemas.internal_event_v1 import EventType
from src.store.event_store import EventStore

DB_PATH = Path("runtime/replay.db")
LMSTUDIO_BASE_URL = "http://192.168.2.104:52624/v1"


pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="runtime/replay.db not found — run the API to populate it first",
)


@pytest.fixture
def event_store() -> EventStore:
    return EventStore()


@pytest.fixture
async def db() -> ConversationsDB:
    d = ConversationsDB()
    await d.connect()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_summarize_one_conversation(event_store: EventStore, db: ConversationsDB) -> None:
    """Call LM Studio to summarize 1 conversation and verify DB + event store output."""
    # Pick the conversation with the most messages for a meaningful summary.
    all_convs = await db.get_all_conversations(limit=20)
    assert all_convs, "No conversations in DB — ingest some events first."

    target = max(all_convs, key=lambda c: c["message_count"])
    conversation_id: str = target["conversation_id"]
    session_id: str = target["session_id"]

    print(
        f"\nTarget conversation: {conversation_id} "
        f"(session={session_id}, messages={target['message_count']})"
    )

    # Delete any previous summary to ensure we test the full path.
    async with db._conn.execute(
        "DELETE FROM conversation_summaries WHERE conversation_id = ?",
        (conversation_id,),
    ):
        await db._conn.commit()

    backend = OpenAICompatBackend(base_url=LMSTUDIO_BASE_URL)
    events_before = event_store.count_events(session_id)

    result = await summarize_conversation(target, event_store, db, backend)

    print(f"  summary_short : {result['summary_short']}")
    print(f"  topics        : {result['topics']}")

    # --- assertions ---
    assert result["summary_short"], "summary_short must not be empty"
    assert result["summary_long"], "summary_long must not be empty"
    assert len(result["topics"]) >= 1, "at least one topic expected"

    # DB should now have the summary.
    saved = await db.get_summary(conversation_id)
    assert saved is not None, "summary must be persisted in DB"
    assert saved["summary_short"] == result["summary_short"]
    assert saved["topics"] == result["topics"]
    assert saved["model_used"] == backend.model_name

    # Event store should have 2 new events (SummaryUpdate + TopicExtraction).
    events_after = event_store.count_events(session_id)
    assert events_after == events_before + 2, (
        f"Expected 2 new events in store, got {events_after - events_before}"
    )

    # Verify the appended events are the right types.
    all_events = event_store.iter_events(session_id)
    last_two = all_events[-2:]
    types = {ev.event_type for ev in last_two}
    assert EventType.SUMMARY_UPDATE in types
    assert EventType.TOPIC_EXTRACTION in types


@pytest.mark.asyncio
async def test_summarize_session_unsummarized(event_store: EventStore, db: ConversationsDB) -> None:
    """Summarize all unsummarized conversations in a session via LM Studio."""
    all_convs = await db.get_all_conversations(limit=100)
    assert all_convs, "No conversations in DB."

    # Find a session that has at least one unsummarized conversation.
    from collections import defaultdict
    by_session: dict[str, list[dict]] = defaultdict(list)
    for c in all_convs:
        by_session[c["session_id"]].append(c)

    target_session: str | None = None
    for sid, convs in by_session.items():
        unsummarized = await db.get_unsummarized_conversations(sid)
        if unsummarized:
            target_session = sid
            break

    if target_session is None:
        pytest.skip("All conversations already have summaries — nothing to process.")

    unsummarized_before = await db.get_unsummarized_conversations(target_session)
    unsummarized_count = len(unsummarized_before)
    print(f"\nSession: {target_session}  ({unsummarized_count} unsummarized)")

    backend = OpenAICompatBackend(base_url=LMSTUDIO_BASE_URL)
    events_before = event_store.count_events(target_session)

    # Import the function directly so we don't need the API server.
    from src.replay.summarizer import summarize_conversation as _summarize

    processed = 0
    failed: list[str] = []
    for conv in unsummarized_before:
        try:
            result = await _summarize(conv, event_store, db, backend)
            print(f"  [{conv['conversation_id'][:8]}] {result['summary_short'][:80]}")
            processed += 1
        except Exception as exc:
            print(f"  [{conv['conversation_id'][:8]}] FAILED: {exc}")
            failed.append(conv["conversation_id"])

    print(f"\nProcessed: {processed}, Failed: {len(failed)}")

    assert processed > 0, "At least one conversation should have been summarized."
    assert not failed, f"Some conversations failed: {failed}"

    # All previously unsummarized conversations should now have summaries.
    unsummarized_after = await db.get_unsummarized_conversations(target_session)
    assert len(unsummarized_after) == 0, (
        f"{len(unsummarized_after)} conversations still missing summaries after run."
    )

    # Each conversation produced 2 new events.
    events_after = event_store.count_events(target_session)
    assert events_after == events_before + processed * 2, (
        f"Expected {processed * 2} new events, got {events_after - events_before}"
    )


@pytest.mark.asyncio
async def test_summarize_session_partial(event_store: EventStore, db: ConversationsDB) -> None:
    """Verify session summarization skips already-summarized conversations correctly."""
    all_convs = await db.get_all_conversations(limit=100)
    assert all_convs, "No conversations in DB."

    from collections import defaultdict
    by_session: dict[str, list[dict]] = defaultdict(list)
    for c in all_convs:
        by_session[c["session_id"]].append(c)

    # Find a session that has both summarized and unsummarized conversations.
    target_session: str | None = None
    summarized_count = 0
    unsummarized_count = 0
    for sid, convs in by_session.items():
        unsummarized = await db.get_unsummarized_conversations(sid)
        total = len(convs)
        u = len(unsummarized)
        s = total - u
        if s > 0 and u > 0:
            target_session = sid
            summarized_count = s
            unsummarized_count = u
            break

    if target_session is None:
        pytest.skip(
            "No session with both summarized and unsummarized conversations — "
            "run test_summarize_session_unsummarized first on a partial session."
        )

    print(
        f"\nSession: {target_session}  "
        f"({summarized_count} summarized, {unsummarized_count} unsummarized)"
    )

    backend = OpenAICompatBackend(base_url=LMSTUDIO_BASE_URL)
    unsummarized_before = await db.get_unsummarized_conversations(target_session)

    from src.replay.summarizer import summarize_conversation as _summarize

    for conv in unsummarized_before:
        result = await _summarize(conv, event_store, db, backend)
        print(f"  [{conv['conversation_id'][:8]}] {result['summary_short'][:80]}")

    # After processing, the session should have zero unsummarized conversations.
    unsummarized_after = await db.get_unsummarized_conversations(target_session)
    assert len(unsummarized_after) == 0, (
        f"Still {len(unsummarized_after)} unsummarized after partial run."
    )

    # Previously summarized conversations must remain unchanged.
    all_after = await db.get_latest_conversations(target_session, limit=100)
    for conv in all_after:
        saved = await db.get_summary(conv["conversation_id"])
        assert saved is not None, (
            f"Conversation {conv['conversation_id']} lost its summary."
        )
