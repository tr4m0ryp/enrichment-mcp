"""Turn one Apollo ``people/match`` person object into an ``EnrichmentResult``.

Pure and network-free, so the mapping can be tested against a recorded
response without a key or a plan -- which matters here, because Apollo gates
``people/match`` by plan and a blocked account can never exercise this path
live. ``tests/fixtures/apollo_person_match.json`` is Apollo's own published
sample, so the field names below are the ones the API really emits.

The non-obvious work is rejecting addresses that *look* like emails but are
not contactable: the ``email_not_unlocked@...`` sentinel Apollo substitutes
when the account lacks the credits or plan to reveal the real one, and any
address Apollo itself flags bounced/unavailable. Either reaching the lead
store would mean mailing an address the provider already told us is dead.
"""

from __future__ import annotations

from ..finder import EnrichmentResult

PROVIDER = "apollo"

# Apollo substitutes this local-part when the address is not revealed to this
# account. It is a sentinel, never a mailbox.
_LOCKED_EMAIL_MARKER = "email_not_unlocked"

# email_status values meaning "this address is known bad or absent".
_DEAD_EMAIL_STATUSES = {"unavailable", "bounced", "invalid"}

# Apollo's own deliverability check. Anything else -- notably "guessed", a
# pattern inference -- still has to clear the verifier chain before we trust it.
_VERIFIED_STATUS = "verified"


def extract_person(person: dict) -> EnrichmentResult:
    """Map Apollo's ``person`` object onto the provider-neutral result."""
    email_status = (person.get("email_status") or "").strip().lower()
    email = (person.get("email") or "").strip().lower()
    if _LOCKED_EMAIL_MARKER in email or email_status in _DEAD_EMAIL_STATUSES:
        email = ""

    return EnrichmentResult(
        email=email,
        email_verified=bool(email) and email_status == _VERIFIED_STATUS,
        linkedin_url=(person.get("linkedin_url") or "").strip(),
        phone=_best_phone(person.get("phone_numbers")),
        job_title=(person.get("title") or "").strip(),
        provider=PROVIDER,
        raw=person,
    )


def _best_phone(numbers: list | None) -> str:
    """Pick one number: a mobile if present, else the first usable entry.

    ``phone_numbers`` is null on most records and its ``type`` is frequently
    null even when numbers exist, so neither can be assumed present. Prefer
    ``sanitized_number`` (E.164) so a ``tel:`` link has no country ambiguity.
    """
    fallback = ""
    for entry in numbers or []:
        if not isinstance(entry, dict):
            continue
        number = (
            entry.get("sanitized_number") or entry.get("raw_number") or ""
        ).strip()
        if not number:
            continue
        if (entry.get("type") or "").lower() == "mobile":
            return number
        fallback = fallback or number
    return fallback


__all__ = ["extract_person", "PROVIDER"]
