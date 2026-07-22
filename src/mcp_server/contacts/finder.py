"""Shared contract for person-enrichment providers, plus the failover chain.

One resolution can be served by more than one provider (Prospeo's free-tier
key pool primary, Apollo as the paid backstop). This module owns the three
things they share:

  - ``EnrichmentResult`` -- the provider-neutral hit shape every finder
    returns, carrying ``provider`` so the caller can attribute the source.
  - ``ProviderUnavailableError`` -- the signal that separates "I could not
    answer" from "I answered: no such person". This distinction is the whole
    basis of failover: a quota-exhausted provider must fall through to the
    next tier, whereas a definitive NO_MATCH is a real answer and (by
    default) still worth a second opinion from another database.
  - ``ChainedFinder`` -- tries tiers in order under those rules.

The same split already governs the email verifiers in ``verify_chain``; a
provider outage must degrade capacity, never fabricate a verdict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import asyncpg

from .key_pool import redact

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Fields the caller persists from a successful enrichment.

    ``raw`` is the full provider response so downstream code can mine extra
    fields (company data, job history, location) without re-running the call.
    ``provider`` names the tier that produced the hit and flows into
    ``ContactResult.source``.
    """

    email: str = ""
    email_verified: bool = False
    linkedin_url: str = ""
    phone: str = ""
    job_title: str = ""
    provider: str = ""
    raw: dict | None = None


class ProviderUnavailableError(Exception):
    """This provider could not answer at all -- every key is exhausted, dead,
    or unreachable. NOT a verdict on the person. Callers fall through to the
    next tier; the chain only surfaces it when no tier can answer.
    """


class Finder(Protocol):
    """What ``resolve_contact`` needs from any enrichment provider."""

    @property
    def enabled(self) -> bool: ...

    async def find(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        *,
        enrich_mobile: bool = False,
    ) -> EnrichmentResult | None: ...


class ChainedFinder:
    """Composes ordered enrichment tiers behind one ``.find()``.

    Failover rules, in the order they are evaluated per tier:

    - Tier raises ``ProviderUnavailableError`` (quota / dead keys / transport)
      -> try the next tier. This is the quota-failover the pipeline depends on.
    - Tier returns ``None`` (definitive NO_MATCH) -> try the next tier only
      when ``fallback_on_no_match`` is set. Different providers hold different
      databases, so a miss in one is genuinely worth re-asking; providers bill
      nothing when they return no data, which is why this defaults to on.
    - Tier returns a hit -> return it immediately, no further tiers called.

    If every tier was unavailable, re-raise ``ProviderUnavailableError`` so the
    caller reports "provider unavailable" rather than a false "no such person".
    If at least one tier gave a real NO_MATCH, return ``None`` -- that is an
    answer, and it outranks the other tiers' silence.
    """

    def __init__(
        self,
        finders: list[Finder],
        *,
        fallback_on_no_match: bool = True,
    ) -> None:
        self._finders = list(finders)
        self._fallback_on_no_match = fallback_on_no_match

    @property
    def enabled(self) -> bool:
        return any(f.enabled for f in self._finders)

    def __len__(self) -> int:
        return len(self._finders)

    async def find(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        *,
        enrich_mobile: bool = False,
    ) -> EnrichmentResult | None:
        last_exc: Exception | None = None
        answered_no_match = False

        for tier in self._finders:
            name = type(tier).__name__
            # A tier whose keys are all permanently dead (bad key, or a plan
            # that does not include the endpoint) is skipped without a call --
            # this is what keeps an unusable provider from costing a round-trip
            # on every single resolution.
            if not tier.enabled:
                continue
            try:
                hit = await tier.find(
                    first_name, last_name, domain, enrich_mobile=enrich_mobile,
                )
            except ProviderUnavailableError as exc:
                logger.info(
                    "ChainedFinder: tier %s unavailable for %s %s @ %s (%s); "
                    "falling through",
                    name, first_name, last_name, domain, exc,
                )
                last_exc = exc
                continue

            if hit is not None:
                return hit

            answered_no_match = True
            if not self._fallback_on_no_match:
                return None
            logger.info(
                "ChainedFinder: tier %s no_match for %s %s @ %s; "
                "trying next tier",
                name, first_name, last_name, domain,
            )

        if answered_no_match:
            return None
        if last_exc is not None:
            raise ProviderUnavailableError(
                f"every configured enrichment provider is unavailable: "
                f"{last_exc}"
            ) from last_exc
        raise ProviderUnavailableError(
            "no enrichment provider is configured or enabled"
        )


async def log_usage(
    usage_pool: asyncpg.Pool | None,
    provider: str,
    api_key: str,
    credits: int,
    domain: str,
    free_dedup: bool = False,
) -> None:
    """Record one credit-metered enrichment call to ``prospeo_usage``.

    The table predates the multi-provider split and keeps its name for
    migration safety; the ``provider`` column (schema 005) is what separates
    Prospeo from Apollo spend. Failures are swallowed -- never block a
    resolution because a metrics row would not write.
    """
    if usage_pool is None:
        return
    try:
        async with usage_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prospeo_usage
                    (key_prefix, credits, domain, free_dedup, provider)
                VALUES ($1, $2, $3, $4, $5)
                """,
                redact(api_key), int(credits), domain, bool(free_dedup),
                provider,
            )
    except Exception:
        logger.exception(
            "log_usage: failed to write %s usage row "
            "(non-fatal -- continuing)", provider,
        )


__all__ = [
    "EnrichmentResult",
    "ProviderUnavailableError",
    "Finder",
    "ChainedFinder",
    "log_usage",
]
