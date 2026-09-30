# 07: "My requests" page

Status: done
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

- [x] The page lists only the logged-in Account's requests (AC12)
- [x] Another Account's requests never appear, even from the same Plant
- [x] Review note and Central Code show when present
- [x] Requester lands here after login
- [x] Available to every Role
- [x] A rejected request that still carries a code (Administrator rejected it
      after approval, `code_burned` event) never shows that code as usable:
      it is shown struck through with "ยกเลิกแล้ว ห้ามใช้" and the reason
      from `review_note` (added 2026-09-29, Peter)

Implementation notes (2026-09-30, decisions by Peter):
- `/my-requests`, every Role; matched on the Account's email (immutable),
  compared lower-cased and trimmed so requests typed before login count;
  `create_account` stores emails lower-case. Newest first (id breaks ties).
- A Requester with no page to return to lands here after login; a safe
  internal `next` still wins; off-site `next` (`https://…`, `//…`) is ignored.
- Code column uses `partials/item_code.html`; a burned code is struck through
  with "ยกเลิกแล้ว ห้ามใช้" and its reason shows once, in the note column.
  Approved/exported codes carry "รอสร้างใน AX — ยังสั่งซื้อไม่ได้".
- Item name links to the queue only for Procurement/Administrator.
- Fixed on the way: the "request sent" message linked everyone to
  `/queue/{id}`, a 403 for a Requester; it now links to "คำขอของฉัน".
- Code review fixes: the landing rule lives in one place (`_landing`) and also
  applies when a logged-in Requester opens `/login`; after the forced
  first-login password change, the success page links a Requester to
  "คำขอของฉัน". Not changed on purpose: a Requester whose session ends while on
  the form lands on "My requests" after logging in again, because keeping
  `next=/` would also send everyone who types the portal's address to the
  form instead.

