"""Contact resolution core -- one Claude-named person, verified.

Distilled from clay's ``email_resolver`` worker into a single write-free
coroutine. The Claude session has already identified the one decision-maker
during qualification, so the server just enriches that known person through
the Prospeo enrich-person pool and confirms the email.

What was deliberately dropped from the original ``_resolve_one``:
  - The grounded-search NO_MATCH fallback (replaced by the session's own
    in-session guess + the ``verify_email`` tool).
  - The always-on worker loop, DB-backed pair fetching, and the
    persistence step (resolution is now pure -- the only write is Prospeo's
    own ``prospeo_usage`` logging, owned by the finder).

On Prospeo NO_MATCH this returns ``ContactResult(found=False,
reason="no_match")`` -- the session decides whether to attempt the
guess+verify fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .helpers import extract_domain, split_name
from .prospeo import ProspeoFinder
from .verifier import MyEmailVerifierClient

logger = logging.getLogger(__name__)


@dataclass
class ContactResult:
    """Pure data return for one resolution attempt.

    ``email`` is only ever populated when verified (Prospeo VERIFIED or
    MyEmailVerifier Valid), so a non-empty ``email`` always implies
    ``email_verified is True``. ``reason`` carries the not-found / partial
    signal the session branches on.
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
    prospeo: ProspeoFinder,
    verifier: MyEmailVerifierClient | None = None,
    enrich_mobile: bool = False,
) -> ContactResult:
    """Resolve one known person to a verified contact via Prospeo.

    1. ``split_name`` the person, ``extract_domain`` the website.
    2. ``prospeo.find(first, last, domain)``. On a hit take
       email / linkedin / title; accept the email if Prospeo flags it
       VERIFIED, otherwise run ``verifier.verify`` and accept only if
       valid. ``source`` is ``"prospeo"`` or ``"prospeo+verifier"``.
    3. On Prospeo ``None`` (NO_MATCH) return ``found=False,
       reason="no_match"`` -- no fallback here.
    """
    first, last = split_name(person_name)
    clean_domain = extract_domain(domain)
    if not first or not clean_domain:
        return ContactResult(found=False, reason="insufficient_input")

    if prospeo is None or not prospeo.enabled:
        return ContactResult(found=False, reason="prospeo_unavailable")

    hit = await prospeo.find(
        first, last, clean_domain, enrich_mobile=enrich_mobile,
    )
    if hit is None:
        return ContactResult(found=False, reason="no_match")

    linkedin_url = hit.linkedin_url or ""
    job_title = hit.job_title or ""

    # Prospeo matched the person but gave no email (linkedin-only record).
    if not hit.email:
        return ContactResult(
            found=bool(linkedin_url),
            linkedin_url=linkedin_url,
            job_title=job_title,
            source="prospeo" if linkedin_url else "none",
            reason="" if linkedin_url else "no_email",
        )

    # Prospeo's own MX-level check passed -- accept without a second call.
    if hit.email_verified:
        return ContactResult(
            found=True,
            email=hit.email,
            email_verified=True,
            linkedin_url=linkedin_url,
            job_title=job_title,
            source="prospeo",
        )

    # Unverified email: confirm with MyEmailVerifier, accept only if valid.
    if await _verify(hit.email, verifier):
        return ContactResult(
            found=True,
            email=hit.email,
            email_verified=True,
            linkedin_url=linkedin_url,
            job_title=job_title,
            source="prospeo+verifier",
        )

    logger.info(
        "resolve_contact: Prospeo email %s did not verify; "
        "keeping linkedin/title only",
        hit.email,
    )
    return ContactResult(
        found=bool(linkedin_url),
        linkedin_url=linkedin_url,
        job_title=job_title,
        source="prospeo" if linkedin_url else "none",
        reason="email_unverified",
    )


async def _verify(
    email: str, verifier: MyEmailVerifierClient | None,
) -> bool:
    """Run the verifier; swallow exceptions so one bad call never crashes
    a resolution. Returns False when no verifier is configured.
    """
    if verifier is None:
        return False
    try:
        result = await verifier.verify(email)
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
