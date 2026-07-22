"""Live probe of ApolloFinder against the real Apollo API.

Hits api.apollo.io with the key in ``APOLLO_API_KEYS`` and asserts the client
handles whatever the account's plan actually allows. Two outcomes are both
treated as a pass, because both are correct behaviour:

  - The plan includes ``people/match``: the finder returns a hit or a clean
    ``None`` miss, and the key stays enabled.
  - The plan excludes it (403 API_INACCESSIBLE, e.g. free/trial): the finder
    raises ``ProviderUnavailableError``, retires the key, and is skipped from
    then on -- costing exactly one probe for the process lifetime.

The failure this test exists to catch is a blocked plan degrading anything:
the chain must still resolve through Prospeo, and Apollo must not be re-probed
on every lead.

Run: APOLLO_API_KEYS=... python -m tests.test_apollo_live
"""

from __future__ import annotations

import asyncio
import os
import sys

from src.mcp_server.contacts import (
    ApolloFinder,
    ChainedFinder,
    EnrichmentResult,
    ProviderUnavailableError,
    resolve_contact,
)

# A public figure at a domain Apollo certainly indexes -- a miss here is a
# plan/coverage signal, not a bug in the client.
PROBE = ("Tim", "Zheng", "apollo.io")


class StubProspeo:
    """Healthy Prospeo stand-in, so the live test needs no Prospeo credits."""

    name = "prospeo"

    def __init__(self, mode: str = "hit") -> None:
        self.mode = mode
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return True

    async def find(self, first, last, domain, *, enrich_mobile=False):
        self.calls += 1
        if self.mode == "unavailable":
            raise ProviderUnavailableError("prospeo: quota exhausted (simulated)")
        return EnrichmentResult(
            email=f"{first}@{domain}".lower(), email_verified=True,
            job_title="CTO", provider="prospeo",
        )


async def main() -> int:
    keys = [k.strip() for k in os.environ.get("APOLLO_API_KEYS", "").split(",") if k.strip()]
    if not keys:
        print("  [SKIP] APOLLO_API_KEYS not set")
        return 0

    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{f'  -- {detail}' if detail else ''}")

    apollo = ApolloFinder(keys)
    check("finder starts enabled", apollo.enabled)

    plan_blocked = False
    try:
        hit = await apollo.find(*PROBE)
        if hit is None:
            check("live call returned a clean miss", True, "person not in Apollo")
        else:
            check("live call returned a hit", True,
                  f"provider={hit.provider} email={bool(hit.email)} "
                  f"verified={hit.email_verified} title={hit.job_title!r}")
            check("hit is attributed to apollo", hit.provider == "apollo")
            check("no locked-email placeholder leaked",
                  "email_not_unlocked" not in (hit.email or ""), hit.email)
    except ProviderUnavailableError as exc:
        plan_blocked = True
        check("blocked plan raises ProviderUnavailableError", True, str(exc))

    if plan_blocked:
        check("blocked key is retired after one probe", not apollo.enabled)
        # The whole point: a second lead must not pay for another round-trip.
        try:
            await apollo.find("Someone", "Else", "stripe.com")
            check("retired key short-circuits", False, "did not raise")
        except ProviderUnavailableError:
            check("retired key short-circuits without a call", True)

    # --- no-regression: a blocked Apollo must not disturb resolution ---
    prospeo = StubProspeo("hit")
    chain = ChainedFinder([prospeo, apollo])
    r = await resolve_contact(
        "Apollo", "https://apollo.io", "Tim Zheng", finder=chain, verifier=None,
    )
    check("resolution still succeeds via prospeo", r.found and r.source == "prospeo",
          f"found={r.found} source={r.source} reason={r.reason}")

    # --- the requirement: Prospeo out of quota hands off to Apollo ---
    down = StubProspeo("unavailable")
    chain2 = ChainedFinder([down, apollo])
    r2 = await resolve_contact(
        "Apollo", "https://apollo.io", "Tim Zheng", finder=chain2, verifier=None,
    )
    if plan_blocked:
        check("prospeo-down + apollo-blocked reports provider_unavailable",
              not r2.found and r2.reason == "provider_unavailable", r2.reason)
        print("\n  NOTE: Apollo's plan blocks people/match, so failover cannot")
        print("  actually resolve yet. The wiring is verified; it needs a paid plan.")
    else:
        check("prospeo-down hands off to apollo",
              r2.found or r2.reason == "no_match",
              f"found={r2.found} source={r2.source} reason={r2.reason}")

    print(f"\n{'FAILURES: ' + str(failures) if failures else 'all live checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
