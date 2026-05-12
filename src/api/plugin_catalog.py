"""Static plugin catalog.

Lists all known adapters (installed, available, and coming-soon).
Runtime status is enriched by main.py using app.state.adapters.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PluginStatus = Literal["active", "available", "coming_soon", "update_available"]


class PluginEntry(BaseModel):
    """Catalog entry for one adapter plugin."""

    name: str
    source_name: str
    description: str
    status: PluginStatus
    installed_version: str | None
    latest_version: str
    install_command: str | None = None


# Canonical catalog.  Status is overridden at runtime for installed adapters.
CATALOG: list[PluginEntry] = [
    PluginEntry(
        name="claude-adapter",
        source_name="claude_cli",
        description="Claude CLI (Claude Code) hook events — Stop / PreToolUse / PostToolUse",
        status="active",
        installed_version="0.1.0",
        latest_version="0.1.0",
    ),
    PluginEntry(
        name="webchat-adapter",
        source_name="webchat",
        description="Web Chat adapter for browser-based AI chat sessions",
        status="coming_soon",
        installed_version=None,
        latest_version="0.1.0",
        install_command="poetry add ai-workspace-webchat-adapter",
    ),
    PluginEntry(
        name="discord-adapter",
        source_name="discord",
        description="Discord Bot adapter for Discord AI interactions",
        status="coming_soon",
        installed_version=None,
        latest_version="0.1.0",
        install_command="poetry add ai-workspace-discord-adapter",
    ),
    PluginEntry(
        name="gemini-adapter",
        source_name="gemini_cli",
        description="Gemini CLI adapter for Google Gemini interactions",
        status="coming_soon",
        installed_version=None,
        latest_version="0.1.0",
        install_command="poetry add ai-workspace-gemini-adapter",
    ),
]


def build_live_catalog(active_source_names: set[str]) -> list[PluginEntry]:
    """Return catalog with status updated from live adapter registry."""
    result = []
    for entry in CATALOG:
        if entry.source_name in active_source_names:
            result.append(entry.model_copy(update={"status": "active"}))
        else:
            result.append(entry)
    return result
