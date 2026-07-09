"""The two contact-resolution tools (T3, T8): ``resolve_contact`` + ``verify_email``.

Both share one Prospeo enrich-person finder and one chained email verifier
(QuickEmailVerification's key pool first, MyEmailVerifier second), built
lazily on first call from ``get_config()`` -- so importing the server (or
building the app) never opens a DB connection or HTTP session. The asyncpg pool
is handed to the finder as its ``usage_pool`` so Prospeo credit burn is metered
(T4). ``resolve_contact`` is deliberately write-free (T3): it enriches the one
person the session already named and returns the result, but never persists a
lead -- compose it with ``add_qualified_lead`` to store the contact.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..config import get_config
from ..contacts import (
    ChainedEmailVerifier,
    MyEmailVerifierClient,
    NoVerifierAvailableError,
    ProspeoFinder,
    QuickEmailVerificationClient,
)
from ..contacts import resolve_contact as _resolve_core
from ..db import get_pool

logger = logging.getLogger(__name__)

# Shared, lazily-built dependencies (one finder + one verifier chain per process).
_finder: ProspeoFinder | None = None
_verifier: ChainedEmailVerifier | None = None
_deps_built = False


async def _deps() -> tuple[ProspeoFinder, ChainedEmailVerifier | None]:
    """Build (once) and return the shared Prospeo finder + verifier chain.

    Opens the asyncpg pool on first use and passes it to the finder for usage
    metering. The chain tries QuickEmailVerification's key pool first, then
    MyEmailVerifier; the whole chain is ``None`` when neither is configured.
    """
    global _finder, _verifier, _deps_built
    if not _deps_built:
        cfg = get_config()
        pool = await get_pool()
        _finder = ProspeoFinder(cfg.prospeo_api_keys, usage_pool=pool)
        tiers = []
        if cfg.quickemailverification_api_keys:
            tiers.append(
                QuickEmailVerificationClient(cfg.quickemailverification_api_keys)
            )
        if cfg.myemailverifier_api_key:
            tiers.append(MyEmailVerifierClient(cfg.myemailverifier_api_key))
        _verifier = ChainedEmailVerifier(tiers) if tiers else None
        _deps_built = True
    assert _finder is not None
    return _finder, _verifier


async def resolve_contact(
    company_name: str,
    domain: str,
    person_name: str,
    role: str | None = None,
) -> dict:
    """Resolve one already-identified decision-maker to a verified email.

    Enriches the single person the session named during qualification, via the
    Prospeo enrich-person pool, and confirms the email (Prospeo's own check or
    the QuickEmailVerification/MyEmailVerifier fallback chain). This does NOT
    create or update a lead --
    it is idempotent and composable; call ``add_qualified_lead`` yourself to
    store the contact. On a hit returns ``{found, email, email_verified,
    linkedin_url, job_title, source}``; otherwise ``{found: false, reason}``
    where ``reason`` is one of no_match / no_email / email_unverified /
    insufficient_input / prospeo_unavailable.
    """
    finder, verifier = await _deps()
    cfg = get_config()
    result = await _resolve_core(
        company_name,
        domain,
        person_name,
        role or "",
        prospeo=finder,
        verifier=verifier,
        enrich_mobile=cfg.prospeo_enrich_mobile,
    )
    if not result.found:
        return {"found": False, "reason": result.reason or "no_match"}
    return {
        "found": True,
        "email": result.email,
        "email_verified": result.email_verified,
        "linkedin_url": result.linkedin_url,
        "job_title": result.job_title,
        "source": result.source,
    }


async def verify_email(email: str) -> dict:
    """Verify a single email address (QuickEmailVerification, falling back to
    MyEmailVerifier).

    Backs the in-session guess+verify fallback (T1/T8): when ``resolve_contact``
    returns no verified email, the session can construct the most likely address
    and confirm deliverability here. Tries QuickEmailVerification's key pool
    first (higher free-tier volume, rotates across configured keys), falling
    back to MyEmailVerifier only if that whole pool is exhausted/unconfigured.
    Returns ``{status, valid, confidence, method}`` where ``status`` is one of
    ``"valid"`` / ``"invalid"`` / ``"catch_all"``. A catch-all domain accepts
    ANY address, so a raw "valid" there only means "the domain accepts mail",
    not "this mailbox exists" -- therefore ``valid`` is true ONLY for a
    confirmed, non-catch-all mailbox, and a catch-all comes back ``status:
    "catch_all", valid: false``. Accept a guessed address only when ``valid``
    is true. Errors (rather than returning a fabricated verdict) if no
    verifier is configured, or if every configured tier is unavailable (bad
    key, exhausted quota) -- a broken verifier must never be mistaken for a
    confirmed-invalid mailbox.
    """
    _, verifier = await _deps()
    if verifier is None:
        raise ToolError(
            "verify_email unavailable: no email verifier configured "
            "(set QUICKEMAILVERIFICATION_API_KEYS and/or MYEMAILVERIFIER_API_KEY)"
        )
    try:
        result = await verifier.verify(email)
    except NoVerifierAvailableError as exc:
        raise ToolError(f"verify_email unavailable: {exc}") from exc
    catch_all = result.method == "catch_all"
    return {
        "status": "catch_all" if catch_all
        else ("valid" if result.valid else "invalid"),
        "valid": result.valid and not catch_all,
        "confidence": result.confidence,
        "method": result.method,
    }


def register_resolve_tools(mcp: FastMCP) -> None:
    """Register ``resolve_contact`` and ``verify_email`` on ``mcp``."""
    mcp.tool(resolve_contact)
    mcp.tool(verify_email)


__all__ = ["resolve_contact", "verify_email", "register_resolve_tools"]
