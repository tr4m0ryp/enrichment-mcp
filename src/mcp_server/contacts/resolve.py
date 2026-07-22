"""Contact resolution core -- one Claude-named person, verified.

Distilled from clay's ``email_resolver`` worker into a single write-free
coroutine. The Claude session has already identified the one decision-maker
during qualification, so the server just enriches that known person through
the configured enrichment chain (Prospeo's free-tier key pool primary,
Apollo as the failover tier) and confirms the email.

What was deliberately dropped from the original ``_resolve_one``:
  - The grounded-search NO_MATCH fallback (replaced by the session's own
    in-session guess + the ``verify_email`` tool).
  - The always-on worker loop, DB-backed pair fetching, and the
    persistence step (resolution is now pure -- the only write is the
    finders' own ``prospeo_usage`` credit logging).

Two distinct not-found signals reach the session, and the difference is
operationally important: ``reason="no_match"`` means a provider actually
answered and the person is not in its database (fall back to guess+verify),
whereas ``reason="provider_unavailable"`` means every provider was out of
quota or unreachable (a capacity problem -- top up keys, do not conclude
anything about the person).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .finder import Finder, ProviderUnavailableError
from .helpers import extract_domain, split_name
from .verifier import MyEmailVerifierAPIError, MyEmailVerifierClient
from .verify_chain import ChainedEmailVerifier, NoVerifierAvailableError

_Verifier = MyEmailVerifierClient | ChainedEmailVerifier

logger = logging.getLogger(__name__)


@dataclass
class ContactResult:
    """Pure data return for one resolution attempt.

    ``email`` is only ever populated when verified (the provider's own
    VERIFIED flag or a positive verifier verdict), so a non-empty ``email``
    always implies ``email_verified is True``. ``reason`` carries the
    not-found / partial signal the session branches on. ``source`` names the
    provider that produced the hit (``prospeo``, ``apollo``, or
    ``<provider>+verifier`` when the verifier chain confirmed the address).
    """

    found: bool = False
    email: str = ""
    email_verified: bool = False
    linkedin_url: str = ""
    job_title: str = ""
    source: str = "none"
    reason: str = ""


async def resolve_contact(
    company_name: str,
    domain: str,
    person_name: str,
    role: str = "",
    *,
    finder: Finder,
    verifier: _Verifier | None = None,
    enrich_mobile: bool = False,
) -> ContactResult:
    """Resolve one known person to a verified contact via the finder chain.

    1. ``split_name`` the person, ``extract_domain`` the website.
    2. ``finder.find(first, last, domain)``. The chain tries Prospeo first and
       fails over to Apollo when Prospeo is out of quota, dead, or (by
       default) returns no match. On a hit take email / linkedin / title;
       accept the email if the provider flags it verified, otherwise run
       ``verifier.verify`` and accept only if valid. ``source`` is the
       winning provider, suffixed ``+verifier`` when the chain confirmed it.
    3. On a definitive miss return ``found=False, reason="no_match"``.
    4. When no provider could answer at all, return ``found=False,
       reason="provider_unavailable"`` -- explicitly NOT a miss.
    """
    first, last = split_name(person_name)
    clean_domain = extract_domain(domain)
    if not first or not clean_domain:
        return ContactResult(found=False, reason="insufficient_input")

    if finder is None or not finder.enabled:
        return ContactResult(found=False, reason="provider_unavailable")

    try:
        hit = await finder.find(
            first, last, clean_domain, enrich_mobile=enrich_mobile,
        )
    except ProviderUnavailableError as exc:
        logger.warning(
            "resolve_contact: no enrichment provider could answer for "
            "%s %s @ %s: %s",
            first, last, clean_domain, exc,
        )
        return ContactResult(found=False, reason="provider_unavailable")

    if hit is None:
        return ContactResult(found=False, reason="no_match")

    provider = hit.provider or "unknown"
    linkedin_url = hit.linkedin_url or ""
    job_title = hit.job_title or ""

    # Provider matched the person but gave no email (linkedin-only record).
    if not hit.email:
        return ContactResult(
            found=bool(linkedin_url),
            linkedin_url=linkedin_url,
            job_title=job_title,
            source=provider if linkedin_url else "none",
            reason="" if linkedin_url else "no_email",
        )

    # The provider's own MX-level check passed -- accept without a second call.
    if hit.email_verified:
        return ContactResult(
            found=True,
            email=hit.email,
            email_verified=True,
            linkedin_url=linkedin_url,
            job_title=job_title,
            source=provider,
        )

    # Unverified email: confirm with the verifier chain, accept only if valid.
    if await _verify(hit.email, verifier):
        return ContactResult(
            found=True,
            email=hit.email,
            email_verified=True,
            linkedin_url=linkedin_url,
            job_title=job_title,
            source=f"{provider}+verifier",
        )

    logger.info(
        "resolve_contact: %s email %s did not verify; "
        "keeping linkedin/title only",
        provider, hit.email,
    )
    return ContactResult(
        found=bool(linkedin_url),
        linkedin_url=linkedin_url,
        job_title=job_title,
        source=provider if linkedin_url else "none",
        reason="email_unverified",
    )


async def _verify(
    email: str, verifier: _Verifier | None,
) -> bool:
    """Run the verifier; swallow exceptions so one bad call never crashes
    a resolution. Returns False when no verifier is configured.
    """
    if verifier is None:
        return False
    try:
        result = await verifier.verify(email)
    except (MyEmailVerifierAPIError, NoVerifierAvailableError) as exc:
        # Provider-side failure (bad key, exhausted quota/pool), not a
        # verdict on this mailbox -- log distinctly and fall back to
        # unverified rather than ever reporting a false "invalid".
        logger.warning(
            "resolve_contact: email verifier unavailable for %s: %s",
            email, exc,
        )
        return False
    except Exception:
        logger.exception("resolve_contact: verify call raised for %s", email)
        return False
    # Reject catch-all domains: they accept every address, so a "valid" verdict
    # there is not a real confirmation that THIS mailbox exists. Only a
    # non-catch-all valid result counts as verified.
    return (
        bool(getattr(result, "valid", False))
        and getattr(result, "method", "") != "catch_all"
    )
