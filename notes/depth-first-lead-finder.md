# Depth-First Lead Finder -- Vision Notes
# Started: 2026-06-30

## The Idea
<!-- One or two paragraphs, plain language: what is this, in a sentence a smart friend would get. -->
Repurpose the old clay-enrichment system (an autonomous, high-volume cold-outreach
machine) into the opposite: a small, sharp **lead finder** for a penetration-testing
/ bug-bounty service. Instead of discovering hundreds of companies and blasting
email, it finds a **handful of well-qualified custom-webshop operators** who would
plausibly welcome a security researcher, and for each one resolves the **single best
person to talk to**. It finds and qualifies; a human decides whether to reach out.

The "brain" is Claude itself (in claude.ai / Claude Code), driving discovery and
qualification with its own web search. A thin MCP server handles only the two things
the chat session can't: paid contact-lookup (Prospeo) and a durable lead database
that remembers state across sessions.

## Why / Intent
<!-- What problem does it solve, who is it for, what does success look like. -->
- **Who runs it:** the founder of the pentest/bounty offering (Moussa), solo / small.
- **Problem:** a pentest offer is high-consideration and low-volume -- spraying
  hundreds of generic emails is the wrong shape. The win is a few *right* targets
  with the *right* contact, not a big funnel.
- **Success looks like:** each session surfaces a few genuinely good leads (custom
  stack, plausibly receptive, reachable decision-maker, can pay a bounty), each with
  one verified contact, stored so nothing is lost between sessions. Higher hit-rate,
  fewer wasted paid lookups.

## Scope
<!-- In scope vs out of scope. -->
**In scope:** discovery + hard qualification (in the Claude session), one-best-contact
resolution (MCP/Prospeo), a durable lead CRM with a status funnel (MCP), a lead-finder
skill that drives the whole flow.

**Explicitly NOT:** no outbound email generation, no sending, no auto-follow-up. No
triggering of any actual security test. No always-on autonomous loop. No bulk
people-discovery. No cross-wiring with the pentest-authorization skill (kept fully
separate for now). The system never contacts and never tests -- those stay behind a
human gate.

## Surfaces & Pages
<!-- The concrete things that exist in the product: pages, screens, CLI commands, components. -->
- **The lead-finder skill** -- the primary surface. You talk to Claude; it runs the
  depth-first workflow and reports leads.
- **The MCP server tools** -- invisible plumbing the skill calls: `resolve_contact`
  (Prospeo) + lead CRUD/status/query tools (`add_qualified_lead`, `list_leads`,
  `get_lead`, `update_lead_status`, `get_uncontacted`).
- **(Open) a read-only dashboard** -- inherited `web/` could survive as a CRM view, or
  be dropped in favour of just asking Claude to query the store. See Open Questions.

## Key Concept Decisions
<!-- High-level approach decisions agreed during discussion. -->

### C1: Depth-first, not volume
**Decision:** Find few, qualify hard, keep only the strong, resolve one contact each.
**Reasoning:** A pentest/bounty offer is high-consideration; quality of targeting beats
quantity of contacts. Fewer paid lookups, higher hit-rate.
**Rejected:** The original volume funnel (discover hundreds, enrich all, auto-send).

### C2: Claude judges custom-vs-platform from the page (no fingerprint code)
**Decision:** Claude reads the site and decides whether it's a custom (non-platform)
shop. No deterministic fingerprinting for now.
**Reasoning:** Simple, usually correct, no code to maintain.
**Rejected (deferred):** A header/markup fingerprint check -- kept as a future option
if accuracy disappoints (would live on the server, since it needs open-network fetch).

### C3: Lead-gen stays fully separate from the pentest-authorization skill
**Decision:** No cross-wiring between this finder and the pentest side for now.
**Reasoning:** Clean separation; the finder never triggers a test.
**Rejected:** Integrating the two into one pipeline.

### C4: Split execution -- web in the session, Prospeo + state on the server
**Decision:** Claude's own web_search/web_fetch do discovery + qualification in-session;
the MCP server owns only Prospeo resolution and the lead database.
**Reasoning:** Eliminates the Gemini / Google-CSE / key-pool cost entirely; the server
only does what the sandbox can't (paid outbound API + durable storage).
**Rejected:** A server that proxies web fetches.

### C5: Finds and qualifies only -- never contacts, never tests
**Decision:** The only autonomous writes are internal CRM state. Any external action
(contacting, testing) stays behind an explicit human gate.
**Reasoning:** Safety and separation of concerns; this is a sales-qualification tool.

## Questions for Research
<!-- Technical "best way to do X" questions, handed verbatim to /research. NOT answered here. -->
- [ ] Prospeo NO_MATCH fallback: minimal Gemini-grounded lookup vs Claude web_fetch
  mining team/about pages then verifying (brief leans Claude-fetch, to drop Gemini
  entirely). Which is more reliable and fully removes the last Gemini dependency?
- [ ] State store: reuse clay's Postgres (`src/db/` already targets it) vs start on
  SQLite. Tradeoffs for a low-volume single-operator CRM.
- [ ] How `resolve_contact` should pick the single best decision-maker (role priority,
  verification, what to return) and how to log/meter Prospeo credit use.
- [ ] MCP server hosting + auth via the existing frogbytes mcpo + Cloudflare Tunnel so
  the endpoint isn't publicly callable.
- [ ] Simplified schema design (leads + one-best-contact + status enum) and migration
  off the old multi-table clay schema.
- [ ] Whether/how to keep the post-Prospeo email verifier (MyEmailVerifier).
- [ ] (Deferred option) deterministic platform-fingerprint check as a later server tool.

## Open Questions
<!-- Conceptual things about the IDEA we could not resolve yet. -->
- [ ] **The receptiveness bet + framing.** The whole model rests on custom-webshop
  operators *welcoming* an unsolicited "I'll find vulnerabilities for a bounty"
  approach. How is the offer framed so it reads as a friendly researcher, not a
  threat/shakedown? This is the make-or-break conceptual risk.
- [ ] **The human handoff.** The system stores qualified leads + one contact but never
  contacts. What is the operator's actual daily loop, and what's the output they act on?
- [ ] **Product surface:** is the experience "a Claude skill you talk to" (chat as UI)
  with the dashboard dropped, or is a read-only CRM view still wanted?
- [ ] **ICP soundness:** is "custom stack" the real signal, or a proxy for "technical,
  receptive founder"? Could the highest-fit targets sometimes be non-custom?
- [ ] **No resolvable contact:** if Prospeo can't find the best contact, is the lead
  still kept (for manual LinkedIn outreach) or discarded?
- [ ] **Cadence/volume:** how few is "depth-first" in practice -- a few leads per
  session? per week? This sizes how hard to qualify and how many angles to run.

## Non-Goals / Rejected Directions
<!-- Product directions considered and chosen against, with the reason. -->
- **Volume funnel / always-on autonomous loop** -- rejected; the offer is low-volume
  by nature (C1).
- **Outbound email generation + sending** -- removed entirely; not this system's job.
- **Bulk people-discovery + SMTP-verify funnel** -- replaced by one-best-contact
  resolution on demand.
- **Gemini-driven discovery/enrichment/scoring** -- replaced by Claude in-session.
