"""Prospeo person enrichment with a multi-key pool -- the primary tier.

Prospeo's free tier grants ~75-100 enrichments per account per month, so
we scale by configuring multiple API keys -- the shared ``key_pool.KeyPool``
rotates round-robin across keys, parking any key hit by 429 /
INSUFFICIENT_CREDITS errors for an hour and permanently disabling keys
that report INVALID_API_KEY.

When the whole pool is spent, ``find`` raises ``ProviderUnavailableError``
rather than returning ``None``: exhaustion is not evidence that the person
does not exist, and conflating the two would let a quota wall masquerade as
a miss. ``ChainedFinder`` catches it and fails over to Apollo.

Cost model:
  - Default call (``enrich_mobile=False``): 1 credit per match. Returns
    email + linkedin_url + current_job_title. Phone numbers come back
    for free WHEN Prospeo has volunteered them in their cached record.
    Recommended mode: predictable 1-credit cost.
  - Reveal call (``enrich_mobile=True``): 10 credits per match. Returns
    a guaranteed full phone number (when Prospeo has one). Drops monthly
    capacity 10x. Gated behind ``PROSPEO_ENRICH_MOBILE`` (default false).
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import asyncpg

from .finder import EnrichmentResult, ProviderUnavailableError, log_usage
from .key_pool import KeyPool, redact

logger = logging.getLogger(__name__)

PROSPEO_ENRICH_URL = "https://api.prospeo.io/enrich-person"
TIMEOUT_SECONDS = 30.0
PROVIDER = "prospeo"
# Per Prospeo docs: 1 credit/match, 10 credits/match when mobile
# revealed, 0 for "free_enrichment" (lifetime account dedup).
_CREDITS_EMAIL_ONLY = 1
_CREDITS_WITH_MOBILE = 10

# Retained for import compatibility: the result shape is now provider-neutral
# and shared with Apollo, but callers still refer to it by the old name.
ProspeoResult = EnrichmentResult


class ProspeoFinder:
    """Async multi-key Prospeo client.

    Round-robins across keys to maximize free-tier coverage. Quota
    accounting is reactive -- we don't poll Prospeo's account-info
    endpoint, instead reacting to 429 / INSUFFICIENT_CREDITS error
    codes as the signal to rotate.
    """

    def __init__(
        self,
        api_keys: list[str],
        usage_pool: asyncpg.Pool | None = None,
    ):
        self._pool = KeyPool(api_keys)
        # Optional asyncpg pool for usage logging. When set, every
        # credit-spending call is recorded to ``prospeo_usage`` so credit
        # burn is queryable. Logging failures are swallowed -- never block
        # a resolution because we couldn't write a metrics row.
        self._usage_pool = usage_pool
        if not len(self._pool):
            logger.info("ProspeoFinder: no API keys configured -- disabled")
        else:
            logger.info(
                "ProspeoFinder: %d keys configured (usage_logging=%s)",
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

        Returns ``None`` only on a definitive miss:
          - first_name or domain is empty (no call made),
          - Prospeo returns NO_MATCH or INVALID_DATAPOINTS for this
            specific contact (a real answer about this person),
          - Prospeo matched but the record carried nothing usable.

        Raises ``ProviderUnavailableError`` when Prospeo could not answer at
        all -- no keys configured, every key exhausted or dead, or a
        transport-level error on every available key. The chain treats that
        as "ask the next provider", never as "this person does not exist".

        On success returns an ``EnrichmentResult`` whose fields are stripped
        and lower-cased where applicable. The caller decides how to
        persist them.
        """
        if not first_name or not domain:
            return None
        if not self.enabled:
            raise ProviderUnavailableError("prospeo: no usable API keys")

        body = {
            "only_verified_email": False,
            "enrich_mobile": enrich_mobile,
            "only_verified_mobile": False,
            "data": {
                "first_name": first_name,
                "last_name": last_name or "",
                "company_website": domain,
            },
        }

        # Try keys until one resolves the contact, or we exhaust the
        # pool. Transport errors fall through to the next key; logical
        # errors (NO_MATCH) terminate immediately because they're not
        # retryable on a different key.
        for _ in range(len(self._pool)):
            state = await self._pool.pick()
            if state is None:
                logger.warning(
                    "ProspeoFinder: all keys exhausted/dead for %s %s @ %s",
                    first_name, last_name, domain,
                )
                raise ProviderUnavailableError(
                    "prospeo: all keys exhausted or dead"
                )
            try:
                status, body_resp = await self._call_one(state.api_key, body)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "ProspeoFinder: HTTP error on key %s for %s %s @ %s: %s",
                    redact(state.api_key), first_name, last_name, domain, exc,
                )
                continue

            error_code = (
                body_resp.get("error_code")
                if isinstance(body_resp, dict) else None
            )

            if (
                status == 200
                and isinstance(body_resp, dict)
                and not body_resp.get("error")
            ):
                result = self._extract(body_resp)
                if result.email or result.linkedin_url:
                    free_dedup = bool(body_resp.get("free_enrichment", False))
                    credits = (
                        0 if free_dedup
                        else (_CREDITS_WITH_MOBILE if enrich_mobile
                              else _CREDITS_EMAIL_ONLY)
                    )
                    logger.info(
                        "ProspeoFinder: hit on key %s for %s %s @ %s "
                        "(email=%s linkedin=%s phone=%s credits=%d "
                        "free_dedup=%s)",
                        redact(state.api_key), first_name, last_name, domain,
                        bool(result.email), bool(result.linkedin_url),
                        bool(result.phone), credits, free_dedup,
                    )
                    await log_usage(
                        self._usage_pool, PROVIDER, state.api_key,
                        credits, domain, free_dedup,
                    )
                    return result
                # Empty result body -- treat as miss without rotating.
                # Log a 0-credit row so the call-count reflects it.
                await log_usage(
                    self._usage_pool, PROVIDER, state.api_key, 0, domain,
                )
                return None

            if status == 401 or error_code == "INVALID_API_KEY":
                await self._pool.mark_dead(state.api_key)
                continue

            if status == 429 or error_code in (
                "RATE_LIMITED", "INSUFFICIENT_CREDITS",
            ):
                logger.info(
                    "ProspeoFinder: key %s exhausted (status=%s code=%s); "
                    "rotating",
                    redact(state.api_key), status, error_code,
                )
                await self._pool.mark_exhausted(state.api_key)
                continue

            if error_code in ("NO_MATCH", "INVALID_DATAPOINTS"):
                logger.info(
                    "ProspeoFinder: %s for %s %s @ %s (definitive miss)",
                    error_code, first_name, last_name, domain,
                )
                # Log a 0-credit row so the call-count reflects every API
                # call we made, not just credit-spending hits. Prospeo
                # doesn't bill these but they are real activity.
                await log_usage(
                    self._usage_pool, PROVIDER, state.api_key, 0, domain,
                )
                return None

            logger.warning(
                "ProspeoFinder: unexpected error %s/%s for %s %s @ %s; "
                "body=%.200s",
                status, error_code, first_name, last_name, domain,
                str(body_resp),
            )
            # Unclassified provider-side failure (5xx, malformed envelope):
            # try the next key rather than declaring the person nonexistent.
            continue

        raise ProviderUnavailableError(
            "prospeo: every key failed for this request"
        )

    async def _call_one(
        self, api_key: str, body: dict,
    ) -> tuple[int, dict | None]:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        headers = {"X-KEY": api_key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(
                PROSPEO_ENRICH_URL, headers=headers, json=body,
            ) as r:
                try:
                    parsed = await r.json()
                except Exception:
                    parsed = None
                return r.status, parsed

    @staticmethod
    def _extract(body: dict) -> EnrichmentResult:
        person = body.get("person") or {}
        email_obj = person.get("email") or {}
        mobile_obj = person.get("mobile") or {}
        email = (email_obj.get("email") or "").strip().lower()
        email_verified = (
            (email_obj.get("status") or "").upper() == "VERIFIED"
        )
        linkedin_url = (person.get("linkedin_url") or "").strip()
        # Prefer the international form so a tel: link renders without
        # country-code ambiguity.
        phone = (
            mobile_obj.get("mobile_international")
            or mobile_obj.get("mobile")
            or ""
        ).strip()
        job_title = (person.get("current_job_title") or "").strip()
        return EnrichmentResult(
            email=email,
            email_verified=email_verified,
            linkedin_url=linkedin_url,
            phone=phone,
            job_title=job_title,
            provider=PROVIDER,
            raw=body,
        )
