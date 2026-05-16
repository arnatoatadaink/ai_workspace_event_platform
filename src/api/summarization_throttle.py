"""Global serialization throttle for summarization calls.

All summarization requests (single-conversation and session-batch) share a
single asyncio.Lock so they never run concurrently.  After each call completes
the lock is held for an additional cooldown period before being released, giving
the local LLM server time to recover.

Cooldown formula::

    wait = fixed_interval_seconds + last_elapsed_seconds * proportional_factor

Settings are reloaded from disk on every call so changes take effect immediately
without a server restart.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Optional, TypeVar

from src.api.settings_store import load_interval_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SummarizationThrottle:
    """Serialize all summarization calls and apply a post-call cooldown."""

    def __init__(self) -> None:
        self._lock: asyncio.Lock = asyncio.Lock()
        self._last_elapsed: float = 0.0

    async def run(self, coro: Awaitable[T]) -> T:
        """Run *coro* under the global lock with post-completion cooldown.

        The lock is held throughout the cooldown so the next caller cannot
        start until both the LLM call and the sleep have finished.
        """
        await self._lock.acquire()
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        error: Optional[BaseException] = None
        result: Optional[T] = None
        try:
            result = await coro
        except Exception as exc:
            error = exc
        finally:
            elapsed = loop.time() - t0
            self._last_elapsed = elapsed
            settings = load_interval_settings()
            wait = settings.fixed_interval_seconds + elapsed * settings.proportional_factor
            if wait > 0:
                logger.debug(
                    "Summarization throttle: cooldown %.2fs (elapsed=%.2fs, fixed=%.2fs, factor=%.2f)",
                    wait,
                    elapsed,
                    settings.fixed_interval_seconds,
                    settings.proportional_factor,
                )
                await asyncio.sleep(wait)
            self._lock.release()

        if error is not None:
            raise error
        return result  # type: ignore[return-value]

    @property
    def last_elapsed_seconds(self) -> float:
        """Wall-clock seconds of the most recently completed summarization call."""
        return self._last_elapsed
