"""Apollo.io ``people/match`` client -- the failover tier behind Prospeo.

Same shape as ``ProspeoFinder`` (``.enabled`` + ``.find()``) so the two are
interchangeable inside ``ChainedFinder``, but the provider differs in four
ways that matter:

  - **Auth** is the ``x-api-key`` header, not Prospeo's ``X-KEY``.
  - **A miss is HTTP 200 with a null person**, not an error envelope. Apollo
    reserves error codes for account-level problems.
  - **Plan gating is per-endpoint.** A key on a plan that excludes
    ``people/match`` returns 403 ``API_INACCESSIBLE`` on every call, forever.
    That is treated as a permanently dead key, so an unusable Apollo key
    costs exactly one probe for the process lifetime and is skipped after --
    resolution degrades to Prospeo-only rather than paying a wasted
    round-trip per lead.
  - **Mobile reveal is asynchronous**: ``reveal_phone_number`` requires a
    webhook and delivers out-of-band, which does not fit a request-scoped
    resolve. ``enrich_mobile`` is therefore accepted and ignored; any phone
    Apollo volunteers in the synchronous body is still kept for free.

Cost model: 1 credit when demographics/email come back, up to 9 when a mobile
is included, 0 when Apollo finds no credit-consuming data.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
import asyncpg

from ..finder import EnrichmentResult, ProviderUnavailableError, log_usage
from ..key_pool import KeyPool, redact
from .parse import PROVIDER, extract_person

logger = logging.getLogger(__name__)

APOLLO_MATCH_URL = "https://api.apollo.io/api/v1/people/match"
TIMEOUT_SECONDS = 30.0

_CREDITS_EMAIL_ONLY = 1
_CREDITS_WITH_MOBILE = 9

# Apollo's tightest limit is per-minute, so a 429 parks a key briefly rather
# than for the pool's default hour -- the quota usually returns long before.
_RATE_LIMIT_COOLDOWN = timedelta(minutes=5)

# Sentinel meaning "this key is retired, move to the next one". Distinct from
# None, which is a real answer (no such person).
_RETRY = object()


class ApolloFinder:
    """Async multi-key Apollo ``people/match`` client."""

    def __init__(
        self,
        api_keys: list[str],
        usage_pool: asyncpg.Pool | None = None,
    ):
        self._pool = KeyPool(api_keys)
        self._usage_pool = usage_pool
        if not len(self._pool):
            logger.info("ApolloFinder: no API keys configured -- disabled")
        else:
            logger.info(
                "ApolloFinder: %d keys configured (usage_logging=%s)",
                len(self._pool),
                "on" if usage_pool is not None else "off",
            )

    @property
    def enabled(self) -> bool:
        return self._pool.enabled

    async def find(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        *,
        enrich_mobile: bool = False,
    ) -> EnrichmentResult | None:
        """Enrich one (first, last, domain) triple.

        Returns ``None`` on a definitive miss (Apollo has no such person, or
        the inputs were unusable). Raises ``ProviderUnavailableError`` when no
        key could serve the call -- exhausted quota, dead keys, a plan that
        excludes the endpoint, or transport failure on every key -- so the
        chain falls through to another provider instead of recording a false
        "no such person".
        """
        if not first_name or not domain:
            return None
        if not self.enabled:
            raise ProviderUnavailableError("apollo: no usable API keys")

        body = {
            "first_name": first_name,
            "last_name": last_name or "",
            "domain": domain,
            # Work email is what the pipeline needs; personal-email reveal is
            # a separate credit tier and off by default. Phone reveal is
            # webhook-only (see module docstring) and never requested here.
            "reveal_personal_emails": False,
            "reveal_phone_number": False,
        }

        for _ in range(len(self._pool)):
            state = await self._pool.pick()
            if state is None:
                raise ProviderUnavailableError(
                    "apollo: all keys exhausted or dead"
                )
            try:
                status, resp = await self._call_one(state.api_key, body)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "ApolloFinder: HTTP error on key %s for %s %s @ %s: %s",
                    redact(state.api_key), first_name, last_name, domain, exc,
                )
                continue

            outcome = await self._handle(
                state.api_key, status, resp, first_name, last_name, domain,
            )
            if outcome is not _RETRY:
                return outcome

        raise ProviderUnavailableError(
            "apollo: every key failed for this request"
        )

    async def _handle(
        self,
        api_key: str,
        status: int,
        resp: dict | None,
        first_name: str,
        last_name: str,
        domain: str,
    ) -> EnrichmentResult | None | object:
        """Map one HTTP response to a hit, a definitive miss, or ``_RETRY``.

        ``_RETRY`` means the key was retired (killed or parked) and the caller
        should try the next one.
        """
        error_code = resp.get("error_code") if isinstance(resp, dict) else None

        if status == 200 and isinstance(resp, dict):
            return await self._handle_ok(
                api_key, resp, first_name, last_name, domain,
            )

        # 401 = bad/revoked key. 403 API_INACCESSIBLE = the account's plan does
        # not include this endpoint. Both are permanent for this key -- retiring
        # it means later resolutions skip Apollo entirely instead of burning a
        # round-trip each time.
        if status == 401 or error_code in ("INVALID_API_KEY", "API_INACCESSIBLE"):
            logger.error(
                "ApolloFinder: key %s permanently unusable (status=%s code=%s) "
                "-- disabling. %.200s",
                redact(api_key), status, error_code, str(resp),
            )
            await self._pool.mark_dead(api_key)
            return _RETRY

        if status == 403:
            # A 403 without API_INACCESSIBLE is an entitlement/credit refusal
            # rather than a plan gate; park the key instead of killing it.
            logger.warning(
                "ApolloFinder: key %s refused (403 code=%s); parking. %.200s",
                redact(api_key), error_code, str(resp),
            )
            await self._pool.mark_exhausted(api_key)
            return _RETRY

        if status == 429:
            logger.info(
                "ApolloFinder: key %s rate-limited; parking %s",
                redact(api_key), _RATE_LIMIT_COOLDOWN,
            )
            await self._pool.mark_exhausted(
                api_key, cooldown=_RATE_LIMIT_COOLDOWN,
            )
            return _RETRY

        if status == 402 or error_code == "INSUFFICIENT_CREDITS":
            logger.info(
                "ApolloFinder: key %s out of credits; parking", redact(api_key),
            )
            await self._pool.mark_exhausted(api_key)
            return _RETRY

        if status == 422:
            # Unprocessable input for this specific contact -- not a key
            # problem, and not retryable on another key.
            logger.info(
                "ApolloFinder: 422 for %s %s @ %s (definitive miss)",
                first_name, last_name, domain,
            )
            await log_usage(self._usage_pool, PROVIDER, api_key, 0, domain)
            return None

        logger.warning(
            "ApolloFinder: unexpected error %s/%s for %s %s @ %s; body=%.200s",
            status, error_code, first_name, last_name, domain, str(resp),
        )
        # 5xx and anything else unclassified is a provider-side failure, so try
        # the next key rather than declaring the person nonexistent.
        return _RETRY

    async def _handle_ok(
        self,
        api_key: str,
        resp: dict,
        first_name: str,
        last_name: str,
        domain: str,
    ) -> EnrichmentResult | None:
        """Handle a 200: either a usable person, or a billed-at-zero miss."""
        person = resp.get("person")
        if not person:
            # Apollo signals "no such person" as a 200 with a null person, and
            # bills nothing for it.
            logger.info(
                "ApolloFinder: no match for %s %s @ %s",
                first_name, last_name, domain,
            )
            await log_usage(self._usage_pool, PROVIDER, api_key, 0, domain)
            return None

        result = extract_person(person)
        if not (result.email or result.linkedin_url):
            await log_usage(self._usage_pool, PROVIDER, api_key, 0, domain)
            return None

        credits = (
            _CREDITS_WITH_MOBILE if result.phone
            else (_CREDITS_EMAIL_ONLY if result.email else 0)
        )
        logger.info(
            "ApolloFinder: hit on key %s for %s %s @ %s "
            "(email=%s linkedin=%s phone=%s credits=%d)",
            redact(api_key), first_name, last_name, domain,
            bool(result.email), bool(result.linkedin_url),
            bool(result.phone), credits,
        )
        await log_usage(self._usage_pool, PROVIDER, api_key, credits, domain)
        return result

    async def _call_one(
        self, api_key: str, body: dict,
    ) -> tuple[int, dict | None]:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "accept": "application/json",
        }
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(
                APOLLO_MATCH_URL, headers=headers, json=body,
            ) as r:
                try:
                    parsed = await r.json()
                except Exception:
                    parsed = None
                return r.status, parsed


__all__ = ["ApolloFinder", "APOLLO_MATCH_URL"]
