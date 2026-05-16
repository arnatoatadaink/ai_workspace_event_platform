#!/usr/bin/env python3
"""UserPromptSubmit hook: inject recent AWEP conversation context into the user turn.

Called by Claude Code on every UserPromptSubmit event.  Reads the hook JSON
from stdin to extract session_id, then fetches the N most recent summarised
conversations from the AWEP API and prints them to stdout.  Claude Code
prepends this output to the user's prompt.

Environment variables
---------------------
AWEP_API_URL    AWEP base URL (default: http://localhost:8001)
AWEP_CONTEXT_N  Number of recent conversations to inject (default: 5, max: 20)

Direct test (no Claude Code required)
--------------------------------------
    echo '{}' | python3 scripts/context_hook.py
    echo '{"session_id":"<id>"}' | python3 scripts/context_hook.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_URL = os.environ.get("AWEP_API_URL", "http://localhost:8001")
N = min(int(os.environ.get("AWEP_CONTEXT_N", "5")), 20)


def _read_hook_input() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _fetch_context(session_id: str) -> dict:
    params: dict[str, str] = {"n": str(N)}
    if session_id:
        params["session_id"] = session_id
    url = f"{API_URL}/context/recent?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"count": 0, "conversations": []}


def main() -> None:
    hook_input = _read_hook_input()
    session_id: str = hook_input.get("session_id", "")

    data = _fetch_context(session_id)
    if not data.get("count"):
        sys.exit(0)

    print("## 過去の会話コンテキスト（AWEP）")
    for c in reversed(data["conversations"]):
        date = c["created_at"][:10]
        summary = c["summary_short"]
        topics_str = ", ".join(c["topics"]) if c["topics"] else "—"
        print(f"- [{date}] {summary} (topics: {topics_str})")


if __name__ == "__main__":
    main()
