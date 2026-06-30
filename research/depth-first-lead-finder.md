# Depth-First Lead Finder -- Technical Design
# Started: 2026-06-30
# Source vision: notes/depth-first-lead-finder.md

## Brief
<!-- filled at wrap-up -->
Refactor `clay-enrichment` (Gemini-driven bulk-outreach pipeline) into a small,
depth-first lead collector for a pentest/bug-bounty offering. Claude drives discovery
+ qualification in-session; a thin MCP server owns Prospeo contact resolution and a
durable lead store. Deliverable stops at a stored, qualified lead with lean context
(recognize-it + one contact + one-line why). No mail pipeline, no outreach, no
dashboard. This doc resolves the parked questions: Prospeo fallback, state store,
resolve_contact selection + credit metering, MCP hosting + auth, simplified schema +
migration, post-Prospeo verifier, deferred fingerprint tool.

## Recommended Technical Design

Build a **new, small Python repo** (`enrichment_mcp`) that is a **FastMCP server** plus
a **lead-finder skill** -- not a port of the old pipeline. The old clay system is a
reference only; we salvage four files and rebuild the rest.

**The server** (`fastmcp` 3.4.2, Streamable HTTP at `/mcp`) exposes **7 tools** over a
**single `leads` table** in the existing Supabase Postgres (reached by `asyncpg` via the
`SUPABASE_DB_URL` DSN -- no new DB on the constrained Mac mini). Five tools are CRUD/query
over the lead store; one (`resolve_contact`) runs the salvaged multi-key **Prospeo**
`enrich-person` pool server-side to verify the email of a Claude-named decision-maker;
one (`verify_email`) wraps **MyEmailVerifier** for the fallback path. **No mcpo, no
Gemini, no Google, no SMTP, no dashboard.**

**The skill** drives everything in the Claude session: it runs 1-3 discovery angles with
the session's own `web_search`/`web_fetch`, qualifies hard against the rewritten
pentest/bounty ICP, keeps only score >= 7, then calls `resolve_contact` for the one best
contact and `add_qualified_lead` to store a **lean** record (recognize-it + one contact +
one-line why). On a Prospeo `NO_MATCH`, the skill mines the site in-session, guesses the
email pattern, and confirms it with `verify_email` -- accepting only `Valid`.

**Hosting:** run the server in a small **Incus instance** on the Mac mini, then
`cf-publish enrichment-mcp http://10.42.0.x:8000` to expose
`https://enrichment-mcp.frogbytes.xyz/mcp` with auto-HTTPS and no open ports. Auth is a
**static app-layer bearer** added via `claude mcp add --transport http ... --header`;
OAuth is a documented config-swap if the claude.ai web connector is needed.

The data flow holds the vision's invariant: **web tools run in the session; Prospeo +
state run on the server; the system never contacts and never tests.**

## Decisions

### T1: Prospeo NO_MATCH fallback -- Claude in-session guess + verify_email; drop Gemini
**Decision:** Remove the Gemini-grounded finder entirely. Primary resolution is Prospeo
`enrich-person` on a Claude-named person. On `NO_MATCH` (free, HTTP 400), the skill mines
/team,/about,/contact + LinkedIn in-session, infers the email pattern, and calls a
server-side `verify_email` tool; only a `Valid` MyEmailVerifier result is accepted,
Catch-all/Unknown are treated as unconfirmed.
**Why:** Removes the last Gemini dependency and the ~4,900-line key-pool that fed it (F5);
the guess+verify path is a fine free last-resort at ~20-50% yield (F8). Verification, not
guessing, is where reliability comes from -- so the verifier stays.
**Alternatives rejected:** Keep a minimal single-key Gemini grounded fallback -- keeps a
whole SDK + a paid key + the `gemini_finder_usage` table for marginal lift over
guess+verify. `domain-search` as the blind fallback -- returns multi/generic contacts,
against the one-best principle (F7).
**Confidence:** high.

### T2: State store -- reuse the existing Supabase Postgres via asyncpg, fresh schema
**Decision:** Keep `asyncpg` against `SUPABASE_DB_URL`; lift the pool out of the
to-delete `src/api_keys/supabase_client.py` into `mcp_server/db/pool.py`. Create one new
`leads` table in the same Supabase project; do NOT migrate old rows.
**Why:** The DB is already cloud-durable and reachable by DSN (F6), the Mac mini has only
4 GB RAM and no local Postgres (F9), and asyncpg reuse keeps the Prospeo usage-logging and
resolution core intact (F1, F3). The old rows are the wrong ICP (Avelero/DPP), so a fresh
empty table is correct, not a backfill.
**Alternatives rejected:** Local SQLite -- lighter infra but forfeits asyncpg reuse and
off-box durability; logged as an override. Stand up Postgres on the Mac mini -- memory
pressure for no gain over the existing cloud DB.
**Confidence:** high.

### T3: resolve_contact -- Claude names the decision-maker; server verifies one person
**Decision:** `resolve_contact(company_name, domain, person_name, role?)`. The server
`split_name`s the Claude-supplied person, runs the multi-key Prospeo `enrich-person` pool
with `only_verified_email` semantics, and returns ONE contact (email, linkedin, title,
verified) or a not-found signal. It is read-only w.r.t. `leads` (writes only the
credit-usage row); Claude then stores via `add_qualified_lead`/`update_lead_status`.
**Why:** `enrich-person` enriches a known person, not a blind domain (F1, F7); depth-first
already has Claude identify the single decision-maker during qualification, so naming the
person in-session replaces the old LLM "recall decision-makers" prompt + seniority gate
(F3). Keeping the tool write-free makes it idempotent and composable.
**Alternatives rejected:** Have the server discover the decision-maker (re-introduces an
LLM/discovery dependency the vision moved into the session). resolve_contact auto-writing
the lead (couples resolution to storage; harder to re-run).
**Confidence:** high.

### T4: Credit metering -- keep the prospeo_usage table and the finder's logging
**Decision:** Keep the existing `prospeo_usage` table and pass the asyncpg pool to
`ProspeoFinder` as its `usage_pool`, so every call logs `(key_prefix, credits, domain,
free_dedup)`. Expose a small `prospeo_credits` read via `list_leads`-style query if
needed; otherwise it's queryable directly.
**Why:** The finder already writes it when given a pool (F1); credit visibility matters
for a paid multi-key free-tier pool. Near-zero cost to keep.
**Alternatives rejected:** Drop usage logging (loses the only view into credit burn).
**Confidence:** high.

### T5: MCP hosting + transport -- FastMCP Streamable HTTP, no mcpo, Incus + cf-publish
**Decision:** `fastmcp` 3.4.2 serving `transport="http"` at `/mcp`. Run it in a dedicated
Incus instance on the Mac mini bound to `0.0.0.0:8000`; publish with
`cf-publish enrichment-mcp http://10.42.0.x:8000` -> `https://enrichment-mcp.frogbytes.xyz`.
A systemd unit inside the instance keeps it alive. mcpo is NOT used.
**Why:** FastMCP serves the MCP protocol over HTTP natively; mcpo emits REST/OpenAPI that
an MCP client cannot consume, and isn't installed anyway (F9, R5/R6). cf-publish is the
established one-command tunnel recipe on this host (F9), giving auto-HTTPS and no inbound
ports.
**Alternatives rejected:** mcpo in front (wrong protocol for claude.ai). Anthropic's new
"MCP tunnels" preview (promising, but cf-publish is already wired and proven here).
Quick/throwaway tunnel (no stable hostname).
**Confidence:** high.

### T6: Auth -- static app-layer bearer (Claude Code path), pluggable to OAuth
**Decision:** Enforce a static bearer (`MCP_BEARER_TOKEN`) in the server via FastMCP's
token verification; connect with
`claude mcp add --transport http enrichment-mcp https://enrichment-mcp.frogbytes.xyz/mcp
--header "Authorization: Bearer <token>"`. Structure the auth as one pluggable layer so
swapping to FastMCP `OIDCProxy` + a hosted IdP is config, not a rewrite.
**Why:** claude.ai's web connector is OAuth-or-authless (no static-bearer field) and its
OAuth path is currently flaky (R7, R8); the Claude Code CLI accepts a static bearer and is
the most reliable path for a personal tool. A bearer check is ~5 lines vs a ~300-line
OAuth/DCR/PKCE subsystem. The override (OIDCProxy) costs only an IdP signup + config later,
so nothing is wasted.
**Alternatives rejected:** OAuth now via OIDCProxy (premature; flaky web path). Authless +
Cloudflare IP-allowlist to `160.79.104.0/21` (blocks the Claude Code CLI, which connects
from your IP). Cloudflare Access service tokens (claude.ai can't inject `CF-Access-*`
headers). **This is the one preference call flagged in "Decisions Made For You."**
**Confidence:** medium (depends on whether the claude.ai *web* app is a hard requirement).

### T7: Simplified schema -- one lean `leads` table + the kept `prospeo_usage`
**Decision:** A single `leads` table keyed on `domain` (PK): `company_name`, `summary`
(what they sell, for recognition), `location`, `webshop_platform`
(custom/shopify/woocommerce/unknown), `bounty_fit_score` SMALLINT, `why` (one-line
rationale, receptiveness folded in), `status`, the one contact
(`contact_name/role/email/linkedin/email_verified`, all nullable per C8), `created_at`,
`updated_at` (trigger). Status CHECK enum: `qualified -> contact_resolved -> contacted ->
replied -> closed/rejected`. Keep `prospeo_usage`. Drop every other old table.
**Why:** Matches the lean-context decision exactly (C7): recognize-it + one contact +
one-line why, nothing more (F4). The `postgres` DSN role bypasses RLS, so no RLS/grant
ceremony is required for the server (F6).
**Alternatives rejected:** Two tables (lead + contact 1:1) -- needless join at this
volume; one row is simpler. Rich schema with evidence trail / attack-surface notes
(rejected by C7).
**Confidence:** high.

### T8: Verifier -- keep MyEmailVerifier, expose as a `verify_email` tool
**Decision:** Port `MyEmailVerifierClient` (`validate_single.php`, `MYEMAILVERIFIER_API_KEY`)
and expose `verify_email(email) -> {status, valid}`. The Prospeo path relies on Prospeo's
own `VERIFIED` status; `verify_email` exists for the in-session guess+verify fallback (T1).
**Why:** Server-side because the paid key must not live in the session and the sandbox
blocks the outbound call. One small tool keeps the fallback honest (accept only `Valid`).
**Alternatives rejected:** Fold verification into `resolve_contact` only (the fallback
needs a standalone verify for Claude-guessed emails). Drop the verifier (the fallback
would deliver unconfirmed guesses).
**Confidence:** high.

### T9: Platform fingerprint -- defer; Claude judges custom-vs-platform from the page
**Decision:** No deterministic fingerprint tool now (honors C2). `webshop_platform` is set
by Claude's judgment and stored as a field. Leave a clearly-scoped hook for a future
optional server tool (`fingerprint_platform(domain)` checking `cdn.shopify.com`,
`/wp-content/`, platform headers) if accuracy disappoints.
**Why:** Vision decision C2; simplest path, usually correct. It needs open-network fetch,
so if added it belongs on the server, not the skill.
**Alternatives rejected:** Build the fingerprint now (premature; C2 deferred it).
**Confidence:** high.

### T10: Tool surface, config, and repo layout
**Decision:** Seven tools: `add_qualified_lead`, `list_leads`, `get_lead`,
`update_lead_status`, `get_uncontacted` (state/CRM) + `resolve_contact`, `verify_email`
(resolution). Config stays a plain `@dataclass` + `python-dotenv` (no pydantic), env:
`SUPABASE_DB_URL`, `PROSPEO_API_KEYS`, `PROSPEO_ENRICH_MOBILE`, `MYEMAILVERIFIER_API_KEY`,
`MCP_BEARER_TOKEN`, `MCP_HOST`, `MCP_PORT`. Repo is a domain-organized tree under
`src/mcp_server/` (db/, contacts/, tools/), each file < 300 lines, re-exported from module
roots, per the user's file-org standard.
**Why:** Matches the vision's named tools and the kept config style (F2); no send/outreach
/pentest-trigger tool, per the invariant.
**Alternatives rejected:** Pydantic-settings (heavier; the dataclass works and matches the
salvaged code). Flat module (violates the file-org standard).
**Confidence:** high.

## Stack & Libraries

| Component | Choice | Call | Licence / health | Notes |
|---|---|---|---|---|
| MCP framework | `fastmcp` 3.4.2 | **Adopt** | Apache-2.0; ~26k stars, weekly releases (R1) | Streamable HTTP at `/mcp`; `@mcp.tool`; built-in token auth |
| Postgres driver | `asyncpg` >=0.29 | **Adopt** | Apache-2.0; mature | Pool from `SUPABASE_DB_URL`; reused from clay |
| HTTP client | `aiohttp` | **Adopt** | Apache-2.0; mature | Prospeo + MyEmailVerifier calls (salvaged) |
| Env loading | `python-dotenv` | **Adopt** | BSD; mature | `.env` -> dataclass config |
| Prospeo client | `prospeo_finder.py` (salvaged) | **Extend** | internal | Drop in unchanged but rewire usage_pool |
| Verifier client | `email_verifier_api.py` (salvaged) | **Extend** | internal | Expose as `verify_email` |
| Resolution core | `_resolve_one` (salvaged) | **Extend** | internal | Strip Gemini + loop -> `resolve_contact` body |

**Dropped deps:** `google-genai`, `notion-client`, `supabase` (py client was Auth/Storage
only), `psycopg2-binary` (the sync prompt-override store is gone), `fastapi` + `uvicorn`
(FastMCP brings its own ASGI server). New `requirements.txt`: `fastmcp`, `asyncpg`,
`aiohttp`, `python-dotenv`.

## Architecture

```
  Claude session (lead-finder skill)
    web_search / web_fetch  -- discovery + hard qualification + NO_MATCH fallback mining
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
                resolve.py  resolve_contact logic (Prospeo + verify, no gemini/loop)
                helpers.py  split_name / extract_domain
      tools/ leads.py      @mcp.tool wrappers -> db.leads
             resolve.py    @mcp.tool resolve_contact, verify_email
        |
        v
  Supabase Postgres  (leads table + prospeo_usage)        Prospeo enrich-person (X-KEY pool)
                                                          MyEmailVerifier validate_single
```

**Key contracts.** Tools return compact JSON and are idempotent: `add_qualified_lead`
upserts on `domain`; `resolve_contact` returns `{email, email_verified, linkedin_url,
job_title}` or `{found:false, reason}` and never writes a lead; `update_lead_status`
validates the status enum. The skill is the only orchestrator -- the server holds no
loop, no scheduler, no autonomous discovery. The single integration point the design
hinges on is **"Claude names the decision-maker -> server verifies the email,"** which is
why `resolve_contact` takes `person_name` rather than discovering it.

## Decisions Made For You (override in /refine)

1. **Auth = static bearer + Claude Code path (T6).** Main alternative: OAuth via FastMCP
   `OIDCProxy` + a hosted IdP (WorkOS AuthKit / Descope). *Change this if you must drive
   the tool from the **claude.ai web app** rather than Claude Code -- the web connector
   has no static-bearer field.* This is the most consequential call in the doc.
2. **State store = reuse Supabase Postgres (T2).** Alternative: local SQLite file in the
   Incus instance. *Change this if you'd rather have zero cloud dependency and don't mind
   rewriting the small DB layer to aiosqlite.*
3. **Single `leads` table, no contact sub-table (T7).** Alternative: `leads` + `contacts`
   1:1. *Change this if you expect to keep multiple contacts per lead later.*
4. **Keep `prospeo_usage` credit metering (T4).** *Drop it if you don't care about
   tracking credit burn across the key pool.*
5. **Hosting in a dedicated Incus instance (T5).** Alternative: run directly on the host or
   in a Docker container. *Change this if you'd rather not spin a per-service instance.*
6. **`verify_email` as a separate tool (T8).** *Fold into resolve_contact if you don't
   want the fallback to be able to verify Claude-guessed addresses independently.*
7. **Fresh empty `leads` table, no backfill (T2).** *Ask for a one-off `leads_full ->
   leads` migration script if you want the old rows despite the ICP mismatch.*

## Key Findings

### F1: The Prospeo finder is a clean, reusable asset (enriches a KNOWN person)
**Finding:** `src/people/prospeo_finder.py` (352 lines) is a self-contained async
multi-key client: `POST https://api.prospeo.io/enrich-person`, `X-KEY` header, body
`{data:{first_name,last_name,company_website}}`. Round-robin key pool with 1h cooldown
on 429/INSUFFICIENT_CREDITS and permanent-dead on INVALID_API_KEY. Returns
`ProspeoResult(email,email_verified,linkedin_url,phone,job_title,raw)` or `None` on
NO_MATCH/INVALID_DATAPOINTS. Keys come from CSV env `PROSPEO_API_KEYS`; mobile gated by
`PROSPEO_ENRICH_MOBILE` (1 credit email-only, 10 with mobile). Optional usage logging
to a `prospeo_usage` table via an asyncpg pool.
**Evidence:** Direct read + Agent A. Deps: `aiohttp`, `asyncpg`.
**Implications:** `enrich-person` enriches a *known* person (needs first+last+domain) --
it does NOT blind-search a domain. So the depth-first flow is: **Claude names the one
decision-maker in-session, the server resolves/verifies that person's email.** The
finder drops into the MCP server almost unchanged; only the DB-pool wiring changes.

### F2: The DB pool is Supabase Postgres, entangled inside the to-delete dir
**Finding:** `src/db/connection.py` is a 14-line re-export of
`src/api_keys/supabase_client.py`, which builds the real `asyncpg` pool from a full DSN
in env `SUPABASE_DB_URL` (min_size=1, max_size=2). `DATABASE_URL` in config is dead.
Config system is plain `@dataclass` + `os.environ` + `python-dotenv` (no pydantic).
**Evidence:** Agent A, Section 7.
**Implications:** The brief says delete `src/api_keys/` entirely -- but the live DB pool
lives there. Migration MUST lift the asyncpg pool into the new module (e.g.
`mcp_server`/`db`) first. The store is already cloud Postgres reachable by DSN, so the
MCP server needs server-side network mainly for Prospeo, not for the DB.

### F3: The reusable resolution core vs the worker-loop wrapper are cleanly separable
**Finding:** In `src/email_resolver/worker.py` (407 lines), `_resolve_one` +
`ResolverResult` + `_verify` are the provider-agnostic resolution unit (Prospeo primary
-> optional verifier -> Gemini-grounded fallback). `_fetch_resolvable_pairs`,
`_persist_resolution`, `email_resolver_worker` are the always-on polling wrapper.
Decision-maker selection today is a binary seniority gate (`title_filter.py`) plus an
LLM "recall named decision-makers" prompt (`DISCOVER_CONTACTS`).
**Evidence:** Agent A, Sections 5-6.
**Implications:** Keep `_resolve_one`'s Prospeo+verify logic as the `resolve_contact`
tool body; drop the loop. The "who is the decision-maker" step moves into the Claude
session (replacing the LLM prompt + seniority gate).

### F4: The old denormalized lead row already matches the target shape
**Finding:** `contact_campaigns` (a denormalized junction) + the `leads_full` view
already carry exactly the fields a lead needs: company_name, website, location,
job_title, email, email_verified, linkedin_url, phone, a fit score, score_reasoning,
context, and a status. The old per-table split (companies / contacts /
contact_campaigns / campaigns / emails / 2 join tables) is what collapses to ONE
`leads` table. Status enum today is `outreach_status` (New -> ... -> Sent -> Replied).
**Evidence:** Agent B, Section 1; `schema/016_leads_full_gemini_status.sql`.
**Implications:** The simplified schema is a single `leads` table whose columns are a
trimmed `leads_full`, with the new status enum (qualified -> contact_resolved ->
contacted -> replied -> closed/rejected). No junctions, no campaigns, no emails table.

### F5: Deletion surface is large and self-contained (~5,170 lines + infra)
**Finding:** `src/api_keys/` (4,871 lines, Gemini-key scraping/pooling) + `src/gemini/`
(298) are the bulk. Plus: the entire `src/discovery/strategies/` 13-strategy apparatus
(~982 lines) + `src/discovery/worker.py`, all 8 always-on workers, `src/email/`
(gen+sender), `src/scoring/`, `src/person_research/`, `src/people/worker.py`, the
supervisor `src/main.py`, `src/utils/backlog.py`, and the GCP/systemd deploy (7
`clay-key-*` timers, `clay-pipeline`, `clay-brief`, `clay-web`, Nginx, SearXNG Docker).
**Evidence:** Agent B, Sections 3-5.
**Implications:** This is a near-total teardown; the new repo is built fresh, salvaging
only the Prospeo finder, helpers, verifier, the `_resolve_one` core, and the (lifted)
asyncpg pool. The old GCP-VM hosting is fully replaced by the Mac-mini MCP host.

### F6: Hosting today is GCP-VM systemd; DB is cloud Supabase reachable by DSN
**Finding:** Runs on a GCP e2-micro VM as systemd services from `/opt/clay-enrichment`.
The DB, however, is Supabase cloud Postgres via `SUPABASE_DB_URL` (a plain DSN), with
RLS + grants on every table. The `postgres` DSN role bypasses RLS.
**Evidence:** Agent B, Section 5; CLAUDE.md.
**Implications:** The DB is reachable from anywhere by DSN, so where the MCP server runs
is driven by Prospeo's network need, not the DB. Reusing Postgres keeps the asyncpg
reuse intact; a fresh minimal schema sidesteps the old RLS/grants ceremony (or adds one
grant). SQLite is the lighter-infra alternative but forfeits the asyncpg code reuse.

### F7: Prospeo API confirmed -- enrich-person is current, NO_MATCH is free
**Finding:** `POST /enrich-person` is the unified current finder; the old
`/email-finder` is deprecated. NO_MATCH returns HTTP 400 + `error_code: NO_MATCH` and is
**not charged**; 1 credit on email hit, 10 with mobile, duplicate within ~90d free.
`only_verified_email: true` debits a credit ONLY when a verified email is returned.
There is also `POST /domain-search` (company domain -> a LIST of people, 1 credit/50,
free if no results or domain already searched) and a LinkedIn finder.
**Evidence:** Agent D, Part A; https://prospeo.io/api-docs/enrich-person.
**Implications:** The existing finder is correct and current -- no rewrite. Depth-first
stays on enrich-person with a Claude-named person. `domain-search` is a possible
"who-works-here" assist but returns generic/multi contacts, against the one-best
principle; keep it out of scope unless naming the DM proves hard.

### F8: Verifier confirmed; in-session guess+verify is a viable NO_MATCH fallback
**Finding:** MyEmailVerifier `GET /api/validate_single.php?apikey=&email=` returns 5
status buckets (Valid/Invalid/Catch-all/Unknown + disposable/role flags), costs 1
credit even on Invalid, 100 free/day. In-session `web_fetch` can mine /team,/about for a
pattern and guess+verify an email at ~20-50% yield -- fine as a free last resort after
Prospeo NO_MATCH, NOT as a primary path; Catch-all/Unknown must be treated as
unconfirmed.
**Evidence:** Agent D, Part A (2,3); https://github.com/pat-myemailverifier/myemailverifier-api.
**Implications:** Drop the Gemini-grounded fallback entirely (removes the last Gemini
dependency). Fallback path = Claude mines the site in-session, guesses a pattern, and
calls a server-side `verify_email` tool; accept only `Valid`. Keep the verifier; the
paid key stays server-side.

### F9: Mac-mini hosting -- Incus + a one-command Cloudflare publish helper; no mcpo
**Finding:** Host `10.0.0.138` (4 GB RAM), user `tr4m0ryp`. Services run in **Incus**
instances on bridge `10.42.0.0/24` (each with its own systemd); a Cloudflare named
tunnel is already live, fronted by domain **frogbytes.xyz**. A helper
`cf-publish <slug> http://<backend:port>` publishes any local HTTP service to
`https://<slug>.frogbytes.xyz` in ~10s (PUTs tunnel ingress + a proxied CNAME).
**mcpo is NOT installed** anywhere -- the brief's "existing mcpo" assumption is wrong.
No local Postgres on the box (the only DB-ish stack is SFTPGo storage).
**Evidence:** Agent D, Part B; `infra/skills/macmini-host/SKILL.md`.
**Implications:** Hosting recipe = run the MCP server in a small Incus instance, then
`cf-publish enrichment-mcp http://10.42.0.x:PORT`. No mcpo layer needed if FastMCP
serves HTTP directly (Agent C confirms). Because cf-publish exposes it publicly,
app-layer auth (bearer token) is required. No local Postgres reinforces reusing the
cloud Supabase DSN over standing up a DB on the constrained box.

## References

### R1: FastMCP (standalone, jlowin)
**Source:** https://pypi.org/project/fastmcp/ , https://gofastmcp.com/deployment/running-server
**Takeaway:** `fastmcp` 3.4.2 (2026-06-06), Python >=3.10, ~26k stars, weekly releases.
`@mcp.tool` decorator; serves Streamable HTTP via `mcp.run(transport="http", host, port)`
at `/mcp`. The actively-maintained successor to the frozen FastMCP 1.0 in the official SDK.

### R2: FastMCP OAuth proxy (the override path)
**Source:** https://gofastmcp.com/servers/auth/oauth-proxy
**Takeaway:** `OIDCProxy` "proxies DCR to work with Claude.ai," the lowest-effort route to a
working claude.ai-web OAuth connector without hand-rolling OAuth 2.1 + DCR + PKCE.

### R3: claude.ai custom connectors + auth
**Source:** https://claude.com/docs/connectors/building , .../authentication , https://support.claude.com/en/articles/11175166
**Takeaway:** Add remote MCP by URL; Streamable HTTP (SSE deprecated). Auth is `none` or
OAuth (`oauth_dcr`/`oauth_cimd`, PKCE S256) -- **no static-bearer field**. Anthropic
connects from cloud IP range `160.79.104.0/21`; server must be public HTTPS.

### R4: Claude Code MCP (the chosen path)
**Source:** https://code.claude.com/docs/en/mcp
**Takeaway:** `claude mcp add --transport http <name> <url> --header "Authorization: Bearer
<token>"` -- the CLI **does** accept a static bearer, unlike the web UI. claude.ai
connectors also auto-appear in Claude Code when logged in.

### R5: mcpo is the wrong layer here
**Source:** https://github.com/open-webui/mcpo , https://docs.openwebui.com/features/extensibility/mcp/
**Takeaway:** mcpo (0.0.20) re-exposes an MCP server as REST/OpenAPI for **non-MCP**
consumers. An MCP client like claude.ai cannot consume its REST output. Unnecessary when
the client speaks MCP -- which FastMCP serves directly.

### R6: Cloudflare Tunnel mechanics + gotchas
**Source:** https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/ , https://zenn.dev/hideakitamai/articles/6747c9bd56bd4f
**Takeaway:** Named tunnel = outbound-only, auto edge-HTTPS, no inbound ports, real custom
hostname required. Watch the `httpHostHeader` -> 421 Misdirected Request gotcha when the
ASGI server validates Host.

### R7: claude.ai-web OAuth is currently flaky
**Source:** https://github.com/anthropics/claude-code/issues/11814 , https://github.com/jlowin/fastmcp/issues/972
**Takeaway:** OAuth servers that pass MCP Inspector / Claude Code still sometimes fail in
the claude.ai *web* UI (about:blank loop, zero inbound requests). Reinforces preferring the
Claude Code CLI + static-bearer path for a self-hosted server today.

### R8: Prospeo + MyEmailVerifier API docs
**Source:** https://prospeo.io/api-docs/enrich-person , https://github.com/pat-myemailverifier/myemailverifier-api
**Takeaway:** Prospeo `enrich-person` (X-KEY): 1 credit/email, NO_MATCH = HTTP 400 + free,
duplicate <90d free, `only_verified_email` gates the debit. MyEmailVerifier
`validate_single.php?apikey=&email=`: 5 status buckets, 1 credit even on Invalid, 100
free/day.

## Discarded Approaches

- **Porting the clay pipeline.** The volume funnel (8 always-on workers, supervisor,
  backlog throttling, 13-strategy rotation) is deleted, not adapted -- depth-first runs in
  the session on demand (F5). Becomes an explicit non-goal.
- **Gemini / Google / SearXNG / Brave anywhere.** All discovery + the grounded fallback
  move to Claude's session web tools; the ~5,170-line key-pool + Gemini client are dropped
  (T1, F5).
- **mcpo in front of the server** (R5) and **OAuth-now** (T6, R7) -- both rejected for this
  personal, Claude-Code-driven tool.
- **Any send / outreach / pentest-trigger tool.** Excluded by invariant; the server finds,
  qualifies, and tracks only.
- **Rich per-lead context** (evidence trail, attack-surface dossier) -- rejected by C7;
  the record stays lean.

## Risks & Open Threads

- [x] **Prospeo needs a name, not a domain** -- resolved: Claude names the decision-maker
  in-session; `resolve_contact` takes `person_name` (T3).
- [x] **DB pool buried in the to-delete dir** -- resolved: lift `asyncpg` pool into
  `mcp_server/db/pool.py` before deleting `src/api_keys/` (F2, T2).
- [x] **mcpo assumed but absent** -- resolved: not needed; FastMCP serves HTTP (T5, F9).
- [ ] **Auth surface mismatch (the one to confirm in /refine).** Static bearer works for
  Claude Code but NOT the claude.ai web connector (R3). If web is required, switch to
  OIDCProxy + IdP (T6). Design auth as a pluggable layer so the swap is config-only.
- [ ] **Host-header / origin validation behind the tunnel.** FastMCP/ASGI may 421 or reject
  the `frogbytes.xyz` Origin; configure allowed hosts/origins and the tunnel
  `httpHostHeader` (R6). Verify at deploy.
- [ ] **Mac mini RAM (4 GB).** An Incus instance + Python server is light, but confirm the
  instance memory cap leaves headroom alongside the existing Docker storage stack.
- [ ] **Prospeo free-tier reliance.** Depth-first keeps credit use low, but the multi-key
  pool is still free-tier; `prospeo_usage` (T4) is the early-warning signal for exhaustion.
- [ ] **NO_MATCH fallback yield (~20-50%, F8).** Acceptable as a free last resort; if it
  underperforms, revisit `domain-search` or a paid finder. Not a launch blocker.

## Build Plan

Dependency-ordered; phase groups in [] can run in parallel.

**Phase 1 -- Repo skeleton + config + DB pool.** New `src/mcp_server/` tree; `config.py`
(dataclass + dotenv, the 7 env vars); `db/pool.py` (asyncpg pool lifted from
`supabase_client.py`, DSN from `SUPABASE_DB_URL`); `.env.example`; trimmed
`requirements.txt`; project `CLAUDE.md`. Gate: pool connects to Supabase.

**Phase 2 -- [Salvage the keep-assets] + [Schema + lead store].**
- 2a (parallel): port `contacts/prospeo.py`, `contacts/verifier.py`, `contacts/helpers.py`,
  and `contacts/resolve.py` (the `_resolve_one` core stripped of Gemini + the worker loop).
- 2b (parallel): `schema/001_leads.sql` (the `leads` table + status CHECK enum; keep
  `prospeo_usage`); `db/leads.py` (CRUD/query); `db/usage.py`. Gate: schema applies; CRUD
  round-trips a row.

**Phase 3 -- MCP server + tools.** `server.py` (FastMCP app, bearer auth layer, run http);
`tools/leads.py` (5 CRUD/query tools); `tools/resolve.py` (`resolve_contact`,
`verify_email`). Depends on Phase 2. Gate: MCP Inspector lists 7 tools; each round-trips
locally over stdio then http.

**Phase 4 -- [The lead-finder skill].** Independent of 1-3, can run from the start.
`SKILL.md` (depth-first workflow: angles -> qualify -> keep>=7 -> resolve_contact ->
add_qualified_lead; aggressive discard); `references/icp.md` (rewritten pentest/bounty ICP,
custom-webshop profile, qualification criteria, >=7 gate, blocklists); `references/angles.md`
(the small set of discovery angles). No bundled code.

**Phase 5 -- Hosting + wiring.** Incus instance on the Mac mini; systemd unit running the
server on `0.0.0.0:8000`; `cf-publish enrichment-mcp http://10.42.0.x:8000`; set
`MCP_BEARER_TOKEN` + the API keys in the instance `.env`; `claude mcp add --transport http
... --header`. Gate: a Claude Code session lists and calls the tools end-to-end against the
live `https://enrichment-mcp.frogbytes.xyz/mcp`.

**Phase 6 -- End-to-end dry run.** One real depth-first session: discover a handful,
qualify, resolve one contact, store a lean lead, query `get_uncontacted`. Confirm the
invariant holds (no contact/test side effects) and credit logging works.
