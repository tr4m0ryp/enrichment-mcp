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
<!-- filled after investigation -->

## Decisions
<!-- T# entries, filled as resolved -->

## Stack & Libraries

## Architecture

## Decisions Made For You (override in /refine)

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
<!-- R# entries -->

## Discarded Approaches

## Risks & Open Threads

## Build Plan
