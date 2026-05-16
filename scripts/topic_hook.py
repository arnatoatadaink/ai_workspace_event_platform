#!/usr/bin/env python3
"""UserPromptSubmit hook: inject related past conversations based on current prompt.

Extracts keywords from the user's prompt and searches AWEP for semantically
related past conversations, injecting them as context.

Current: keyword extraction + FTS5 full-text search (/search/conversations)
Planned: FAISS semantic k-NN via MED integration (see STEP 5-3 / 5-5 in TODO.md)

Environment variables
---------------------
AWEP_API_URL    AWEP base URL (default: http://localhost:8001)
AWEP_TOPIC_N    Number of related conversations to inject (default: 3, max: 10)

Direct test
-----------
    echo '{"prompt": "FastAPIのルーター設計について"}' | python3 scripts/topic_hook.py
    echo '{"prompt": "FAISS index optimization"}' | python3 scripts/topic_hook.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

API_URL = os.environ.get("AWEP_API_URL", "http://localhost:8001")
N = min(int(os.environ.get("AWEP_TOPIC_N", "3")), 10)

# FTS5 trigram tokenizer requires >= 3 chars; shorter queries return nothing
_FTS_MIN_LEN = 3


def _read_hook_input() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _extract_prompt(hook_input: dict) -> str:
    """Extract prompt text; accept 'prompt' (Claude Code) or 'user_prompt' as fallback."""
    return hook_input.get("prompt") or hook_input.get("user_prompt") or ""


def _build_fts_query(prompt: str) -> str:
    """Extract alphanumeric + CJK runs from prompt for a safe FTS5 query.

    FTS5 treats "", *, :, (, ), AND, OR, NOT, NEAR as operators.
    By keeping only word chars and CJK codepoints we avoid syntax errors.
    Keeps first 60 chars after extraction to bound query length.
    """
    # Keep ASCII word chars and CJK ideographs / Hiragana / Katakana; drop punctuation
    tokens = re.findall(r"[\w一-鿿぀-ゟ゠-ヿ]+", prompt)
    query = " ".join(tokens)[:60].strip()
    return query


def _fetch_related(query: str) -> list:
    if len(query) < _FTS_MIN_LEN:
        return []
    params = urllib.parse.urlencode({"q": query, "limit": str(N)})
    url = f"{API_URL}/search/conversations?{params}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("results", [])
    except Exception:
        return []


def main() -> None:
    hook_input = _read_hook_input()
    prompt = _extract_prompt(hook_input)
    query = _build_fts_query(prompt)
    results = _fetch_related(query)

    if not results:
        sys.exit(0)

    print("## 関連する過去の会話（AWEP）")
    for r in results:
        date = r["created_at"][:10]
        summary = r["summary_short"]
        topics_str = ", ".join(r["topics"]) if r["topics"] else "—"
        print(f"- [{date}] {summary} (topics: {topics_str})")


if __name__ == "__main__":
    main()
