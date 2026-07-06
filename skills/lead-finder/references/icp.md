# ICP -- Offering, Target Profile, Qualification Rubric

This is the qualification spec for the lead finder. Read the **Company Context**
to know what we sell and to whom, then apply the **Rubric** and **Blocklists** to
every candidate. Keep only leads that clear the `>= 7` gate.

## Company Context

A boutique **penetration-testing / bug-bounty service**, run by founder
**Moussa**. The service finds **real, exploitable vulnerabilities in custom-built
online commerce** and reports them under a **low-friction bounty model** -- the
operator pays for genuine findings rather than committing to a long retainer or a
heavyweight audit engagement. In practice: an independent security researcher
looks at a shop's own code and surface, finds bugs that off-the-shelf scanners
and platform vendors miss, and hands over actionable reports.

### Who we target: custom-built, high-blast-radius commerce (NOT consumer hobby)

The target is a **custom-coded commerce operator where a breach would hurt a
lot** -- because of *who its customers are* and *what data it holds*, not just
because its code is bespoke. The archetype is a **B2B webshop / distributor /
wholesaler / marketplace / trade platform**: it holds valuable, sensitive
customer data (corporate accounts, order and pricing history, contract terms,
PII, payment and integration secrets), and its buyers are high-value businesses.
A leak there is a serious incident for the operator *and* its customers -- which
is exactly what makes a security test worth paying for.

Three things must all be true:

- **Custom (non-platform) stack.** A bespoke build carries its own
  authentication, cart/checkout, account/portal system, and APIs -- the
  hand-written surface generic scanners and platform teams don't cover, where
  real findable bugs accumulate, and which the operator owns and can fix.
- **High breach blast-radius.** B2B / distribution / marketplace / platform
  whose compromise exposes valuable business customers or sensitive data. This is
  the dimension the old ICP was missing, and it is now a scored, gated criterion.
- **Unwatched and receptive.** Small-to-mid-market: real revenue but roughly
  **under ~€50M**, **no in-house AppSec team**, and **no managed bug-bounty / VDP
  program**. The risk is unmanaged and the door is open. Big enough to pay a
  bounty, small enough that nobody is already watching.

### What is NOT a target

- **Platform-hosted stores** (Shopify / WooCommerce-cloud / Wix / Squarespace /
  BigCommerce / Shopware cloud) -- little bespoke code, non-technical operator,
  security outsourced to the platform. Fails criterion 1.
- **Low-stakes B2C consumer-hobby shops** -- a bike-parts, model-building,
  fishing-gear, or apparel D2C store whose breach mostly exposes ordinary
  consumer orders. Low blast-radius; fails criterion 3. *This is the class the
  pipeline was wrongly filling up with -- it is now explicitly out.*
- **True enterprises** with their own AppSec function and procurement (thousands
  of staff, multinational, public-company footprint). Too big for the bounty
  model. Fails criterion 4.

### Target profile (the sweet spot)

A **small-to-mid-market, independent, custom-coded B2B or otherwise
high-blast-radius commerce operator**, EU-based, holding valuable/sensitive
customer data, with a named technical owner, that nobody is currently watching.

## Qualification Rubric (1-10)

Score the candidate on **five criteria, each 0-2**, then **sum to the
`bounty_fit_score` (0-10)**. Judge everything from the live site (via `web_fetch`)
plus public LinkedIn / news -- there is no fingerprint tool; you decide.

| # | Criterion | 0 | 1 | 2 |
|---|-----------|---|---|---|
| 1 | **Custom-stack confidence** (top filter) | Clearly a known platform (Shopify, WooCommerce, Magento SaaS, Wix, Squarespace, BigCommerce, Shopware cloud) | Ambiguous / headless / hybrid -- custom frontend on a commerce API, cannot fully confirm | Clear bespoke build: custom frontend + backend, custom checkout/cart + account/portal + API, framework tells (custom Next/Rails/Laravel/Django app), self-hosted |
| 2 | **Receptiveness** (unwatched) | Already runs a public managed bounty program, OR has a dedicated in-house security team | Neutral -- no bounty program and no security org, no other signal | Strong: publishes `security.txt` / accepts vuln reports (no managed crowd), founder/team discuss security publicly, handled a past incident transparently, small independent technical team |
| 3 | **Breach blast-radius / segment fit** (the new top-of-mind filter) | Low-stakes B2C consumer-hobby retail -- breach mostly exposes ordinary consumer orders, little sensitive/high-value data | Mixed: some B2B or trade customers, or moderately sensitive data, but mostly consumer | Clear **B2B / distributor / wholesaler / marketplace / trade or dealer platform** holding valuable or sensitive customer data (corporate accounts, pricing, contracts, PII, payment/integration data) -- a breach hits high-value business customers |
| 4 | **Right-sized to pay & stay unwatched** | Too small (hobby / pre-revenue) OR too large (enterprise with in-house AppSec + procurement) | Plausible: established operation, real product/customer base, scale unclear | Established small/mid-market operator: real revenue signals but roughly **under ~€50M**, sizeable-but-not-enterprise team, **no in-house security team** -- can pay a bounty, isn't already watched |
| 5 | **Reachable technical decision-maker** | No identifiable individual at all | A contact exists but role unclear, or only a non-technical founder | Named technical decision-maker (founder / CTO / head of engineering / head of IT) clearly identifiable on the site or LinkedIn |

### The keep-gate

Keep a lead **only if ALL hold:**

1. `bounty_fit_score` **>= 7**, AND
2. **Custom-stack confidence >= 1** (criterion 1 -- a clear platform store is an
   automatic discard, whatever the rest scores), AND
3. **Receptiveness >= 1** (a public bounty program or an in-house security team is
   an automatic discard -- see Blocklists), AND
4. **Breach blast-radius >= 1** (criterion 3 -- a pure low-stakes B2C
   consumer-hobby shop is an automatic discard even if its stack is custom; we
   target high-impact / B2B commerce, not hobby retail).

Everything below the gate is **discarded immediately and explicitly**, with a
one-line reason. Quality over count: a session that keeps two leads and discards
twenty is working correctly.

## Blocklists

Never keep, never store, a candidate matching either list. These are hard
disqualifiers (they force criteria 2 or 4 to 0 and fail the gate).

### Already-covered -- runs a public / managed bug-bounty or crowd program

The risk is already managed and there is an existing channel and crowd; we add
nothing. Recognize by a program page or listing on, or a self-hosted equivalent
of: HackerOne, Bugcrowd, Intigriti, YesWeHack, Open Bug Bounty (managed listing),
or any "Security" / "Responsible Disclosure" page advertising a *paid managed
program* (a bare `security.txt` contact is NOT this -- that is a positive
receptiveness signal, criterion 2).

### Out-of-ICP -- large enterprise with an in-house security team

Too big for the mid-market bounty model; almost certainly has its own AppSec
function and procurement. Recognize by clear enterprise scale (thousands of
employees, multinational, public-company footprint). Representative examples to
exclude: Amazon, Walmart, Zalando, ASOS, Shopify (and other platform vendors
themselves), or any operator with a public-company / multinational footprint and
a named security/AppSec team.

### Effectively out -- low-stakes B2C consumer-hobby retail

Not a named blocklist, but a **low-blast-radius consumer-hobby store fails
criterion 3** (bike parts, model-building, fishing/angling gear, DJ/music gear,
apparel, paint/décor -- ordinary consumer orders, little sensitive/high-value
data). Discard the same way, with the reason "discard -- low blast-radius B2C
hobby retail." If such a shop *also* runs a genuine B2B/trade arm holding
business-customer data, judge it on that (criterion 3 may reach 1-2).

Platform-hosted stores (Shopify / WooCommerce-cloud / Wix / Squarespace /
BigCommerce) are not a named blocklist but fail criterion 1 (custom-stack = 0)
and are discarded the same way.

## Output Fields Per Lead (the lean record)

When a lead clears the gate, store exactly these via `add_qualified_lead`.
`webshop_platform` and `why` are **first-class** -- always set both.

| Field | Rule |
|-------|------|
| `domain` | Bare registrable domain, e.g. `examplestore.com`. Primary key; upserts. |
| `company_name` | Official company / store name. |
| `summary` | A few words on what they sell **and to whom**, for **recognition** -- e.g. "NL B2B electronics distributor, dealer portal + API". Not a pitch. |
| `location` | City, country if determinable, else empty. EU-wide is fine. |
| `webshop_platform` | One of `custom` / `shopify` / `woocommerce` / `unknown`. For a kept lead this is `custom` or `unknown` (a known platform would have been discarded). |
| `bounty_fit_score` | The integer 0-10 total from the rubric (>= 7 for a stored lead). |
| `why` | **ONE line.** Fold in the **blast-radius** and **receptiveness** evidence -- e.g. "Custom Laravel B2B dealer portal, accounts + pricing + API; no bounty program, security.txt present." No multi-line evidence trail (C7). |
| `contact_name`, `contact_role`, `contact_email`, `contact_linkedin`, `contact_email_verified` | The ONE best contact, if resolved. All nullable -- a qualified lead with no resolvable contact is still stored (C8). `contact_email_verified` is true only for a Prospeo-verified email or a `Valid` `verify_email` result. |

### Field hard rules

- `summary` and `why` describe the lead for recognition and the fit rationale --
  never an outreach message, subject line, or approach. There is no outreach
  field, by design.
- One contact per lead, never a list (depth-first, one-best-contact).
- Never fabricate a company, a contact, or a verified email. If unknown, leave
  empty -- never a sentinel string.
- No emojis anywhere.
