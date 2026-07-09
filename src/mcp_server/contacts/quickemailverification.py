"""QuickEmailVerification client with a multi-key pool -- the primary tier
of the email-verification chain, ahead of MyEmailVerifier.

QuickEmailVerification's free tier grants 100 verifications/day per account
(no card required), reset daily rather than monthly, so a key hitting its
daily cap is parked until the next UTC midnight rather than the shorter
generic cooldown used for a plain rate limit. Multiple free-tier keys pool
the same way Prospeo's do (``key_pool.KeyPool``), scaling capacity linearly
with the number of keys configured.

Endpoint: ``GET /v1/verify?apikey=...&email=...``
Auth: query param ``apikey``.
Error signals (HTTP status): 401 invalid key (permanent), 402 out of
credits (daily reset), 429 rate limited (short cooldown).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp

from .key_pool import KeyPool, redact, seconds_until_next_utc_midnight
from .verifier import VerifyResult, _truthy

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.quickemailverification.com/v1/verify"
HTTP_TIMEOUT_SECONDS = 30.0
_RATE_LIMIT_COOLDOWN = timedelta(minutes=2)


class QuickEmailVerificationClient:
    """Async multi-key QuickEmailVerification client.

    Mirrors :class:`ProspeoFinder`'s pool-rotation shape: round-robins
    across keys, returns ``None`` (never raises) when every key is
    exhausted/dead/erroring so the caller can fall through to the next
    verifier tier.
    """

    def __init__(self, api_keys: list[str]) -> None:
        self._pool = KeyPool(api_keys)
        if not len(self._pool):
            logger.info(
                "QuickEmailVerificationClient: no API keys configured -- "
                "disabled",
            )
        else:
            logger.info(
                "QuickEmailVerificationClient: %d keys configured",
                len(self._pool),
            )

    @property
    def enabled(self) -> bool:
        return self._pool.enabled

    async def verify(self, email: str) -> VerifyResult | None:
        """Verify one email; returns ``None`` when the whole pool is
        unavailable right now (every key dead or in cooldown) so a chained
        fallback verifier can take over -- never a fabricated verdict.
        """
        if not email or "@" not in email:
            return VerifyResult(
                email=email or "", valid=False,
                method="quickemailverification", confidence="high",
            )
        if not self.enabled:
            return None

        for _ in range(len(self._pool)):
            state = await self._pool.pick()
            if state is None:
                logger.warning(
                    "QuickEmailVerificationClient: all keys exhausted/dead "
                    "for %s",
                    email,
                )
                return None
            try:
                status, body = await self._call(state.api_key, email)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "QuickEmailVerificationClient: transport error on key "
                    "%s for %s: %s",
                    redact(state.api_key), email, exc,
                )
                continue

            if status == 401:
                await self._pool.mark_dead(state.api_key)
                continue
            if status == 402:
                logger.info(
                    "QuickEmailVerificationClient: key %s out of daily "
                    "credits; rotating",
                    redact(state.api_key),
                )
                await self._pool.mark_exhausted(
                    state.api_key,
                    cooldown=seconds_until_next_utc_midnight(),
                )
                continue
            if status == 429:
                await self._pool.mark_exhausted(
                    state.api_key, cooldown=_RATE_LIMIT_COOLDOWN,
                )
                continue
            if (
                status == 200
                and isinstance(body, dict)
                and _truthy(body.get("success", "true"))
            ):
                return _parse_response(email, body)

            logger.warning(
                "QuickEmailVerificationClient: unexpected HTTP %s for %s: "
                "%.200s",
                status, email, str(body),
            )
            continue

        return None

    async def _call(self, api_key: str, email: str) -> tuple[int, dict]:
        params = {"apikey": api_key, "email": email}
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ENDPOINT, params=params) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = {"_raw_text": (await resp.text())[:200]}
                return resp.status, (body if isinstance(body, dict) else {})


def _parse_response(email: str, body: dict) -> VerifyResult:
    """Map QuickEmailVerification's response into the shared VerifyResult
    shape used across every verifier tier.
    """
    # QuickEmailVerification returns booleans as the STRINGS "true"/"false",
    # so a plain bool() would read "false" as truthy -- use the shared
    # string-aware truthiness check (same convention as MyEmailVerifier).
    result = (body.get("result") or "").strip().lower()
    accept_all = _truthy(body.get("accept_all"))
    disposable = _truthy(body.get("disposable"))
    role = _truthy(body.get("role"))

    if result == "valid":
        if accept_all:
            return VerifyResult(
                email=email, valid=True,
                method="catch_all", confidence="medium",
            )
        if disposable:
            return VerifyResult(
                email=email, valid=False,
                method="quickemailverification", confidence="high",
            )
        return VerifyResult(
            email=email, valid=True,
            method="quickemailverification",
            confidence="medium" if role else "high",
        )

    # "invalid" or "unknown".
    logger.info(
        "QuickEmailVerification: %s -> %s (%s)",
        email, result or "no-result", (body.get("reason") or "")[:80],
    )
    return VerifyResult(
        email=email, valid=False,
        method="quickemailverification",
        confidence="high" if result == "invalid" else "low",
    )
