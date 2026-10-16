# 03: Procurement's "รับเข้าคิวใหม่" uses the same claim

Status: ready-for-agent
Triage: ready-for-agent
Parent: STORY-009
Blocked by: 02

**What to build:** Procurement's "ผู้ขอส่งข้อมูลแล้ว รับเข้าคิวใหม่" button
stays, for replies by phone. Its note becomes required, it clears the
request's Procurement note, and it leaves Needs Info through the same
conditional claim as a resubmit. Whichever of two concurrent attempts comes
second gets 0 rows: 409, no event, no email.

- [ ] Empty note → Thai error, nothing changes
- [ ] With a note: status `submitted`, one `submitted` event carrying the note,
      Procurement note cleared
- [ ] Two threads on a file-based SQLite DB, resubmit vs resubmit: exactly one
      `submitted` event, the other 409
- [ ] Two threads, resubmit vs the queue button: exactly one `submitted`
      event, the other 409
- [ ] Other status changes from the queue behave as before
