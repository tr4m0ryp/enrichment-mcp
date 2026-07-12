# enrichment_mcp -- Project Instructions

Depth-first lead finder for a pentest / bug-bounty offering. A Claude session
drives discovery and hard qualification with its own web tools; this repo is a
small **FastMCP server** that owns Prospeo contact resolution and a durable
`leads` store in Supabase Postgres.

## Invariant (do not break)
The system **finds, qualifies, and tracks only**. It never contacts a lead and
never runs a test. There is no send / outreach / pentest-trigger tool -- if a
task asks for one, it is out of scope.

## Architecture
- **Session (the lead-finder skill):** runs 1-3 discovery angles, qualifies
  against the pentest/bounty ICP (custom-built **B2B / high-blast-radius
  commerce**, EU-wide, small-to-mid-market, unwatched -- NOT low-stakes B2C
  consumer-hobby shops), keeps only score >= 7, names the one decision-maker.
  The operational copy of the skill is in the `pentest-pipeline` repo; the copy
  under `skills/` here is the reference pairing -- keep them in sync.
- **Server (this repo):** `resolve_contact` (Prospeo enrich-person pool) +
  `verify_email` (MyEmailVerifier fallback) + five CRUD/query tools over the
  `leads` table. Streamable HTTP at `/mcp`, static bearer auth.
- Seven tools total: `add_qualified_lead`, `list_leads`, `get_lead`,
  `update_lead_status`, `get_uncontacted`, `resolve_contact`, `verify_email`.
- **Project partition (shared store).** The `leads` table is shared by more than
  one outreach pipeline (pentest / bug-bounty and the Avelero licensing pipeline).
  Every row has a `project` tag (`pentest` | `avelero`); the five lead-store tools
  are scoped to it -- reads filter by it, writes stamp it, a domain owned by one
  project can't be taken by the other. Scope = the `LEADS_PROJECT` env default
  (`pentest`), overridable per call via the `project` argument. Run one instance
  per project (each with its own `LEADS_PROJECT`), OR share one instance and pass
  `project` per call. `list_leads` / `get_uncontacted` return a COMPACT projection
  (scan fields + truncated summary) to stay under the MCP output cap; `get_lead`
  is the full row. Schema: `schema/004_project_partition.sql`.

## Layout
`src/mcp_server/`: `config.py` (dataclass + dotenv), `db/` (asyncpg pool + lead
store), `contacts/` (Prospeo + verifier), `tools/` (@mcp.tool wrappers),
`server.py` (FastMCP app). Each file < 300 lines, re-exported from its package
root.

## Stack
Python 3.10+, `fastmcp` (>=3.4,<4), `asyncpg`, `aiohttp`, `python-dotenv`.
Config is a plain `@dataclass` + `os.environ` -- **no pydantic**. No Gemini,
Google, SMTP, Notion, or dashboard.

## Run
```
pip install -r requirements.txt
python -m src.mcp_server        # serves HTTP on MCP_HOST:MCP_PORT at /mcp
```

## Environment (.env -- see .env.example)
- `SUPABASE_DB_URL` -- full Postgres DSN for the lead store (required)
- `PROSPEO_API_KEYS` -- comma-separated enrich-person keys
- `PROSPEO_ENRICH_MOBILE` -- pull mobile numbers (10x credits); default false
- `MYEMAILVERIFIER_API_KEY` -- verifier key for the fallback path
- `MCP_BEARER_TOKEN` -- static bearer the server enforces
- `LEADS_PROJECT` -- lead partition this instance serves (`pentest` | `avelero`);
  default `pentest`. Sets the default `project` for every lead-store tool call.
- `MCP_HOST` / `MCP_PORT` -- bind address; default `0.0.0.0:8000`

## Reference
`clay-enrichment/` is the previous Gemini pipeline, kept locally as a READ-ONLY
salvage source and gitignored. Do not import from it or recreate it.
