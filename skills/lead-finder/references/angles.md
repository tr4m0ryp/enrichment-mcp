# Discovery Angles

A **small** set of angles for surfacing seed candidates with the session's
`web_search`. This is **not** a volume funnel and not a strategy rotation: each
angle produces a handful of **seed candidates**, and **every seed must still pass
the hard qualification rubric and `>= 7` keep-gate in `icp.md`**. A seed is a
hypothesis ("this might be a custom, receptive, mid-market shop"), nothing more.

**How to use:** pick **1-3** angles that fit the operator's brief, run their
searches, collect candidate companies + likely domains, then `web_fetch` each and
qualify hard. Stop generating seeds once you have enough to qualify a few keepers
-- depth beats breadth.

**Placeholders** come from the brief: `[niche]` (e.g. specialty coffee gear,
independent menswear), `[region]` / `[target geographies]` (note when unset and
use a sensible default), `[seed]` (a company or site the operator handed you).

---

## Angle 1 -- Recent custom-build signal

**Why:** A shop that recently shipped or rebuilt a bespoke storefront, or is
hiring engineers to run one, almost certainly has fresh, hand-written, untested
surface -- and a technical owner who values a researcher.

**Search (examples):**
- `[niche] online store custom built Next.js OR Rails OR Laravel`
- `[niche] ecommerce "rebuilt our store" OR "new website" engineering blog`
- `[niche] shop hiring "backend engineer" OR "ecommerce developer" [region]`
- `"we built our own" checkout OR storefront [niche]`

**Recognize a fit:** an engineering/changelog post or a job ad for backend /
full-stack / e-commerce engineers; mentions of their own checkout, API, or app;
a storefront that does not look templated. Hiring developers to run the store is
itself the signal -- it means custom code and in-house ownership.

---

## Angle 2 -- Receptiveness signal

**Why:** Receptiveness is the rubric criterion most often missing. Start from
operators who have *already shown* they take security seriously but have no
managed program -- they are primed to welcome a researcher.

**Search (examples):**
- `[niche] ecommerce security.txt -hackerone -bugcrowd`
- `[niche] online store "responsible disclosure" -bugcrowd -intigriti`
- `[niche] shop founder talk OR blog "web security" OR "appsec"`
- `[niche] retailer data breach OR vulnerability disclosed [region]`

**Recognize a fit:** a `/.well-known/security.txt` or a plain responsible-
disclosure page **without** a paid managed crowd program; a founder/CTO who has
spoken or written about web security; a past incident the company handled
openly. A full HackerOne / Bugcrowd / Intigriti / YesWeHack program is the
opposite -- a blocklist hit (see `icp.md`), not a seed.

---

## Angle 3 -- Migration signal (off-platform to custom)

**Why:** Shops moving off Shopify / WooCommerce onto their own stack are
deliberately taking on bespoke surface and the responsibility for it -- a strong
custom-stack and technical-ownership signal, often mid-migration when bugs are
freshest.

**Search (examples):**
- `[niche] "migrated off Shopify" OR "left Shopify" custom platform`
- `[niche] "replatformed" OR "moved off WooCommerce" headless commerce`
- `[niche] ecommerce "built our own platform" case study`
- `[niche] headless commerce custom storefront [region]`

**Recognize a fit:** a blog post, case study, or talk describing leaving a SaaS
platform for a custom or headless build; a storefront now lacking platform
fingerprints; engineering content about their migration. Confirm on the live
site that the move actually happened (no lingering platform tells).

---

## Angle 4 -- Niche / geographic breadth

**Why:** A steady, reliable source of seeds: independent D2C operators in a
chosen niche and region are disproportionately custom-built, mid-market, and
unwatched. Use this to widen the pool when the targeted angles run thin.

**Search (examples):**
- `independent [niche] direct-to-consumer brand [target geographies]`
- `best independent [niche] online stores [region]`
- `[niche] D2C retailer not on Shopify [region]`
- expand from `[seed]`: `companies like [seed]` / `[seed] competitors [niche]`

**Recognize a fit:** an established independent store (real product range,
revenue signals) that is clearly its own operation rather than a marketplace
listing or a templated drop-shipper. Treat each as a seed and qualify it on the
live site -- breadth here exists only to feed the hard gate, never to pad a list.

---

## After every angle

Seeds are cheap; keepers are not. For each seed, `web_fetch` the real site and
run the full `icp.md` rubric. Discard anything below `>= 7` immediately and by
name. The job of these angles ends at a qualified `>= 7` lead -- never at an
outreach plan.
