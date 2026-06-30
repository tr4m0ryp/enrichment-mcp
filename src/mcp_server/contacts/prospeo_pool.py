"""Multi-key round-robin pool for the Prospeo enrich-person finder.

Split out of ``prospeo.py`` to keep both files under the 300-line cap. Owns
the key-rotation state machine only: round-robins across configured keys,
parks any key hit by 429 / INSUFFICIENT_CREDITS for an hour before retrying
it (in case the limit was per-minute rather than monthly), and permanently
disables keys that report INVALID_API_KEY. Quota accounting is reactive --
we never poll Prospeo's account-info endpoint, we react to error codes.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

EXHAUSTED_COOLDOWN = timedelta(hours=1)


@dataclass
class _KeyState:
    api_key: str
    exhausted_until: datetime | None = None
    permanently_dead: bool = False


class KeyPool:
    """Async round-robin pool of Prospeo API keys."""

    def __init__(self, api_keys: list[str]) -> None:
        clean = [k.strip() for k in api_keys if k and k.strip()]
        self._keys = [_KeyState(api_key=k) for k in clean]
        self._cursor = 0
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def enabled(self) -> bool:
        return any(not s.permanently_dead for s in self._keys)

    async def pick(self) -> _KeyState | None:
        """Return the next available key in round-robin order, or None
        when every key is either dead or in cooldown.
        """
        async with self._lock:
            now = datetime.utcnow()
            n = len(self._keys)
            if n == 0:
                return None
            for _ in range(n):
                state = self._keys[self._cursor]
                self._cursor = (self._cursor + 1) % n
                if state.permanently_dead:
                    continue
                if state.exhausted_until and state.exhausted_until > now:
                    continue
                state.exhausted_until = None
                return state
            return None

    async def mark_exhausted(self, key: str) -> None:
        async with self._lock:
            for state in self._keys:
                if state.api_key == key:
                    state.exhausted_until = (
                        datetime.utcnow() + EXHAUSTED_COOLDOWN
                    )
                    break

    async def mark_dead(self, key: str) -> None:
        async with self._lock:
            for state in self._keys:
                if state.api_key == key:
                    state.permanently_dead = True
                    logger.error(
                        "ProspeoFinder: key %s permanently disabled",
                        redact(key),
                    )
                    break


def redact(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-2:]
