# enrichment-mcp

A depth-first lead finder for a pentest / bug-bounty offering. Claude drives
discovery and qualification in-session using its own web tools; a thin
[FastMCP](https://gofastmcp.com) server handles the two things the chat sandbox
cannot: paid contact resolution via Prospeo and a durable lead database that
remembers state across sessions. The deliverable is a stored, qualified lead
carrying lean context -- enough to recognise the company, one verified contact,
and a one-line "why". **The system never contacts prospects and never triggers
any security test. All autonomous writes are internal CRM state only.**

---

## Architecture

```
  Claude session (lead-finder skill)
    web_search / web_fetch  -- discovery + qualification + NO_MATCH fallback mining
        |  tool calls over HTTPS (bearer)
        v
  https://enrichment-mcp.frogbytes.xyz/mcp   (Cloudflare Tunnel, auto-HTTPS)
        |
  Incus instance (10.42.0.x:8000) on the Mac mini
    FastMCP server  src/mcp_server/
      server.py            FastMCP app, bearer auth, run(transport=http)
      config.py            dataclass + dotenv
      db/   pool.py        asyncpg pool  <- SUPABASE_DB_URL
            leads.py       add/list/get/update_status/get_uncontacted
            usage.py       prospeo_usage logging
      contacts/ prospeo.py ProspeoFinder (multi-key pool, enrich-person)
                verifier.py MyEmailVerifierClient
                resolve.py  resolve_contact logic (Prospeo + verify, no Gemini)
                helpers.py  split_name / extract_domain
      tools/ leads.py      @mcp.tool wrappers -> db.leads
             resolve.py    @mcp.tool resolve_contact, verify_email
        |
        v
  Supabase Postgres (leads + prospeo_usage)        Prospeo enrich-person (X-KEY pool)
                                                   MyEmailVerifier validate_single
```

**Data-flow invariant:** web tools run in the session; Prospeo and state run on
the server. The server holds no loop, no scheduler, no autonomous discovery.

---

## Local Setup

**Requirements:** Python 3.10+, access to a Supabase Postgres instance.

```sh
# 1. Create venv and install dependencies
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and fill in the 7 required vars (see .env.example for the full list)

# 3. Apply the database schema
#    SUPABASE_DB_URL must be set in .env before this step.
psql "$SUPABASE_DB_URL" -f schema/001_leads.sql

# 4. Run the server
python -m src.mcp_server
# Binds to MCP_HOST:MCP_PORT (default 0.0.0.0:8000).
# MCP endpoint: http://localhost:8000/mcp
```

**Environment variables** (see `.env.example` for the authoritative list):

| Variable | Purpose |
|---|---|
| `SUPABASE_DB_URL` | Full `postgres://...` DSN to Supabase |
| `PROSPEO_API_KEYS` | Comma-separated Prospeo API keys |
| `PROSPEO_ENRICH_MOBILE` | `0` = email-only (1 credit); `1` = includes mobile (10 credits) |
| `MYEMAILVERIFIER_API_KEY` | MyEmailVerifier key (fallback path) |
| `MCP_BEARER_TOKEN` | Static bearer token; used in `claude mcp add --header` |
| `MCP_HOST` | Bind address (default `0.0.0.0`) |
| `MCP_PORT` | Bind port (default `8000`) |

---

## Hosting

The server runs inside a dedicated **Incus** instance on the Mac mini and is
exposed via the existing Cloudflare named tunnel (outbound-only, auto-HTTPS, no
inbound ports required).

See `deploy/` for the artifacts:

- `deploy/enrichment-mcp.service` -- systemd unit that runs inside the instance.
- `deploy/setup-incus.sh` -- commented provisioning runbook; read before executing.

One-liner to publish after the instance is up:

```sh
cf-publish enrichment-mcp http://<instance-ip>:8000
# Exposes: https://enrichment-mcp.frogbytes.xyz/mcp
```

**Host-header caveat:** Cloudflare forwards requests with `Host:
enrichment-mcp.frogbytes.xyz`. If the ASGI server responds with 421
Misdirected Request, set `httpHostHeader: enrichment-mcp.frogbytes.xyz` in
the tunnel ingress config (see `deploy/setup-incus.sh` step 9).

---

## Connecting Claude

**Claude Code (default path -- static bearer):**

```sh
claude mcp add --transport http enrichment-mcp \
  https://enrichment-mcp.frogbytes.xyz/mcp \
  --header "Authorization: Bearer <MCP_BEARER_TOKEN>"
```

Replace `<MCP_BEARER_TOKEN>` with the value from your `.env`.

**claude.ai web connector:** requires OAuth (no static-bearer field). Switch to
FastMCP `OIDCProxy` + a hosted IdP if the web app is required; the bearer layer
is designed as a pluggable swap.

---

## Tools

Seven tools, grouped by concern:

**Lead store (CRM / state)**

| Tool | Purpose |
|---|---|
| `add_qualified_lead` | Upsert a qualified lead; domain is the PK |
| `list_leads` | List leads, optionally filtered by status |
| `get_lead` | Fetch a single lead by domain |
| `update_lead_status` | Advance the status enum for a domain |
| `get_uncontacted` | Return leads at `qualified` or `contact_resolved` status |

**Contact resolution**

| Tool | Purpose |
|---|---|
| `resolve_contact` | Run Prospeo `enrich-person` for a Claude-named decision-maker |
| `verify_email` | Verify a guessed email via MyEmailVerifier (NO_MATCH fallback) |

Status enum: `qualified` -> `contact_resolved` -> `contacted` -> `replied` ->
`closed` / `rejected`.

---

## Scope / Non-Goals

The server finds, qualifies, and tracks leads. It does not:

- Send email or contact any prospect (no outreach tool, no SMTP).
- Run or trigger security tests.
- Provide a web dashboard (query leads through Claude).
- Use Gemini, Google CSE, SearXNG, or any other discovery API.
- Run an always-on autonomous loop.
