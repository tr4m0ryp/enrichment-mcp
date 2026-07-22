"""ApolloFinder response parsing, against a real people/match person object.

``fixtures/apollo_person_match.json`` is the genuine sample response published
in Apollo's own API reference, not a hand-written mock -- so the field names
under test (``email_status``, ``title``, ``linkedin_url``,
``phone_numbers[].sanitized_number``) are the ones the live API actually emits.
This matters because the account's plan currently blocks ``people/match``, so
the hit path cannot be exercised against the live endpoint; the fixture is what
proves the parser is aimed at the right schema.

The variants cover the ways Apollo returns something that looks like an email
but is not contactable -- the locked placeholder, and addresses Apollo itself
flags bounced or unavailable. Any of those reaching the lead store would mean
sending mail to an address the provider already told us is dead.

Run: python -m tests.test_apollo_parse   (no network, no DB, no key)
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

from src.mcp_server.contacts.apollo import ApolloFinder

FIXTURE = Path(__file__).parent / "fixtures" / "apollo_person_match.json"
PERSON = json.loads(FIXTURE.read_text())

_results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((ok, name, detail))


def test_extracts_real_person() -> None:
    r = ApolloFinder._extract(PERSON)
    check("email parsed", r.email == "tim@apollo.io", r.email)
    check("verified status honoured", r.email_verified is True)
    check("job title parsed", r.job_title == "Founder & CEO", r.job_title)
    check("linkedin parsed", "linkedin.com/in/tim-zheng" in r.linkedin_url,
          r.linkedin_url)
    check("provider stamped", r.provider == "apollo")
    check("raw retained for later mining", r.raw is not None)
    check("null phone_numbers tolerated", r.phone == "", r.phone)


def test_guessed_email_is_not_pre_verified() -> None:
    """A pattern-guessed address must still go through the verifier chain."""
    p = copy.deepcopy(PERSON)
    p["email_status"] = "guessed"
    r = ApolloFinder._extract(p)
    check("guessed keeps the email", r.email == "tim@apollo.io")
    check("guessed is not marked verified", r.email_verified is False)


def test_locked_placeholder_is_dropped() -> None:
    """`email_not_unlocked@domain.com` is a sentinel, never a mailbox."""
    p = copy.deepcopy(PERSON)
    p["email"] = "email_not_unlocked@domain.com"
    p["email_status"] = "verified"
    r = ApolloFinder._extract(p)
    check("locked placeholder dropped", r.email == "", r.email)
    check("locked placeholder not verified", r.email_verified is False)


def test_dead_statuses_drop_the_email() -> None:
    for status in ("bounced", "unavailable", "invalid"):
        p = copy.deepcopy(PERSON)
        p["email_status"] = status
        r = ApolloFinder._extract(p)
        check(f"{status} email dropped", r.email == "", r.email)


def test_phone_prefers_mobile() -> None:
    p = copy.deepcopy(PERSON)
    p["phone_numbers"] = [
        {"raw_number": "(123) 555-0158", "sanitized_number": "+11235550158",
         "type": "work_hq", "status": "valid_number"},
        {"raw_number": "(123) 555-0126", "sanitized_number": "+11235550126",
         "type": "mobile", "status": "valid_number"},
    ]
    check("mobile preferred over work number",
          ApolloFinder._extract(p).phone == "+11235550126")

    p2 = copy.deepcopy(PERSON)
    p2["phone_numbers"] = [
        {"raw_number": "(123) 555-0158", "sanitized_number": "+11235550158",
         "type": None, "status": "valid_number"},
    ]
    check("untyped number still kept",
          ApolloFinder._extract(p2).phone == "+11235550158")

    p3 = copy.deepcopy(PERSON)
    p3["phone_numbers"] = [{"raw_number": "", "sanitized_number": "", "type": None}]
    check("empty numbers ignored", ApolloFinder._extract(p3).phone == "")


def test_missing_fields_do_not_raise() -> None:
    for person in ({}, {"email": None, "title": None, "linkedin_url": None,
                        "email_status": None, "phone_numbers": None}):
        try:
            r = ApolloFinder._extract(person)
            check("sparse person parses to empties",
                  r.email == "" and r.job_title == "" and r.phone == "")
        except Exception as exc:  # noqa: BLE001
            check("sparse person parses to empties", False, repr(exc))


async def test_no_keys_is_unavailable_not_a_miss() -> None:
    """An unconfigured Apollo must never look like "person does not exist"."""
    from src.mcp_server.contacts import ProviderUnavailableError
    finder = ApolloFinder([])
    check("no keys means disabled", finder.enabled is False)
    try:
        await finder.find("Ada", "Lovelace", "example.com")
        check("no keys raises rather than returning a miss", False)
    except ProviderUnavailableError:
        check("no keys raises rather than returning a miss", True)
    # Empty inputs are a real no-op, not an outage -- and cost no HTTP call.
    check("empty input returns None without calling",
          await finder.find("", "", "") is None)


def main() -> int:
    test_extracts_real_person()
    test_guessed_email_is_not_pre_verified()
    test_locked_placeholder_is_dropped()
    test_dead_statuses_drop_the_email()
    test_phone_prefers_mobile()
    test_missing_fields_do_not_raise()
    asyncio.run(test_no_keys_is_unavailable_not_a_miss())

    failed = sum(1 for ok, _, _ in _results if not ok)
    for ok, name, detail in _results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
              f"{f'  -- {detail}' if detail else ''}")
    print(f"\n{len(_results) - failed}/{len(_results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
