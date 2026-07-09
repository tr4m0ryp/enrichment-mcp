"""Chains multiple email-verifier tiers behind one interface.

Tries each configured verifier in order (QuickEmailVerification's key pool
first, MyEmailVerifier second) and takes the first one that can actually
answer. A tier is "unavailable" -- not a verdict -- when it returns ``None``
(its own pool exhausted/dead) or raises ``MyEmailVerifierAPIError`` (a
provider-side error envelope); the chain moves to the next tier rather than
ever fabricating a result. Only when every tier is unavailable does the
chain raise, so a single provider outage degrades capacity instead of
silently reporting a false "invalid".
"""

from __future__ import annotations

import logging
from typing import Protocol

from .verifier import MyEmailVerifierAPIError, VerifyResult

logger = logging.getLogger(__name__)


class _Verifier(Protocol):
    @property
    def enabled(self) -> bool: ...
    async def verify(self, email: str) -> VerifyResult | None: ...


class NoVerifierAvailableError(Exception):
    """Every configured verifier tier is unavailable right now (all pools
    exhausted/dead, or erroring) -- not a verdict on the email itself.
    """


class ChainedEmailVerifier:
    """Composes an ordered list of verifier tiers behind one ``.verify()``."""

    def __init__(self, verifiers: list[_Verifier]) -> None:
        self._verifiers = list(verifiers)

    @property
    def enabled(self) -> bool:
        return any(v.enabled for v in self._verifiers)

    async def verify(self, email: str) -> VerifyResult:
        last_exc: Exception | None = None
        for v in self._verifiers:
            if not v.enabled:
                continue
            try:
                result = await v.verify(email)
            except MyEmailVerifierAPIError as exc:
                logger.warning(
                    "ChainedEmailVerifier: tier %s unavailable for %s: %s",
                    type(v).__name__, email, exc,
                )
                last_exc = exc
                continue
            if result is None:
                continue
            return result

        if last_exc is not None:
            raise NoVerifierAvailableError(
                f"every configured email verifier is unavailable: {last_exc}"
            ) from last_exc
        raise NoVerifierAvailableError(
            "every configured email verifier is unavailable"
        )
