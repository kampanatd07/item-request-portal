# 02: Role guards + Requester submission

Status: todo
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

- [ ] Requester gets 403 on queue, exports and Administrator pages (AC2)
- [ ] Procurement gets 403 on Snapshot upload, config pages and Account admin
- [ ] A Requester posting another Plant never gets a request in the posted
      Plant — it is stored for their own Plant or refused (AC3)
- [ ] Posted requester name/email are ignored; the Account's are stored
- [ ] Procurement can submit for any Plant; the request is in their name
- [ ] Navigation shows only links the Role can use
- [ ] New request tests use `central_ids()`
