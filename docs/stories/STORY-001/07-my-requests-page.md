# 07: "My requests" page

Status: todo
Triage: ready-for-agent
Parent: STORY-001
Blocked by: 02

**What to build:** A logged-in Account opens "My requests" and follows its own
requests without asking Procurement: a read-only list, newest first, showing
Item Name, Plant, Request Status (Thai label), Procurement's review note (so a
Needs Info or rejected request says why) and the Central Code once issued. The
list shows only requests submitted by that Account. It is the page a Requester
lands on after login. Editing and resubmitting a Needs Info request is
STORY-009, not this ticket. No migration.

- [ ] The page lists only the logged-in Account's requests (AC12)
- [ ] Another Account's requests never appear, even from the same Plant
- [ ] Review note and Central Code show when present
- [ ] Requester lands here after login
- [ ] Available to every Role
