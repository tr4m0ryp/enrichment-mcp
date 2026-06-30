---
name: lead-finder
description: >-
  Depth-first lead finder for a penetration-testing / bug-bounty offering
  (founder Moussa). Use when the operator wants to surface a few high-fit
  custom-webshop operators -- bespoke, non-platform online stores that would
  plausibly welcome a security researcher -- hard-qualify them against the ICP,
  resolve the single best contact for each, and store them as durable leads via
  the enrichment MCP tools. Discovery and qualification run in-session with
  web_search / web_fetch; contact resolution and lead state run on the MCP
  server. This skill FINDS, QUALIFIES, and STORES leads only -- it never
  contacts anyone and never runs a security test.
---

# Lead Finder -- depth-first (pentest / bug-bounty)

## Invariant -- read before anything else

This skill **FINDS, QUALIFIES, and STORES** leads. Nothing more.

- It never emails, messages, or otherwise contacts a person or company.
- It never sends, drafts, or designs any outreach (no framing, no templates,
  no handoff).
- It never triggers, schedules, or runs a security test against any target.

Resolving and storing one contact's email is **bookkeeping for a stored lead**,
not outreach. Whether a human later reaches out, and how, is out of scope and is
deliberately not designed here. If you find yourself drafting a message or
planning how to approach a lead, stop -- that is not this skill's job.

## What this skill produces

A **few** (not many) stored, qualified leads -- each a custom-webshop operator
that scored `>= 7` on the qualification rubric, carrying a lean record:
recognize-it fields, one best contact, and a one-line `why`. Depth over volume:
a handful of strong leads per session beats a long list of weak ones. Discard
aggressively.

## Inputs

A **target brief** from the operator -- any of: a niche (e.g. independent
menswear, specialty coffee gear), a geography, and/or one or more seed
companies or sites to expand from. If the brief is thin, pick the most specific
angle you can and proceed; do not stall asking for more.

## Reference files (read these)

- `references/icp.md` -- the offering, who we target and why custom webshops,
  the five-criterion 1-10 rubric with the **`>= 7` keep-gate**, and the two
  blocklists. Read it before you qualify anything.
- `references/angles.md` -- the small set of discovery angles. Pick **1-3** per
  the brief; these produce *seed candidates* that then get hard-qualified, not a
  volume funnel.

## Tools

**Session web tools (discovery, qualification, fallback contact mining):**

- `web_search` -- run the angle queries from `references/angles.md`.
- `web_fetch` -- open each candidate's real site and judge it against the ICP
  (custom-vs-platform, attack surface, receptiveness, contact). Judge
  `webshop_platform` yourself from the page -- there is no fingerprint tool.

**Enrichment MCP tools (contact resolution + durable lead state):**

- `resolve_contact(company_name, domain, person_name, role)`
  -> `{found, email, email_verified, linkedin_url, job_title}`
  or `{found: false, reason}`. Resolves and verifies ONE named decision-maker.
- `verify_email(email)` -> `{status, valid, confidence, method}`, where `status`
  is `"valid"` / `"invalid"` / `"catch_all"`. Accept the address **only** when
  `valid` is `true` (equivalently `status == "valid"`). A **catch-all** domain
  accepts any address, so it returns `status: "catch_all"`, `valid: false` --
  treat it, and `"invalid"`, as **unconfirmed**. Never store a `catch_all` result
  as a verified email.
- `add_qualified_lead(domain, company_name, summary, location,
  webshop_platform, bounty_fit_score, why, contact_name?, contact_role?,
  contact_email?, contact_linkedin?, contact_email_verified?)` -- upserts on
  `domain`. The lean record. Contact fields are optional (C8).
- `get_uncontacted()` / `list_leads(...)` / `get_lead(domain)` -- recall what
  is already stored, across sessions, before searching, to avoid re-work and
  duplicate lookups.
- `update_lead_status(domain, status)` -- status enum is
  `qualified -> contact_resolved -> contacted -> replied -> closed/rejected`.
  This skill only ever sets `qualified` or `contact_resolved`. **Never** set
  `contacted` or beyond -- those imply a human acted, which is out of scope.

There is no send tool, no outreach tool, and no pentest-trigger tool, by design.

## Workflow

### 1. Take the brief and recall state
Read the operator's brief. Call `get_uncontacted` (or `list_leads`) first so you
do not re-discover or re-resolve leads already stored. Note known domains to skip.

### 2. Discover seed candidates
Choose **1-3** angles from `references/angles.md` that fit the brief. Run their
`web_search` queries. Collect a small set of candidate companies with their
likely domains. Aim for quality of fit, not length of list.

### 3. Qualify HARD against the ICP
For each candidate, `web_fetch` the **actual site** (home, product, checkout,
account/login, `/about`, `/team`, `/contact`, and `/.well-known/security.txt`).
Then judge it against `references/icp.md`:
- **Custom stack?** Is it a bespoke, non-platform build, or clearly Shopify /
  WooCommerce / Magento / Wix / Squarespace / BigCommerce? Set `webshop_platform`
  (`custom` / `shopify` / `woocommerce` / `unknown`) from what you see (C2).
- **Receptive?** No public managed bounty program (HackerOne / Bugcrowd /
  Intigriti / YesWeHack), no in-house security team; bonus for a `security.txt`,
  a past handled incident, or public security talk.
- **Attack surface?** Customer accounts/auth, custom checkout, payment handling,
  an API, user content, integrations -- bespoke surface is the point.
- **Able to pay a bounty?** Mid-market: established product line, real revenue
  signals, sizeable-but-not-enterprise team.
- **Reachable decision-maker?** A named technical owner (founder / CTO / head of
  engineering) identifiable on the site or LinkedIn.
Score each criterion and total the `bounty_fit_score` (0-10) per the rubric.

### 4. Keep only `>= 7`; discard the rest immediately and explicitly
Apply the keep-gate from `references/icp.md`: total `>= 7`, custom-stack not
zero, and receptiveness not zero (the two blocklist conditions are hard
disqualifiers regardless of total). For every candidate you drop, say so in one
line with the reason (e.g. "discard -- Shopify storefront" / "discard -- runs a
HackerOne program"). Do not store anything below the gate. Quality over count.

### 5. Resolve the single best contact
For each kept lead, identify the **one** best decision-maker (name + role) from
the site or LinkedIn -- the person who would own web security. Call
`resolve_contact(company_name, domain, person_name, role)` for that one person.
On `found: true`, capture `email`, `email_verified`, `linkedin_url`,
`job_title`.

### 6. Fallback when `resolve_contact` returns `found: false` (NO_MATCH)
Mine the site in-session: `web_fetch` `/team`, `/about`, `/contact`, and the
person's LinkedIn for a name and the email pattern (e.g. `first@`,
`first.last@`). Construct ONE candidate address from the pattern and call
`verify_email(email)`. Accept it **only** if `status` is `Valid`. If no `Valid`
address results, store the lead anyway with the contact fields left empty and
`contact_email_verified` false -- a qualified company is never discarded just
because its contact could not be resolved (C8).

### 7. Store the lean record
Call `add_qualified_lead` with the lean fields:
`domain`, `company_name`, `summary` (a few words on what they sell, for
recognition), `location`, `webshop_platform`, `bounty_fit_score`, `why` (ONE
line; fold the receptiveness evidence in), and the one contact if found
(`contact_name`, `contact_role`, `contact_email`, `contact_linkedin`,
`contact_email_verified`). Keep it lean -- no evidence trail, no attack-surface
dossier, no source links (C7). If a verified contact was attached, advance the
status to `contact_resolved` via `update_lead_status`; otherwise leave it at the
default `qualified`.

### 8. Report and remember
Summarize the kept leads briefly to the operator (company, one-line why, contact
or "no contact"). The store is durable: a later session calls `get_uncontacted`
/ `list_leads` / `get_lead` to pick up where this one left off. Do not advance
any lead past `contact_resolved`.

## Discard discipline

Discarding is the main work. Most candidates will not clear the gate -- a
templated-platform store, an enterprise with its own security team, a shop
already running a public bounty program, a site with no reachable owner. Drop
them fast, name the reason, and move on. A short list of `>= 7` leads is the
success condition, not a failure.

## Boundaries (non-goals, restated)

- Do **not** write, suggest, or design any outreach message, subject line,
  template, sequence, or handoff. (C6)
- Do **not** run, schedule, or describe how to run a security test against any
  candidate. (C3 / C5)
- Do **not** enrich a lead with a dossier; keep the record lean. (C7)
- Do **not** advance lead status past `contact_resolved`.
