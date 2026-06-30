"""The seven MCP tools (T10): five lead-store CRUD/query + two resolution.

State / CRM: ``add_qualified_lead``, ``list_leads``, ``get_lead``,
``update_lead_status``, ``get_uncontacted``.
Resolution: ``resolve_contact``, ``verify_email``.

There is intentionally no messaging, dispatch, or scan-launch tool -- the
system finds, qualifies, and tracks only (the product invariant).
"""

from __future__ import annotations

from fastmcp import FastMCP

from .leads import register_lead_tools
from .resolve import register_resolve_tools


def register_tools(mcp: FastMCP) -> None:
    """Register all seven tools on ``mcp`` (five lead-store + two resolution)."""
    register_lead_tools(mcp)
    register_resolve_tools(mcp)


__all__ = ["register_tools", "register_lead_tools", "register_resolve_tools"]
