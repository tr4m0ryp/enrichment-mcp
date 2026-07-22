"""Failover behaviour of the enrichment chain, and the no-regression guarantee.

Two things are under test:

  1. The chain fails over for the right reasons. A quota-exhausted or dead
     provider must fall through to the next tier, while a definitive
     "no such person" must not be mistaken for an outage (or vice versa) --
     that distinction is what stops a credit wall from silently poisoning the
     lead store with false misses.
  2. Adding Apollo changes nothing when Apollo is absent or unusable. With no
     Apollo key, with an Apollo key whose plan blocks the endpoint, and with
     Prospeo healthy, resolution results are identical to the single-provider
     server's.

Run: python -m tests.test_finder_chain   (from the repo root; no DB, no network)
"""

from __future__ import annotations

import asyncio
import sys

from src.mcp_server.contacts import (
    ChainedFinder,
    EnrichmentResult,
    ProviderUnavailableError,
    resolve_contact,
)

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    _results.append((PASS if condition else FAIL, name, detail))


class FakeFinder:
    """Stand-in provider with scriptable behaviour.

    ``mode`` is one of: ``hit`` (returns a result), ``no_match`` (returns
    None -- a real answer), ``unavailable`` (raises, i.e. quota/outage), or
    ``disabled`` (``enabled`` is False, so the chain skips it without a call).
    """

    def __init__(self, name: str, mode: str, email: str = "") -> None:
        self.name = name
        self.mode = mode
        self.email = email
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled"

    async def find(self, first, last, domain, *, enrich_mobile=False):
        self.calls += 1
        if self.mode == "unavailable":
            raise ProviderUnavailableError(f"{self.name}: quota exhausted")
        if self.mode == "no_match":
            return None
        return EnrichmentResult(
            email=self.email or f"{first}@{domain}".lower(),
            email_verified=True,
            linkedin_url=f"https://linkedin.com/in/{first}".lower(),
            job_title="CTO",
            provider=self.name,
        )


async def test_quota_failover() -> None:
    """Prospeo out of credits -> Apollo answers. The stated requirement."""
    prospeo = FakeFinder("prospeo", "unavailable")
    apollo = FakeFinder("apollo", "hit", "hit@example.com")
    chain = ChainedFinder([prospeo, apollo])

    hit = await chain.find("Ada", "Lovelace", "example.com")
    check("quota failover reaches apollo", hit is not None and hit.provider == "apollo")
    check("quota failover calls both tiers", prospeo.calls == 1 and apollo.calls == 1)


async def test_healthy_prospeo_never_touches_apollo() -> None:
    """A Prospeo hit short-circuits -- no Apollo credit is ever spent."""
    prospeo = FakeFinder("prospeo", "hit")
    apollo = FakeFinder("apollo", "hit")
    chain = ChainedFinder([prospeo, apollo])

    hit = await chain.find("Ada", "Lovelace", "example.com")
    check("prospeo hit wins", hit is not None and hit.provider == "prospeo")
    check("apollo not called on prospeo hit", apollo.calls == 0)


async def test_no_match_fallthrough_toggle() -> None:
    """no_match falls through only when the chain is configured to."""
    p1, a1 = FakeFinder("prospeo", "no_match"), FakeFinder("apollo", "hit")
    hit = await ChainedFinder([p1, a1], fallback_on_no_match=True).find(
        "Ada", "Lovelace", "example.com")
    check("no_match falls through when enabled",
          hit is not None and hit.provider == "apollo")

    p2, a2 = FakeFinder("prospeo", "no_match"), FakeFinder("apollo", "hit")
    hit2 = await ChainedFinder([p2, a2], fallback_on_no_match=False).find(
        "Ada", "Lovelace", "example.com")
    check("no_match stops when disabled", hit2 is None and a2.calls == 0)


async def test_all_no_match_is_a_miss_not_an_outage() -> None:
    """Every tier answered "no such person" -> None, never an exception."""
    chain = ChainedFinder([
        FakeFinder("prospeo", "no_match"), FakeFinder("apollo", "no_match"),
    ])
    check("all no_match returns None",
          await chain.find("Ada", "Lovelace", "example.com") is None)


async def test_all_unavailable_raises() -> None:
    """Every tier down -> raise, so the caller never records a false miss."""
    chain = ChainedFinder([
        FakeFinder("prospeo", "unavailable"), FakeFinder("apollo", "unavailable"),
    ])
    try:
        await chain.find("Ada", "Lovelace", "example.com")
        check("all unavailable raises", False, "no exception raised")
    except ProviderUnavailableError:
        check("all unavailable raises", True)


async def test_miss_outranks_outage() -> None:
    """A real no_match beats a silent tier: an answer is better than nothing."""
    chain = ChainedFinder([
        FakeFinder("prospeo", "no_match"), FakeFinder("apollo", "unavailable"),
    ])
    try:
        result = await chain.find("Ada", "Lovelace", "example.com")
        check("real miss outranks an unavailable tier", result is None)
    except ProviderUnavailableError:
        check("real miss outranks an unavailable tier", False, "raised instead")


async def test_disabled_tier_costs_no_call() -> None:
    """A retired provider (dead key / blocked plan) is skipped, not probed."""
    apollo = FakeFinder("apollo", "disabled")
    prospeo = FakeFinder("prospeo", "hit")
    chain = ChainedFinder([prospeo, apollo])
    await chain.find("Ada", "Lovelace", "example.com")
    check("disabled tier never called", apollo.calls == 0)
    check("chain enabled while any tier is", chain.enabled is True)
    check("chain disabled when all tiers are",
          ChainedFinder([FakeFinder("a", "disabled")]).enabled is False)


async def test_resolve_core_unchanged_without_apollo() -> None:
    """Prospeo-only chain behaves exactly as the single-provider server did."""
    chain = ChainedFinder([FakeFinder("prospeo", "hit", "ada@example.com")])
    r = await resolve_contact(
        "Example", "https://www.example.com", "Ada Lovelace",
        finder=chain, verifier=None,
    )
    check("prospeo-only resolves", r.found and r.email == "ada@example.com")
    check("prospeo-only source attributed", r.source == "prospeo")

    miss = ChainedFinder([FakeFinder("prospeo", "no_match")])
    r2 = await resolve_contact(
        "Example", "https://www.example.com", "Ada Lovelace",
        finder=miss, verifier=None,
    )
    check("prospeo-only miss keeps no_match reason",
          not r2.found and r2.reason == "no_match", r2.reason)


async def test_resolve_core_reasons() -> None:
    """Outage and miss produce distinguishable session-facing reasons."""
    down = ChainedFinder([FakeFinder("prospeo", "unavailable")])
    r = await resolve_contact(
        "Example", "example.com", "Ada Lovelace", finder=down, verifier=None,
    )
    check("outage reports provider_unavailable",
          not r.found and r.reason == "provider_unavailable", r.reason)

    empty = ChainedFinder([])
    r2 = await resolve_contact(
        "Example", "example.com", "Ada Lovelace", finder=empty, verifier=None,
    )
    check("empty chain reports provider_unavailable",
          not r2.found and r2.reason == "provider_unavailable", r2.reason)

    r3 = await resolve_contact(
        "Example", "", "Ada Lovelace",
        finder=ChainedFinder([FakeFinder("p", "hit")]), verifier=None,
    )
    check("bad input still reports insufficient_input",
          r3.reason == "insufficient_input", r3.reason)


async def test_apollo_failover_end_to_end() -> None:
    """The headline path, through resolve_contact rather than the raw chain."""
    chain = ChainedFinder([
        FakeFinder("prospeo", "unavailable"),
        FakeFinder("apollo", "hit", "ada@example.com"),
    ])
    r = await resolve_contact(
        "Example", "https://example.com/about", "Ada Lovelace",
        finder=chain, verifier=None,
    )
    check("end-to-end failover resolves", r.found and r.email == "ada@example.com")
    check("end-to-end failover attributes apollo", r.source == "apollo", r.source)


async def main() -> int:
    for fn in [
        test_quota_failover,
        test_healthy_prospeo_never_touches_apollo,
        test_no_match_fallthrough_toggle,
        test_all_no_match_is_a_miss_not_an_outage,
        test_all_unavailable_raises,
        test_miss_outranks_outage,
        test_disabled_tier_costs_no_call,
        test_resolve_core_unchanged_without_apollo,
        test_resolve_core_reasons,
        test_apollo_failover_end_to_end,
    ]:
        await fn()

    failed = 0
    for status, name, detail in _results:
        if status == FAIL:
            failed += 1
        print(f"  [{status}] {name}{f'  -- {detail}' if detail else ''}")
    print(f"\n{len(_results) - failed}/{len(_results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
