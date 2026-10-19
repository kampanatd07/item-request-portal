# Decision Log

## [2026-10-19] "My requests" shows Originator rows in any Plant; resubmit checks the Plant
**Decision:** "My requests" lists every request where the Account is the
Requester or the Originator, matched on email only, with no Plant or active
rule. Resubmitting still requires an active Originator in the request's
Plant (any Plant for an Account without one), so an Originator in another
Plant sees the row read-only, without the "แก้ไขและส่งกลับ" button.
**Why:** the Originator already receives the created and rejected emails,
which carry the same data (item name, Procurement's note, the code). Hiding
the row would leave them with an email and no request to find, and would
protect nothing the email has not already shown.
**Alternatives considered:** apply the resubmit rule to the list as well,
so one definition decides "my request" (code review, STORY-009 ticket 04).
Rejected (Peter) for the reason above.
**Revisit when:** emails to Originators stop carrying request data, or a
Plant must not see another Plant's requests for a reason beyond email.

## [2026-10-16] The Originator may resubmit a Needs Info request too
**Decision:** A Needs Info request can be edited and resubmitted by its
Requester, or by its Originator if the Originator has an active Account
(matched on email) in the request's Plant. The Originator may edit every
field except Plant and the originator fields; only the Requester can change
who the request is for. "My requests" also lists requests where the Account
is the Originator, in every status, labelled "ขอแทนโดย <Requester>".
**Why:** the Needs Info email of an on-behalf request goes to the Originator,
the person who actually has the missing detail. With only the Requester able
to resubmit, Procurement would have to relay every reply by hand.
**Alternatives considered:** Requester only (Procurement re-keys replies from
email or phone), which is simpler and matches "Procurement stays the
Requester". Rejected (Peter, STORY-009 grilling Q1) because it keeps
Procurement in the middle of every on-behalf reply.

## [2026-10-16] Resubmit emails to Procurement are best-effort
**Decision:** When a Requester or Originator resubmits, every active
Procurement and Administrator Account gets an email. It is sent in the
background, and a failure is only logged: no `notified`/`notify_failed`
event and no entry on the resend list. No email goes out when Procurement
or an Administrator resubmits themselves, or for new submissions.
**Why:** the email is a nudge. The request is in the queue whether or not the
email arrives, and the queue is where Procurement works. Putting it on the
resend list means teaching `pending_notifications`/`recipients` about a
second kind of recipient, code that took several review rounds in
STORY-002.
**Revisit when:** Procurement misses resubmitted requests because an email
did not arrive.

## [2026-10-15] The mail limiter spaces bookings, not the actual sends
**Decision:** `prepare()` first makes sure a token is cached, then books a
send slot with `RateLimiter.wait()`. Bookings are ≥ 60/MAIL_RATE_PER_MINUTE s
apart (2.4 s at 25/min), across threads too. The POSTs themselves are *not*
guaranteed to be that far apart: after booking, a notifier still claims its
rows, and that claim can wait on another notifier's lock, so two POSTs can
go out close together. A token failure books nothing, since the token
comes first.
**Purpose:** stay under Exchange's per-mailbox limit (~30/min) on average,
not exact spacing. Worst case when sends bunch up: Graph answers 429, that
send is recorded as `notify_failed` and lands on the resend list, and the
Retry-After pushes later bookings back. No email is lost.
**Why:** sending inside the row lock while waiting outside it leaves a gap
of unknown length between "slot booked" and "POST". Closing that gap means
one queued mail worker, a story-sized change, for 1–2 users at low volume.
**Correction:** the message of commit 4ec519f says "a token failure
before the post no longer wastes a turn" and "every pair of starts is >=
one interval apart". At 4ec519f the slot was booked *before* the token, so
a token failure did waste a turn (fixed in the commit after it). The
eight-thread test checks the booked starts, not the POSTs.
**Revisit when:** 429s show up often on the resend list after go-live.
Option: a single mail worker with a queue (see STORY-006 notes).

## [2026-10-14] Known limit: request rows stay locked during one short Graph call
**Decision:** Keep claim → send → record in one transaction for v1, but with
nothing slow inside it. Before the claim, `prepare()` makes sure a token is
cached, then books a send slot (bookings ≥ 60/MAIL_RATE_PER_MINUTE s apart,
also across threads, though the sends themselves may bunch up: see
2026-10-15; plus any Retry-After a 429 asked for, capped at 60 s per 429). The spacing
limiter never fails a send (Peter, 2026-10-15: one worker, 1–2 users; the
earlier sliding window with per-thread slot reservations had locking and
leak bugs). Under the
lock there is exactly one sendMail call with a short timeout (5 s connect,
10 s read), no retry and no wait: a 401/429/5xx/timeout is recorded as
`notify_failed` and the lock is released; the resend list does the
retrying. The lock covers one request
(needs_info/rejected) or the whole (To, CC) group ("created"). On PostgreSQL
(prod) those rows only; on SQLite (dev) the database-wide write lock.
**How long (under the lock):** a normal send is well under 1 s. Worst case per sendMail
≈ 15 s (5 s connect + 10 s read; the write phase is a few KB). Rare cases
add to it: a "created" group whose recipients changed since it was read is
split and sends once per part, back to back (send never waits on the
limiter); if another thread dropped the token after a 401
between prepare and send, the token is fetched under the lock (≤ 20 s).
A Procurement status change on a locked request waits that long
(`_get_locked` has no lock_timeout); other requests are not affected.
**Wait before the lock** (no rows held): the spacing (2.4 s at the default
rate) or a 429's Retry-After (≤ 60 s each). This wait has no fixed bound:
every further 429 seen while waiting pushes it later again, so a run of 429s
keeps it waiting until Graph stops throttling.
**Why:** 1–2 Procurement users and a low email volume; restructuring to
claim → commit → send → record adds a "sending" state and its own crash
recovery, for a problem not yet seen. Moving the slow parts out of the lock
was cheap and removes the multi-minute worst case.
**Alternatives considered:** a separate claim transaction with a `sending`
marker — deferred, not rejected. Retrying 429/5xx inside the send —
rejected: it held the lock for up to ~2–3 minutes.
**Revisit when:** after go-live, a Graph call is seen to be slow (the
`mail sent via Graph` log line, or Procurement reporting a hanging status
change), or rate-limit / Graph failures pile up on the resend list.

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
