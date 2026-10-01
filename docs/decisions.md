# Decision Log

## [2026-10-01] Email through Microsoft Graph, not SMTP
**Decision:** The portal sends email with Microsoft Graph `sendMail` using an
app registration (client credentials) limited by an Application Access Policy
to one shared sender mailbox. Code goes through a `MailSender` interface; dev
and tests use log/fake senders.
**Why:** Exchange Online turns SMTP AUTH Basic Auth off by default at the end
of December 2026; building on SMTP would break right after go-live.
**Alternatives considered:** SMTP AUTH on a shared mailbox — rejected, being
retired; an external provider (SendGrid etc.) — rejected, needs SPF/DKIM for
the company domain and sends company data through a third party.
**Revisit when:** IT offers an approved relay, or Graph limits get in the way.

## [2026-09-29] Only Administrators consume the running register
**Decision:** Approving a request, re-categorising a request that already has a
code, and overriding a code are Administrator-only (the Data Steward + one
backup). Procurement keeps review, name edit, re-categorise before a code,
Needs Info, reject and export.
**Why:** Governance v1 §3 says only the central Data Steward issues running
numbers, and an issued number is used forever. All three actions consume the
register, so giving them to every Procurement Account would let 3–4 people
burn numbers that cannot be reclaimed.
**Alternatives considered:** keep STORY-001's original matrix (Procurement
approves) — rejected: contradicts Governance for no gain, since Procurement
still does most of the work.
**Implemented by:** STORY-001.
**Revisit when:** Governance changes who may issue codes.

## [2026-09-28] "Other" (99) and possible fixed assets pass through with a flag
**Decision:** Requesters may choose Sub-Category 99 but must give a reason; the
request is flagged for procurement. Requests that look like fixed assets
(machines, vehicles) are flagged, and procurement must confirm with Accounting
before approving. Neither is blocked outright.
**Why:** 99 is at 21.3% against a ≤ 15% KPI, and its reasons are what the yearly
taxonomy review needs. Blocking would push requesters into wrong specific
categories, which is worse than an honest "Other". Fixed-asset status is
Accounting's call, not something the portal can decide.
**Implemented by:** STORY-008. Rules in skill `carabao-item-master` §5.
**Revisit when:** 99 drops below 15%, or Accounting provides an asset rule.

## [2026-09-28] Names follow the standard's unit and punctuation forms exactly
**Decision:** Millilitre is written `mL`, inch `N in` (not `N"`), and `,` never
appears in a name. `/` is allowed only unspaced inside a spec (`208 L/Drum`).
**Why:** the code had drifted from Restructure Proposal §2.3 (`ml`, `4"`, and
only spaced ` , ` removed). Names that differ from the central master weaken
duplicate detection; `"` also tends to break CSV/Excel import into AX.
**Implemented by:** STORY-007. The rules live in skill `carabao-item-master` §3.
**Revisit when:** the group naming standard is revised.

## [2026-08-10] Adopt the Carabao Group central standard (supersedes earlier code/name rules)
**Decision:** The portal issues one group-wide 11-digit code
`[Group 3][Sub 2][00][Running 4]` for all four plants, names items as
`[CATEGORY] - [ชื่อ] - [รายละเอียด]`, and owns the central running register.
Taxonomy (20 groups / 130 sub-categories) and the register are embedded as
`app/data/*.json`.
**Supersedes:** the five per-plant code patterns and the space-joined name form
(แบบ B) decided on 2026-07-24 and 2026-07-30.
**Scope:** non-stock + service only. Stock (99xx / 8xx) stays with the stock
team; its code systems remain seeded but `active = False` so it can be switched
on later without a code change.
**Conflict resolved:** the group standard mandates `20 L` (spaced) while the
legacy master overwhelmingly used `20L`. Peter chose the standard — legacy data
is being migrated anyway.
**Revisit when:** stock joins the portal, or the group taxonomy is revised.

## [2026-08-10] The portal is the owner of the central running register
**Decision:** Numbers are only ever issued by incrementing a `running_register`
row inside the approval transaction (row-locked on Postgres), never by scanning
existing codes.
**Why:** the handover lists 'ทะเบียนเลขรันกลาง ยังไม่มีเจ้าของ' as the risk that
would make codes collide within the first month. Scanning also can't see codes
issued outside the portal, while a register can be reconciled.
**Revisit when:** a second system also needs to issue central codes — then the
register must move to a shared service.

## [2026-07-30] Item names are composed, not typed (แบบ B)
**Decision:** Product name = compose(ชื่อเรียก, แบรนด์, รุ่น, ขนาด, ชนิด/สี) in the
company's documented convention order, with cleaning (whitespace, forbidden
chars, token dedupe). Requester sees a live preview but cannot edit the result;
procurement can rename before export (audit-logged).
**Alternatives considered:** Noun-Modifier MRO style ('BEARING, BALL: SKF…') —
rejected: search-name taxonomy already provides grouping, and consistency with
22k existing items keeps duplicate detection accurate.
**Revisit when:** AX-side naming policy changes.

## [2026-07-30] UOM merges are manual, never automatic
**Decision:** canonical_uom() normalizes via exact -> alias -> unique
case-insensitive match; ambiguous look-alikes are left untouched. Merging is a
deliberate admin action (source becomes alias, old requests rewritten).
**Alternatives considered:** auto-merge case variants — rejected: Job (APM) vs
JOB (ACM) may be legitimately different per AX environment; a wrong merge
produces import files AX rejects.
**Revisit when:** AX teams confirm a single canonical unit list.

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
