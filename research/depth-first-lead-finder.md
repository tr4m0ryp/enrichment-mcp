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
<!-- F# entries -->

## References
<!-- R# entries -->

## Discarded Approaches

## Risks & Open Threads

## Build Plan
