"""Persistent settings store backed by runtime/settings.json.

Stores summarizer backend configuration.  The file is created on first write
and given mode 0600 so the API key is not world-readable.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

_SETTINGS_PATH = Path("runtime/settings.json")

BackendKind = Literal["openai_compat", "claude"]


class SummarizerSettings(BaseModel):
    """Persisted configuration for the summarizer LLM backend."""

    backend: BackendKind = "openai_compat"
    base_url: str = "http://192.168.2.104:52624/v1"
    api_key: str = "lm"
    model: str = "gemma-4-31b-it@q6_k"


def load_summarizer_settings() -> SummarizerSettings:
    """Load summarizer settings from disk.  Returns defaults when file absent."""
    if not _SETTINGS_PATH.exists():
        return SummarizerSettings()
    try:
        raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return SummarizerSettings.model_validate(raw.get("summarizer", {}))
    except Exception:
        return SummarizerSettings()


def save_summarizer_settings(settings: SummarizerSettings) -> None:
    """Persist summarizer settings to disk with mode 0600."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if _SETTINGS_PATH.exists():
        try:
            existing = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing["summarizer"] = settings.model_dump()
    text = json.dumps(existing, ensure_ascii=False, indent=2)
    _SETTINGS_PATH.write_text(text, encoding="utf-8")
    os.chmod(_SETTINGS_PATH, stat.S_IRUSR | stat.S_IWUSR)


def mask_api_key(key: str) -> str:
    """Return a masked representation for display.  Never returns the real key."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def build_backend(settings: SummarizerSettings) -> object:
    """Construct a SummarizerBackend from settings.  Raises on import error."""
    from src.replay.summarizer import ClaudeBackend, OpenAICompatBackend

    if settings.backend == "claude":
        api_key: Optional[str] = settings.api_key if settings.api_key else None
        return ClaudeBackend(model=settings.model, api_key=api_key)
    return OpenAICompatBackend(
        base_url=settings.base_url,
        api_key=settings.api_key or "lm",
        model=settings.model,
    )
