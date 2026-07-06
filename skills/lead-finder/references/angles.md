# Discovery Angles

A **small** set of angles for surfacing seed candidates with the session's
`web_search`. This is **not** a volume funnel and not a strategy rotation: each
angle produces a handful of **seed candidates**, and **every seed must still pass
the hard qualification rubric and `>= 7` keep-gate in `icp.md`** -- including the
breach-blast-radius gate (criterion 3). A seed is a hypothesis ("this might be a
custom, receptive, high-impact B2B commerce operator"), nothing more.

**How to use:** pick **1-3** angles that fit the operator's brief, run their
searches, collect candidate companies + likely domains, then `web_fetch` each and
qualify hard. Stop generating seeds once you have enough to qualify a few keepers
-- depth beats breadth.

**Target reminder:** we want **custom-built B2B / high-blast-radius commerce**
(distributors, wholesalers, B2B webshops, marketplaces, trade/dealer/reseller
portals, platforms holding valuable/sensitive customer data), **EU-wide**,
**small-to-mid-market** (real revenue but roughly under ~€50M), **unwatched**. We
do **not** want low-stakes B2C consumer-hobby shops -- those fail criterion 3.

**Placeholders** come from the brief: `[vertical]` (e.g. electronics
distribution, industrial/MRO supplies, wholesale trade, packaging, lab/medical
supplies, automotive parts B2B, B2B food/hospitality supply), `[region]` /
`[target geographies]` (default **EU-wide** when unset), `[seed]` (a company or
site the operator handed you, e.g. `t1distribution.nl`).

---

## Angle 1 -- B2B / distribution custom-build signal

**Why:** A B2B webshop, distributor, or wholesaler that runs its own bespoke
storefront/portal almost certainly has fresh, hand-written, untested surface
(dealer login, quote/order flow, pricing engine, API) *and* high breach impact
(business-customer data). This is the core archetype.

**Search (examples):**
- `[vertical] B2B webshop OR wholesale portal custom built Next.js OR Laravel OR Rails [region]`
- `[vertical] distributor "dealer portal" OR "reseller login" OR "trade account" ecommerce`
- `[vertical] B2B ecommerce "we built our own" checkout OR portal OR platform`
- `[vertical] wholesaler hiring "backend engineer" OR "ecommerce developer" [region]`

**Recognize a fit:** a trade/dealer/reseller account or B2B pricing behind login,
a quote/RFQ or bulk-order flow, an ordering API or EDI/integration surface, an
engineering/changelog post or a job ad for backend/full-stack engineers; a
storefront that does not look templated.

---

## Angle 2 -- Receptiveness signal (unwatched)

**Why:** Receptiveness is the rubric criterion most often missing. Start from
operators who have *already shown* they take security seriously but have no
managed program -- they are primed to welcome a researcher.

**Search (examples):**
- `[vertical] B2B ecommerce security.txt -hackerone -bugcrowd`
- `[vertical] distributor OR wholesaler "responsible disclosure" -bugcrowd -intigriti`
- `[vertical] ecommerce founder OR CTO talk OR blog "web security" OR "appsec" [region]`
- `[vertical] B2B retailer data breach OR vulnerability disclosed [region]`

**Recognize a fit:** a `/.well-known/security.txt` or a plain responsible-
disclosure page **without** a paid managed crowd program; a founder/CTO who has
spoken or written about web security; a past incident handled openly. A full
HackerOne / Bugcrowd / Intigriti / YesWeHack program is the opposite -- a
blocklist hit (see `icp.md`), not a seed.

---

## Angle 3 -- High blast-radius data signal

**Why:** The dimension that was missing. Go straight at operators whose
compromise would expose valuable business customers or sensitive data --
marketplaces, platforms, and distributors running customer account/portal
systems -- rather than low-stakes consumer catalogues.

**Search (examples):**
- `[vertical] B2B marketplace OR trade platform custom [region]`
- `[vertical] distributor customer portal accounts pricing API [region]`
- `[vertical] wholesale platform "business accounts" OR "credit account" ecommerce`
- `[region] B2B ecommerce handling "customer data" OR "order history" OR "integrations"`

**Recognize a fit:** business-customer accounts holding order/pricing/contract
history, a marketplace connecting many buyers/sellers, integration/API access to
customer systems -- anything where one bug spills many high-value customers'
data. Confirm the custom stack on the live site.

---

## Angle 4 -- Seed / vertical breadth (EU-wide)

**Why:** A steady source of seeds: independent B2B commerce operators in a chosen
vertical and region are disproportionately custom-built, mid-market, and
unwatched. Use this to widen the pool when the targeted angles run thin, and to
expand from a seed the operator handed you.

**Search (examples):**
- expand from `[seed]`: `companies like [seed]` / `[seed] competitors [vertical]`
  / `[vertical] distributors like [seed] Europe`
- `independent [vertical] B2B distributor OR wholesaler [target geographies]`
- `best European [vertical] wholesale OR trade webshops`
- `[vertical] B2B ecommerce not on Shopify OR Magento [region]`

**Recognize a fit:** an established independent B2B operator (real product range,
revenue signals, business customers) that is clearly its own operation rather
than a marketplace *listing* or a templated drop-shipper. Treat each as a seed
and qualify it on the live site -- breadth here exists only to feed the hard
gate, never to pad a list. Discard consumer-hobby results by name.

---

## After every angle

Seeds are cheap; keepers are not. For each seed, `web_fetch` the real site and
run the full `icp.md` rubric -- **including the breach-blast-radius gate**.
Discard anything below `>= 7`, any platform store, and any low-stakes B2C
consumer-hobby shop, immediately and by name. The job of these angles ends at a
qualified `>= 7` lead -- never at an outreach plan.
