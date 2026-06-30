"""enrichment_mcp -- depth-first lead-finder MCP server.

A small FastMCP server exposing seven tools over one Supabase ``leads`` table
plus Prospeo contact resolution. The Claude session does discovery and hard
qualification; this server owns Prospeo enrichment and the durable lead store.
It never contacts a lead and never runs a test.
"""

__version__ = "0.1.0"
