"""AdapterPlugin interface.

Each source (Claude CLI, WebChat, Discord, ...) implements this interface.
Adapters are loaded at FastAPI startup (low-isolation: same Python process).

Contract:
  - parse() converts raw hook/webhook payload to InternalEvent list
  - parse() MUST NOT raise; catch internally, log, return []
  - source_name must match an EventSource enum value
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.schemas.internal_event_v1 import InternalEvent


class AdapterPlugin(ABC):
    """Base class for all source adapters."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Must match an EventSource enum value (e.g. 'claude_cli')."""
        ...

    @property
    def version(self) -> str:
        """Semantic version string for this adapter."""
        return "0.1.0"

    @property
    def description(self) -> str:
        """Human-readable description of this adapter."""
        return ""

    @abstractmethod
    def parse(self, raw_payload: dict) -> list[InternalEvent]:
        """Convert raw source payload to InternalEvent list.

        Never raises. On parse error: log and return [].
        """
        ...
