"""Apollo.io person enrichment -- the failover tier behind Prospeo.

Same shape as ``ProspeoFinder`` (``.enabled`` + ``.find()``) so the two are
interchangeable inside ``ChainedFinder``, but the provider differs in four
ways that matter:

  - **Auth** is the ``x-api-key`` header, not Prospeo's ``X-KEY``.
  - **A miss is HTTP 200 with a null person**, not an error envelope. Apollo
    only uses error codes for account-level problems.
  - **Plan gating is per-endpoint.** A key on a plan that excludes
    ``people/match`` returns 403 ``API_INACCESSIBLE`` on every call, forever.
    That is treated as a permanently dead key, so an unusable Apollo key
    costs exactly one probe and is then skipped -- resolution degrades to
    Prospeo-only rather than paying a wasted round-trip per lead.
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

from .finder import EnrichmentResult, ProviderUnavailableError, log_usage
from .key_pool import KeyPool, redact

logger = logging.getLogger(__name__)

APOLLO_MATCH_URL = "https://api.apollo.io/api/v1/people/match"
TIMEOUT_SECONDS = 30.0
PROVIDER = "apollo"

_CREDITS_EMAIL_ONLY = 1
_CREDITS_WITH_MOBILE = 9

# Apollo's tightest limit is per-minute, so a 429 parks a key briefly rather
# than for the pool's default hour -- the quota usually returns long before.
_RATE_LIMIT_COOLDOWN = timedelta(minutes=5)

# Apollo substitutes this sentinel local-part when the account lacks the
# credits or plan to reveal the real address. It is not a deliverable mailbox
# and must never reach the lead store.
_LOCKED_EMAIL_MARKER = "email_not_unlocked"

# email_status values that mean "this address is known bad or absent".
_DEAD_EMAIL_STATUSES = {"unavailable", "bounced", "invalid"}


class ApolloFinder:
    """Async multi-key Apollo people/match client."""

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
                state.api_key, status, resp,
                first_name, last_name, domain,
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

        Returning ``_RETRY`` means the key was retired (dead or parked) and
        the caller should try the next one.
        """
        error_code = (
            resp.get("error_code") if isinstance(resp, dict) else None
        )

        if status == 200 and isinstance(resp, dict):
            person = resp.get("person")
            if not person:
                # Apollo signals "no such person" as a 200 with a null
                # person, and bills nothing for it.
                logger.info(
                    "ApolloFinder: no match for %s %s @ %s",
                    first_name, last_name, domain,
                )
                await log_usage(
                    self._usage_pool, PROVIDER, api_key, 0, domain,
                )
                return None

            result = self._extract(person)
            if not (result.email or result.linkedin_url):
                await log_usage(
                    self._usage_pool, PROVIDER, api_key, 0, domain,
                )
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
            await log_usage(
                self._usage_pool, PROVIDER, api_key, credits, domain,
            )
            return result

        # 401 = bad/revoked key. 403 API_INACCESSIBLE = the account's plan
        # does not include this endpoint. Both are permanent for this key --
        # retiring it means later resolutions skip Apollo entirely instead of
        # burning a round-trip each time.
        if status == 401 or error_code in ("INVALID_API_KEY", "API_INACCESSIBLE"):
            logger.error(
                "ApolloFinder: key %s permanently unusable "
                "(status=%s code=%s) -- disabling. %.200s",
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
                "ApolloFinder: key %s out of credits; parking",
                redact(api_key),
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
        # 5xx and anything else unclassified is a provider-side failure, so
        # try the next key rather than declaring the person nonexistent.
        return _RETRY

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

    @staticmethod
    def _extract(person: dict) -> EnrichmentResult:
        email_status = (person.get("email_status") or "").strip().lower()
        email = (person.get("email") or "").strip().lower()
        # Drop the locked placeholder and any address Apollo itself flags as
        # dead -- neither is a contactable mailbox.
        if _LOCKED_EMAIL_MARKER in email or email_status in _DEAD_EMAIL_STATUSES:
            email = ""
        # "verified" is Apollo's own deliverability check; "guessed" is a
        # pattern inference and must still go through the verifier chain.
        email_verified = bool(email) and email_status == "verified"

        phone = ""
        for entry in person.get("phone_numbers") or []:
            if not isinstance(entry, dict):
                continue
            number = (
                entry.get("sanitized_number") or entry.get("raw_number") or ""
            ).strip()
            if not number:
                continue
            # Prefer a mobile when one is present, else keep the first number.
            if (entry.get("type") or "").lower() == "mobile":
                phone = number
                break
            phone = phone or number

        return EnrichmentResult(
            email=email,
            email_verified=email_verified,
            linkedin_url=(person.get("linkedin_url") or "").strip(),
            phone=phone,
            job_title=(person.get("title") or "").strip(),
            provider=PROVIDER,
            raw=person,
        )


# Sentinel meaning "this key is retired, move to the next one". Distinct from
# None, which is a real answer (no such person).
_RETRY = object()


__all__ = ["ApolloFinder", "PROVIDER"]
