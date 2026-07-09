"""Generic multi-key round-robin pool, shared by every free-tier provider
that needs to scale past a single account's quota (Prospeo, and now
QuickEmailVerification).

Owns the key-rotation state machine only: round-robins across configured
keys, parks any key hit by a rate-limit / quota-exhausted signal for a
cooldown (in case the limit resets rather than being permanent), and
permanently disables keys that report an invalid/revoked key. Quota
accounting is reactive -- callers react to each provider's own error
signals; this module never polls an account-info endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEFAULT_EXHAUSTED_COOLDOWN = timedelta(hours=1)


@dataclass
class _KeyState:
    api_key: str
    exhausted_until: datetime | None = None
    permanently_dead: bool = False


class KeyPool:
    """Async round-robin pool of API keys for one provider."""

    def __init__(
        self,
        api_keys: list[str],
        *,
        default_cooldown: timedelta = DEFAULT_EXHAUSTED_COOLDOWN,
    ) -> None:
        clean = [k.strip() for k in api_keys if k and k.strip()]
        self._keys = [_KeyState(api_key=k) for k in clean]
        self._cursor = 0
        self._lock = asyncio.Lock()
        self._default_cooldown = default_cooldown

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

    async def mark_exhausted(
        self, key: str, cooldown: timedelta | None = None,
    ) -> None:
        """Park ``key`` until ``cooldown`` elapses (default: the pool's
        configured cooldown). Pass an explicit ``cooldown`` for a provider
        whose quota resets on its own schedule (e.g. daily) rather than a
        generic per-minute rate limit.
        """
        async with self._lock:
            for state in self._keys:
                if state.api_key == key:
                    state.exhausted_until = datetime.utcnow() + (
                        cooldown if cooldown is not None
                        else self._default_cooldown
                    )
                    break

    async def mark_dead(self, key: str) -> None:
        async with self._lock:
            for state in self._keys:
                if state.api_key == key:
                    state.permanently_dead = True
                    logger.error(
                        "KeyPool: key %s permanently disabled", redact(key),
                    )
                    break


def redact(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-2:]


def seconds_until_next_utc_midnight() -> timedelta:
    """Time remaining until 00:00 UTC tomorrow -- the reset point for a
    provider whose free tier grants credits per calendar day.
    """
    now = datetime.utcnow()
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return tomorrow - now
