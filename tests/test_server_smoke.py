"""No-regression smoke test for the server as a whole.

Asserts the guarantees the Apollo change had to preserve: the app still builds
with the same seven tools, construction still touches no network or database,
config still loads with Apollo absent, and the tool docstrings the session
reads still describe the reasons the tools actually return.

Run: python -m tests.test_server_smoke   (no network, no DB, no keys)
"""

from __future__ import annotations

import asyncio
import os
import sys

EXPECTED_TOOLS = {
    "add_qualified_lead", "list_leads", "get_lead", "update_lead_status",
    "get_uncontacted", "resolve_contact", "verify_email",
}

_results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((ok, name, detail))


async def main() -> int:
    # Import must not open a socket or a pool. Building the app at import time
    # is a documented property of server.py; breaking it would make the module
    # unimportable anywhere without live credentials.
    from src.mcp_server.server import build_server, mcp

    tools = {t.name for t in await mcp.list_tools()}
    check("seven tools still registered", tools == EXPECTED_TOOLS,
          str(sorted(tools ^ EXPECTED_TOOLS)) if tools != EXPECTED_TOOLS else "")
    check("build_server is repeatable", isinstance(build_server(), type(mcp)))

    from src.mcp_server.config import Config, _load_config

    cfg = Config()
    check("apollo defaults to empty", cfg.apollo_api_keys == [])
    check("no_match fallback defaults on", cfg.contact_fallback_on_no_match is True)

    os.environ["APOLLO_API_KEYS"] = " k1 , k2 ,, "
    os.environ["CONTACT_FALLBACK_ON_NO_MATCH"] = "false"
    loaded = _load_config()
    check("apollo keys split and stripped", loaded.apollo_api_keys == ["k1", "k2"],
          str(loaded.apollo_api_keys))
    check("fallback toggle honoured", loaded.contact_fallback_on_no_match is False)
    del os.environ["APOLLO_API_KEYS"], os.environ["CONTACT_FALLBACK_ON_NO_MATCH"]
    check("fallback defaults on when unset",
          _load_config().contact_fallback_on_no_match is True)

    # The docstring is the session's contract: every reason the tool can return
    # must be named in it, and reasons it can no longer return must be gone.
    from src.mcp_server.tools.resolve import resolve_contact as tool
    doc = tool.__doc__ or ""
    for reason in ("no_match", "no_email", "email_unverified",
                   "insufficient_input", "provider_unavailable"):
        check(f"docstring documents {reason}", reason in doc)
    check("stale prospeo_unavailable reason removed", "prospeo_unavailable" not in doc)

    # Back-compat: the old result name must still import.
    from src.mcp_server.contacts import EnrichmentResult, ProspeoResult
    check("ProspeoResult still importable", ProspeoResult is EnrichmentResult)

    failed = sum(1 for ok, _, _ in _results if not ok)
    for ok, name, detail in _results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
              f"{f'  -- {detail}' if detail else ''}")
    print(f"\n{len(_results) - failed}/{len(_results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
