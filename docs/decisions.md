# Decision Log

## [2026-07-24] Human-in-the-loop via import files, no direct AX/D365 write
**Decision:** System generates AX/D365 import files; Peter imports manually and marks batches as created.
**Alternatives considered:** Direct write via AIF/OData/DB — rejected: needs IT project on AX side, higher blast radius on error.
**Revisit when:** Import-file flow exceeds ~30 min/day of manual work, or IT offers a supported API.

## [2026-07-24] Duplicate/running-number source = uploaded snapshot behind an interface
**Decision:** v1 reads item master from uploaded Excel/CSV snapshots into `item_snapshot`; module exposed as an interface so live AX DB query can replace it without touching callers.
**Alternatives considered:** Wait for IT to grant read-only DB access — rejected: blocks the whole project on IT timeline.
**Revisit when:** IT grants DB access.

## [2026-07-24] Code-generation rules stored as DB config
**Decision:** Item groups/categories per system live in DB tables editable via admin UI. Rule doc proved stale (7 categories in real data missing from doc); anomalies in real data were human error.
**Alternatives considered:** Hardcode rules — rejected: rules drift, Peter must self-serve edits.
**Revisit when:** Never (this one is structural).

## [2026-07-24] Hosting: Render/Railway cloud, single Docker container
**Decision:** Deploy to Render/Railway for pilot — no IT dependency, fast iteration.
**Alternatives considered:** Company VM (blocked on IT), own PC (not durable).
**Revisit when:** Pilot succeeds and IT wants it in-house; or data policy forbids external hosting — check policy before storing real item data.

## [2026-07-24] Frontend: HTMX + Jinja2
**Decision:** App is forms/lists/queues — HTMX ships fastest, one language, readable end-to-end.
**Alternatives considered:** React — rejected for v1: no genuinely stateful UI needs; slower first ship.
**Revisit when:** UI needs drag-drop/live collaboration, or a real learning-React goal outweighs speed.

## [2026-07-27] Export templates modeled per-factory in code, reference data as config
**Decision:** 4 factory import formats (CBD 1-sheet, APM/APG 5-sheet, ACM wide)
are reproduced by per-factory builder functions. Variable fields come from the
request; fixed columns are constants from the temp files. Three reference lists
(UOM, procurement category, group→ItemGroupId/ModelGroup mapping) are editable
config seeded with observed values, completed by Peter later.
**Alternatives considered:** A fully generic data-driven column-mapping engine —
rejected as over-engineering for 4 known, stable templates.
**Revisit when:** A 5th format appears, or a factory's template changes shape.

## [2026-07-27] Search name = AI-assisted taxonomy, built after export ships
**Decision:** Slice 4 ships export using simple truncation for search name. A
later slice adds AI-assisted search-name classification into a canonical
item-type vocabulary (seeded from the well-grouped terms in the master:
WEAR STRIP, SPROCKET, PLATE, ROLLER…). Real data shows 95% of existing search
names equal the full product name — no usable taxonomy today, so this is a
genuine cleanup, not just automation.
**Alternatives considered:** (a) fuzzy-match existing search names — rejected,
95% ungrouped so it just echoes full names; (b) curated dictionary only —
viable, kept as the deterministic fallback under the AI path.
**Implementation notes for that slice:** LLM classification needs an Anthropic
API key as a *soft* dependency — always fall back to the curated dictionary +
keyword match so the deployed app never hard-fails without the key; cache
name→search_name results; every suggestion is editable by a human before export.
**Revisit when:** building the taxonomy slice.

## [2026-07-24] Auth: simple email+password first, Azure AD SSO later
**Decision:** v1 uses app-managed accounts created by Peter; structure code so AD SSO can replace the login provider later.
**Alternatives considered:** AD SSO from day 1 — rejected: blocks on IT app registration.
**Revisit when:** IT registers the Azure AD app.
