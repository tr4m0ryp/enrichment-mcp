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

## References
<!-- R# entries -->

## Discarded Approaches

## Risks & Open Threads

## Build Plan
