# 06: Resend failed notifications

Status: todo
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

- [ ] Resend after a failure sends the email and moves the request on (AC1)
- [ ] The Export list shows exactly the requests still `created`; "send all"
      groups them per recipient
- [ ] Pressing resend twice sends one email (AC8)
- [ ] Requesters get 403 on both buttons (AC11)
