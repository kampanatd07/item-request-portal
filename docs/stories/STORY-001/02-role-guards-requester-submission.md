# 02: Role guards + Requester submission

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-001
Blocked by: 01

**What to build:** Each Role sees and reaches only what the Authorisation
matrix allows, and a Requester's requests are always in their own name and
Plant. Apply the `require_role` dependency from 01 to the existing routes:
Requester is refused the queue, exports and all Administrator pages;
Procurement is refused Snapshot upload, config pages and Account admin. On the
request form, the requester name and email come from the logged-in Account
and cannot be edited; a Requester's Plant is preselected and locked, and the
server uses the Account's Plant whatever is posted. Procurement and
Administrator choose the Plant and submit in their own name (the originator
goes in the note). The base layout shows who is logged in and hides links the
Role cannot use. No migration.

- [x] Requester gets 403 on queue, exports and Administrator pages (AC2)
- [x] Procurement gets 403 on Snapshot upload, config pages and Account admin
- [x] A Requester posting another Plant never gets a request in the posted
      Plant — it is stored for their own Plant or refused (AC3)
- [x] Posted requester name/email are ignored; the Account's are stored
- [x] Procurement can submit for any Plant; the request is in their name
- [x] Navigation shows only links the Role can use
- [x] New request tests use `central_ids()`

Implementation notes (2026-09-29):
- A Requester's posted Plant is ignored, not refused: the service always uses
  the Account's Plant (Peter's call).
- "On behalf of" is stored as a `ขอแทน: <name>` line in the `submitted`
  RequestEvent's detail, never in `spec_note` (that is the item's spec); read
  back with `originator_of()` and shown on the request detail page.
