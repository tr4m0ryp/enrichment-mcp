"""HTTP-based email verifier using MyEmailVerifier's API.

Server-side confirmation for emails Prospeo returns unverified, and the
backing for the ``verify_email`` tool's in-session guess+verify path.

Free tier: 100 verifications/day = ~3000/month, no credit card.
Endpoint: ``GET /api/validate_single.php?apikey=...&email=...``
Auth: query param ``apikey``.
Rate limit: 30 req/min default (we apply a per-domain client-side cap as a
courtesy). ``VerifyResult`` is inlined here so this module has no dependency
on the (deleted) SMTP-verify package.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.myemailverifier.com/api/validate_single.php"
HTTP_TIMEOUT_SECONDS = 30.0
RATE_LIMIT_INTERVAL = 1.0  # seconds between checks per domain
# Provider treats anything that's not "Valid" as not-deliverable. We map
# their string statuses into our (valid, confidence) shape. catch_all=true
# is delivered to *any* address at the domain so we mark medium confidence
# even when Status=Valid -- a real human may not be reading the inbox.
_STATUS_VALID = "valid"


@dataclass
class VerifyResult:
    """Result of an email verification check."""

    email: str
    valid: bool
    method: str  # "myemailverifier", "catch_all"
    confidence: str  # "high", "medium", "low"


class MyEmailVerifierClient:
    """Async wrapper around the MyEmailVerifier single-validate endpoint.

    Per-domain rate limiting is preserved as a courtesy even though the
    upstream limit is 30 req/min globally; spreading by domain prevents a
    single domain from monopolising the bucket.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError(
                "MyEmailVerifierClient requires a non-empty api_key"
            )
        self._api_key = api_key
        self._domain_last_check: dict[str, float] = {}

    async def verify(self, email: str) -> VerifyResult:
        """Verify a single email; returns VerifyResult."""
        if not email or "@" not in email:
            return VerifyResult(
                email=email or "", valid=False,
                method="myemailverifier", confidence="high",
            )
        domain = email.split("@", 1)[-1].lower()
        await self._rate_limit(domain)

        try:
            payload = await self._call(email)
        except aiohttp.ClientError as exc:
            logger.warning(
                "MyEmailVerifier transport error for %s: %s", email, exc,
            )
            return VerifyResult(
                email=email, valid=False,
                method="myemailverifier", confidence="low",
            )
        except asyncio.TimeoutError:
            logger.warning("MyEmailVerifier timeout for %s", email)
            return VerifyResult(
                email=email, valid=False,
                method="myemailverifier", confidence="low",
            )
        except Exception:
            logger.exception("MyEmailVerifier unexpected error for %s", email)
            return VerifyResult(
                email=email, valid=False,
                method="myemailverifier", confidence="low",
            )

        return _parse_response(email, payload)

    async def verify_batch(self, emails: list[str]) -> list[VerifyResult]:
        """Sequential batch verify."""
        out: list[VerifyResult] = []
        for e in emails:
            out.append(await self.verify(e))
        return out

    async def _call(self, email: str) -> dict:
        params = {"apikey": self._api_key, "email": email}
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ENDPOINT, params=params) as resp:
                # Provider returns HTTP 200 even on quota / auth errors,
                # with the failure reason in the JSON body. Parse any
                # non-2xx into a payload too so _parse_response can
                # log + return invalid/low.
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = {"_raw_text": (await resp.text())[:200]}
                if resp.status != 200:
                    logger.warning(
                        "MyEmailVerifier HTTP %s for %s: %s",
                        resp.status, email, str(body)[:200],
                    )
                return body if isinstance(body, dict) else {}

    async def _rate_limit(self, domain: str) -> None:
        now = time.monotonic()
        last = self._domain_last_check.get(domain, 0.0)
        elapsed = now - last
        if elapsed < RATE_LIMIT_INTERVAL:
            await asyncio.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self._domain_last_check[domain] = time.monotonic()


def _parse_response(email: str, body: dict) -> VerifyResult:
    """Map the provider's response into VerifyResult."""
    status = (body.get("Status") or "").strip().lower()
    catch_all = _truthy(body.get("catch_all"))
    role_based = _truthy(body.get("Role_Based"))
    disposable = _truthy(body.get("Disposable_Domain"))
    diagnosis = (body.get("Diagnosis") or "")[:80]

    if status == _STATUS_VALID:
        # Catch-all domains accept every address; mark medium confidence.
        if catch_all:
            return VerifyResult(
                email=email, valid=True,
                method="catch_all", confidence="medium",
            )
        # Disposable domains shouldn't be sent to even if Valid.
        if disposable:
            return VerifyResult(
                email=email, valid=False,
                method="myemailverifier", confidence="high",
            )
        return VerifyResult(
            email=email, valid=True,
            method="myemailverifier",
            confidence="medium" if role_based else "high",
        )

    # Non-Valid: invalid, unknown, greylisted, etc.
    logger.info(
        "MyEmailVerifier: %s -> %s (%s)",
        email, status or "no-status", diagnosis,
    )
    return VerifyResult(
        email=email, valid=False,
        method="myemailverifier",
        confidence="high" if status == "invalid" else "low",
    )


def _truthy(value) -> bool:
    """Provider returns booleans as the strings 'true'/'false'."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)
