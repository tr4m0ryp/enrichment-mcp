# enrichment-mcp: Depth-First Lead Discovery for a Bug-Bounty Offering

## Project Overview

Selling a penetration-testing / bug-bounty service is a **high-consideration, low-volume** sale. Spraying hundreds of generic emails is the wrong shape for it -- the win is a few *right* companies, each reached through the *right* person, not a big funnel of weak contacts. Most lead-gen tooling optimises for the opposite: discover everything, enrich everything, auto-send. That produces volume and burns goodwill.

**enrichment-mcp** inverts that. It is a depth-first lead finder: per run it surfaces a *handful* of candidate webshops, qualifies them hard, and for each keeper resolves the **single best decision-maker**. The deliverable stops at a stored, qualified lead carrying **lean context** -- enough to recognise the company, one verified contact, and a one-line "why". A human decides what to do next; the system never reaches out and never tests anything.

The design splits cleanly across two execution contexts. **Claude** (in claude.ai or Claude Code) runs discovery and qualification *in-session* using its own `web_search` / `web_fetch` -- no third-party search API, no LLM key pool. A thin **[FastMCP](https://gofastmcp.com) server** does only the two things the chat sandbox cannot: paid contact resolution through **Prospeo** (an outbound API the sandbox blocks) and a **durable lead store** that remembers state across sessions. This is a ground-up rebuild of an older volume-funnel pipeline (`clay-enrichment`); roughly 5,000 lines of key-pool and worker machinery were dropped, four assets salvaged.

## How It Works

For each run, Claude drives the loop and calls the server only when it must:

```
  Claude session  (lead-finder skill)
    web_search / web_fetch  ── discovery, hard qualification, NO_MATCH fallback mining
        │  tool calls over HTTPS (static bearer)
        ▼
  https://enrichment-mcp-<num>.<region>.run.app/mcp     (Cloud Run — auto-HTTPS, scales to zero)
        │
  Cloud Run container (GCP) — env from Secret Manager
    FastMCP server  ── 7 tools, bearer auth, Streamable HTTP at /mcp
        │
        ▼
  Supabase Postgres            Prospeo enrich-person        MyEmailVerifier
  (leads + prospeo_usage)      (X-KEY multi-key pool)       (validate_single)
```

The qualification loop is deliberately **discard-heavy**:

1. **Discover** -- run one to three angles via `web_search` to surface a handful of candidates (not a funnel).
2. **Qualify hard** -- `web_fetch` each site and score it 0-10 against the ICP: is it a **custom (non-platform)** webshop, is it **receptive** (no existing public bounty program), is there a **reachable** technical decision-maker, can it **plausibly pay**.
3. **Keep only winners** -- discard anything under the `>=7` gate immediately and explicitly. Quality over count.
4. **Resolve one contact** -- name the single best decision-maker, then call `resolve_contact`; the server runs the Prospeo pool and returns one verified email + LinkedIn + title.
5. **Fallback on miss** -- on Prospeo `NO_MATCH`, mine the site's team/about pages in-session, guess the email pattern, and confirm with `verify_email`; accept only a `Valid` result.
6. **Store lean** -- write the lead via `add_qualified_lead`. If no contact resolves, the company is still stored (flagged), never thrown away.

**Data-flow invariant:** web tools run in the session; Prospeo and state run on the server. The server holds **no loop, no scheduler, no autonomous discovery** -- it only acts when Claude calls a tool.

## Targeting Scope

| Dimension | In scope | Out of scope |
|---|---|---|
| **Stack** | Custom / bespoke webshops (own checkout, APIs, accounts) | Templated SaaS stores whose security is the platform's problem |
| **Size** | Mid-market: big enough to pay a bounty | Large enterprises with in-house security teams |
| **Security posture** | No existing public bounty program; signs of receptiveness | Companies already on HackerOne / Bugcrowd / Intigriti |
| **Contact** | One reachable decision-maker (CTO / lead dev / founder) | Bulk people enumeration; every employee |

The qualification rubric scores five criteria 0-2 each (**custom-stack confidence**, **receptiveness**, **attack surface**, **ability to pay**, **reachable decision-maker**) and sums to a 0-10 `bounty_fit_score`. The keep-gate is `>=7` **and** custom-stack `>=1` **and** receptiveness `>=1`, so a clear platform store or an existing bounty program is an automatic discard regardless of total.

## Quick Start

**Requirements:** Python 3.10+ and a Postgres instance (the design targets Supabase; any Postgres works).

<details>
<summary>macOS / Linux</summary>

```bash
# 1. Create a virtualenv and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and fill in the values (see the table below)

# 3. Apply the database schema (SUPABASE_DB_URL must be set)
psql "$SUPABASE_DB_URL" -f schema/001_leads.sql

# 4. Run the server
.venv/bin/python -m src.mcp_server
# Serves Streamable HTTP at http://MCP_HOST:MCP_PORT/mcp (default 0.0.0.0:8000)
```
</details>

**Environment variables** (`.env.example` is the authoritative list):

| Variable | Purpose |
|---|---|
| `SUPABASE_DB_URL` | Full Postgres DSN to the lead store (**required**) |
| `PROSPEO_API_KEYS` | Comma-separated Prospeo keys (free-tier pool, rotated round-robin) |
| `PROSPEO_ENRICH_MOBILE` | `false` = email-only (1 credit); `true` = include mobile (10 credits) |
| `MYEMAILVERIFIER_API_KEY` | MyEmailVerifier key for the guess-and-verify fallback |
| `MCP_BEARER_TOKEN` | Static bearer the server requires on every request |
| `MCP_HOST` / `MCP_PORT` | Bind address / port (default `0.0.0.0` / `8000`) |

## Usage

### Connecting Claude

**Claude Code (default path -- static bearer):**

```bash
claude mcp add --transport http enrichment-mcp \
  https://enrichment-mcp-<num>.<region>.run.app/mcp \
  --header "Authorization: Bearer <MCP_BEARER_TOKEN>"
```

Use the live Cloud Run service URL (printed by the deploy) with `/mcp` appended, and the `MCP_BEARER_TOKEN` from Secret Manager.

**claude.ai web connector (OAuth).** The web app cannot send a bearer header, so it uses OAuth. The server supports it via `MCP_OAUTH_PROVIDER` (see `auth.py`):

- `workos` (**recommended**) -- WorkOS AuthKit, which supports Dynamic Client Registration natively, so the server holds no client secret. Set `MCP_OAUTH_PROVIDER=workos`, `WORKOS_AUTHKIT_DOMAIN=https://<name>.authkit.app`, and `MCP_BASE_URL=<the public run.app URL>`, then redeploy. Enable DCR for the AuthKit instance in the WorkOS dashboard. The server returns 401 with an RFC 9728 `resource_metadata` pointer to AuthKit, and claude.ai (Settings -> Connectors -> Add custom connector -> paste `<base>/mcp`) drives the login.
- `oidc` -- any OIDC provider (Descope, Auth0, Google, ...) via `OIDCProxy`: set `MCP_OIDC_CONFIG_URL`, `MCP_OIDC_CLIENT_ID` (+ secret), and `MCP_BASE_URL`.
- `supabase` -- reuse the project's own Supabase Auth, but only if that project advertises an OAuth registration endpoint (many do not -- prefer `workos`).

Switching modes is pure config -- no code change. Bearer mode (empty `MCP_OAUTH_PROVIDER`) stays available for Claude Code.

### Running a lead hunt

The `skills/lead-finder/` skill drives the depth-first workflow end-to-end. In a Claude session with the connector attached, give it a brief ("independent EU streetwear shops on custom stacks") and it runs discovery, qualifies, resolves contacts, and stores keepers -- calling the tools below. Across sessions, `get_uncontacted` is the durable memory of who is qualified but not yet acted on.

### Tools

**Lead store (CRM / state)**

| Tool | Purpose |
|---|---|
| `add_qualified_lead` | Upsert a qualified lead; `domain` is the primary key. Status never regresses on re-upsert. |
| `list_leads` | List leads, optionally filtered by `status` / `min_score`. |
| `get_lead` | Fetch one lead by domain. |
| `update_lead_status` | Advance the status enum for a domain (validated). |
| `get_uncontacted` | Leads at `qualified` or `contact_resolved` -- the cross-session backlog. |

**Contact resolution (server-side network)**

| Tool | Purpose |
|---|---|
| `resolve_contact` | Run the Prospeo `enrich-person` pool for a Claude-named person; returns one verified contact or `found:false`. Write-free. |
| `verify_email` | Verify a guessed address via MyEmailVerifier; the fallback accepts only `Valid`. |

Status flow: `qualified --> contact_resolved --> contacted --> replied --> closed / rejected`.

## Technical Details

### Module breakdown

| Path | Responsibility |
|---|---|
| `src/mcp_server/server.py` | FastMCP app, pluggable bearer auth (`_build_auth`), `run()` over Streamable HTTP |
| `src/mcp_server/config.py` | Typed config -- plain `@dataclass` + `python-dotenv`, no pydantic |
| `src/mcp_server/db/pool.py` | asyncpg pool built from `SUPABASE_DB_URL` |
| `src/mcp_server/db/leads.py` | The five lead-store operations (parametrized, dict returns) |
| `src/mcp_server/contacts/prospeo.py` + `prospeo_pool.py` | Multi-key Prospeo `enrich-person` client with round-robin rotation |
| `src/mcp_server/contacts/verifier.py` | MyEmailVerifier client (inlined `VerifyResult`) |
| `src/mcp_server/contacts/resolve.py` | Write-free `resolve_contact` core: Prospeo primary -> verify |
| `src/mcp_server/tools/` | `@mcp.tool` wrappers over the db and contacts layers |
| `skills/lead-finder/` | The Claude-side skill: `SKILL.md` + `references/icp.md` + `references/angles.md` |

### The lead record (intentionally lean)

One `leads` table, keyed on `domain`:

| Column | Notes |
|---|---|
| `domain` | Primary key |
| `company_name`, `summary`, `location` | Enough to **recognise** the lead |
| `webshop_platform` | `custom` / `shopify` / `woocommerce` / `unknown` (judged by Claude) |
| `bounty_fit_score` | The 0-10 qualification score |
| `why` | One-line rationale (receptiveness evidence folded in) |
| `status` | The funnel enum above |
| `contact_name/role/email/linkedin/email_verified` | The one best contact -- all nullable |
| `created_at`, `updated_at` | `updated_at` maintained by trigger |

A second table, `prospeo_usage`, meters credit burn across the key pool.

### Credit model

| Call | Cost on hit | Cost on miss |
|---|---|---|
| Prospeo `enrich-person` (email) | **1 credit** | NO_MATCH is **free** |
| Prospeo `enrich-person` (mobile) | 10 credits | free |
| Prospeo duplicate within ~90 days | free | -- |
| MyEmailVerifier `validate_single` | 1 credit | 1 credit (still returns a status) |

Depth-first targeting keeps these low by design -- one resolution per kept lead, not per candidate.

### Hosting

The server runs on **Google Cloud Run** as a container: automatic HTTPS, a public `*.run.app` URL, and scale-to-zero (no cost when idle). Secrets live in **Secret Manager** and are injected as env vars; the app-layer bearer is what actually protects the public endpoint (`--allow-unauthenticated` at the IAM layer so claude.ai, which carries no Google identity, can reach it).

`deploy/deploy-cloudrun.sh` is the reproducible runbook (project, APIs, secrets, deploy). The `Dockerfile` builds the image; Cloud Run injects `$PORT`, which `config.py` honors. One-liner to redeploy after a code change:

```bash
gcloud run deploy enrichment-mcp --source . --region <region> \
  --allow-unauthenticated --max-instances 1 \
  --set-secrets=MCP_BEARER_TOKEN=MCP_BEARER_TOKEN:latest,SUPABASE_DB_URL=SUPABASE_DB_URL:latest,PROSPEO_API_KEYS=PROSPEO_API_KEYS:latest,MYEMAILVERIFIER_API_KEY=MYEMAILVERIFIER_API_KEY:latest
```

Cloud Run pins secret versions per revision, so after updating a secret value, redeploy (or roll a new revision) to pick it up.

## Roadmap

- **Platform fingerprint tool** -- an optional server-side check (`cdn.shopify.com`, `/wp-content/`, platform headers) if Claude's page-judgment of custom-vs-platform proves unreliable. Deliberately deferred; Claude judges from the page for now.
- **OAuth path for the claude.ai web connector** -- FastMCP `OIDCProxy` + a hosted IdP, swappable into the existing auth layer.
- **`domain-search` assist** -- fall back to Prospeo's domain search when naming the decision-maker is hard (currently out of scope to preserve the one-best principle).

## Disclaimer

This is a **sales-qualification** tool, not a reconnaissance or testing tool. It discovers publicly listed companies, judges their fit for a security-research engagement, and identifies one business contact for a human to approach. It **does not contact prospects, does not send email, and does not run or trigger any security test** -- those remain separate, human-gated actions. Process contact data in line with GDPR and applicable anti-spam rules, and only pursue testing against a target with explicit written authorization. Built for the author's own bug-bounty offering; not licensed for external distribution.
