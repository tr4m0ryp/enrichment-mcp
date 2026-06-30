# ICP -- Offering, Target Profile, Qualification Rubric

This is the qualification spec for the lead finder. Read the **Company Context**
to know what we sell and to whom, then apply the **Rubric** and **Blocklists** to
every candidate. Keep only leads that clear the `>= 7` gate.

## Company Context

A boutique **penetration-testing / bug-bounty service**, run by founder
**Moussa**. The service finds **real, exploitable vulnerabilities in custom-built
online stores** and reports them under a **low-friction bounty model** -- the
operator pays for genuine findings rather than committing to a long retainer or a
heavyweight audit engagement. In practice: an independent security researcher
looks at a webshop's own code and surface, finds bugs that off-the-shelf scanners
and platform vendors miss, and hands over actionable reports.

### Why custom (non-platform) webshops

Custom webshops are the target because they are where the bespoke risk -- and the
receptive operator -- both live:

- **Bespoke attack surface.** A custom build carries its own authentication,
  cart/checkout, payment handling, account system, and APIs. That hand-written
  surface is exactly what generic scanners and platform security teams do not
  cover, so real, findable bugs accumulate there.
- **Technical, receptive operators.** Custom shops are run or backed by
  developers who understand and value a security researcher's findings. They own
  their code, so a reported bug is theirs to fix and worth paying for.
- **Platform stores are the opposite.** A Shopify / WooCommerce-cloud / Wix /
  Squarespace / BigCommerce store outsources most of its security surface to the
  platform. There is little bespoke code to test, the operator is typically
  non-technical, and "security" is seen as the platform's job -- low surface, low
  receptiveness. These are not targets.

### Target profile (the sweet spot)

**Mid-market, independent operators of their own e-commerce code:**

- **Big enough to pay a bounty** -- an established product line, real revenue
  signals, a real (not hobby) operation.
- **Small enough to be uncovered** -- no in-house security team, and no existing
  public bug-bounty or managed VDP (vulnerability-disclosure) program. The risk
  is unmanaged and the door is open.
- **Technical enough to care** -- developers in-house or a clearly engineered,
  bespoke storefront.

The ideal lead is an established independent D2C / niche retailer running custom
code, with a named technical owner and a meaningful bespoke surface, that nobody
is currently watching.

## Qualification Rubric (1-10)

Score the candidate on **five criteria, each 0-2**, then **sum to the
`bounty_fit_score` (0-10)**. Judge everything from the live site (via `web_fetch`)
plus public LinkedIn / news -- there is no fingerprint tool; you decide.

| # | Criterion | 0 | 1 | 2 |
|---|-----------|---|---|---|
| 1 | **Custom-stack confidence** (top filter) | Clearly a known platform (Shopify, WooCommerce, Magento SaaS, Wix, Squarespace, BigCommerce, Shopware cloud) | Ambiguous / headless / hybrid -- custom frontend on a commerce API, cannot fully confirm | Clear bespoke build: custom frontend + backend, custom checkout/cart, framework tells (custom Next/Rails/Laravel/Django app), self-hosted |
| 2 | **Receptiveness** | Already runs a public managed bounty program, OR has a dedicated in-house security team | Neutral -- no signals either way, but no bounty program and no security org | Strong: publishes `security.txt` / accepts vuln reports (no managed crowd), founder/team discuss security publicly, handled a past incident transparently, small independent technical team |
| 3 | **Attack surface** | Thin: static catalogue, no accounts, off-the-shelf checkout | Moderate: customer accounts OR custom checkout, but mostly standard | Rich bespoke surface: customer accounts/auth + custom checkout + payment handling + an API + user-generated content / integrations |
| 4 | **Ability to pay a bounty** | Too small (hobby / pre-revenue) OR too large (enterprise with in-house security) | Plausible: established small business, real product line, scale unclear | Clearly funded/established: many SKUs + real revenue signals, funding, sizeable-but-not-enterprise team (~10-200), own ops/warehouse |
| 5 | **Reachable decision-maker** | No identifiable individual at all | A contact exists but role unclear, or only a non-technical founder | Named technical decision-maker (founder / CTO / head of engineering) clearly identifiable on the site or LinkedIn |

### The keep-gate

Keep a lead **only if ALL hold:**

1. `bounty_fit_score` **>= 7**, AND
2. **Custom-stack confidence >= 1** (criterion 1 is the top filter -- a clear
   platform store is an automatic discard, whatever the rest scores), AND
3. **Receptiveness >= 1** (a public bounty program or an in-house security team
   is an automatic discard -- see Blocklists).

Everything below the gate is **discarded immediately and explicitly**, with a
one-line reason. Quality over count: a session that keeps two leads and discards
twenty is working correctly.

## Blocklists

Never keep, never store, a candidate matching either list. These are hard
disqualifiers (they force criteria 2 or 4 to 0 and fail the gate).

### Already-covered -- runs a public / managed bug-bounty or crowd program

The risk is already managed and there is an existing channel and crowd; we add
nothing. Recognize by a program page or listing on, or a self-hosted equivalent
of:

- HackerOne
- Bugcrowd
- Intigriti
- YesWeHack
- Open Bug Bounty (managed listing)
- Any "Security" / "Responsible Disclosure" page that advertises a *paid managed
  program* (a bare `security.txt` contact is NOT this -- that is a positive
  receptiveness signal, criterion 2)

### Out-of-ICP -- large enterprise with an in-house security team

Too big for the mid-market bounty model; almost certainly has its own AppSec
function and procurement. Recognize by clear enterprise scale (thousands of
employees, multinational, public-company footprint). Representative examples to
exclude:

- Amazon
- Walmart
- Zalando
- ASOS
- Shopify (and other platform vendors themselves)
- Any retailer with a public-company / multinational footprint and a named
  security/AppSec team

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
| `summary` | A few words on what they sell, for **recognition** -- e.g. "Independent UK menswear D2C, ~40 SKUs". Not a pitch. |
| `location` | City, country if determinable, else empty. |
| `webshop_platform` | One of `custom` / `shopify` / `woocommerce` / `unknown`. For a kept lead this is `custom` or `unknown` (a known platform would have been discarded). |
| `bounty_fit_score` | The integer 0-10 total from the rubric (>= 7 for a stored lead). |
| `why` | **ONE line.** The rationale with the **receptiveness evidence folded in** -- e.g. "Custom Laravel storefront, accounts + bespoke checkout; no bounty program, founder posts on web security." No multi-line evidence trail (C7). |
| `contact_name`, `contact_role`, `contact_email`, `contact_linkedin`, `contact_email_verified` | The ONE best contact, if resolved. All nullable -- a qualified lead with no resolvable contact is still stored (C8). `contact_email_verified` is true only for a Prospeo-verified email or a `verify_email` result with `valid: true` (status `"valid"`, never `catch_all`). |

### Field hard rules

- `summary` and `why` describe the lead for recognition and the fit rationale --
  never an outreach message, subject line, or approach. There is no outreach
  field, by design.
- One contact per lead, never a list (depth-first, one-best-contact).
- Never fabricate a company, a contact, or a verified email. If unknown, leave
  empty -- never a sentinel string.
- No emojis anywhere.
