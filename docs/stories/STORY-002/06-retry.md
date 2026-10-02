# 06: Resend failed notifications

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-002
Blocked by: 01

**What to build:** A failed or lost email can be sent again without touching
the database by hand. The queue detail page shows the latest `notify_failed`
reason and a "ส่งอีเมลอีกครั้ง" button for that request's pending
notification (created / needs_info / rejected). The Export page lists
"สร้างแล้วแต่ยังไม่ได้แจ้ง" — requests still `created` (failed, or lost to a
restart) — with "ส่งซ้ำทั้งหมด", which uses the batched grouping of ticket 03.
Both buttons are Procurement + Administrator only and go through the same
atomic dedupe, so pressing twice sends once.

- [x] Resend after a failure sends the email and moves the request on (AC1)
- [x] The Export list shows exactly the requests still `created`; "send all"
      groups them per recipient
- [x] Pressing resend twice sends one email (AC8)
- [x] Requesters get 403 on both buttons (AC11)

Implementation notes (2026-10-02, decisions by Peter):
- `notify.pending_notifications(db, now)` is the one read the list, the queue
  panel and the menu counter share. It holds (a) every request still
  `created`, and (b) every needs_info/rejected change E that is still current
  (the request is in E's status and E is its latest status change) with no
  `notified` pointing at E, and either a `notify_failed` pointing at E or
  older than 10 minutes (`LOST_AFTER`: lost to a restart). A stale E is never
  listed, so never resent. The reason shown is the latest `notify_failed`
  (for `created`, only failures since the change to `created`), else
  "ยังไม่ได้ส่ง — อาจค้างจากการ restart".
- Export page: "อีเมลที่ยังไม่ได้ส่ง" table + "ส่งซ้ำทั้งหมด" (background;
  `created` ones grouped per (To, CC) through `notify_created`). Queue detail:
  latest reason + "ส่งอีเมลอีกครั้ง", sent at once with the result shown.
  Both go through the same claims as the first send.
- Menu: "Export (อีเมลค้าง N)" when N > 0, Procurement and above only.
  Counted in `session_account` while the request's session is open (full
  pages only, not HTMX fragments) into `request.state.pending_mail_count`;
  base.html only reads the number and shows nothing when it is absent
  (Peter: templates never query the DB).
- One HTTP end-to-end test on a file SQLite DB (request and background
  sessions on separate connections): fail, listed, resend twice, one email.
- No migration.
