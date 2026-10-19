# 03: Procurement's "รับเข้าคิวใหม่" uses the same claim

Status: done
Triage: ready-for-agent
Parent: STORY-009
Blocked by: 02

**What to build:** Procurement's "ผู้ขอส่งข้อมูลแล้ว รับเข้าคิวใหม่" button
stays, for replies by phone. Its note becomes required, it clears the
request's Procurement note, and it leaves Needs Info through the same
conditional claim as a resubmit. Whichever of two concurrent attempts comes
second gets 0 rows: 409, no event, no email.

- [x] Empty note → Thai error, nothing changes
- [x] With a note: status `submitted`, one `submitted` event carrying the note,
      Procurement note cleared
- [x] Two threads on a file-based SQLite DB, resubmit vs resubmit: exactly one
      `submitted` event, the other 409
- [x] Two threads, resubmit vs the queue button: exactly one `submitted`
      event, the other 409
- [x] Other status changes from the queue behave as before

Implementation notes (2026-10-16):
- `_claim_from_needs_info(db, request_id)` is the one way out of Needs Info:
  it was moved out of `resubmit_request` unchanged. `requeue_request` uses
  it, and `change_status(new_status="submitted")` hands off to
  `requeue_request`.
- **Rules in the service.** `requeue_request` refuses:
  - an empty note (RequestError);
  - an Account below Procurement (RequestForbidden). This was added after
    code review; before, only the queue router enforced it.
  The note is cleaned by the same one-line rule as the reply. It clears
  `review_note` and sends no email.
- **Queue panel.** "รับเข้าคิวใหม่" has its own form with a required note;
  "ไม่อนุมัติ" from Needs Info keeps the optional note. Queue errors:
  RequestConflict → 409.
- **Race tests.** Two threads on file SQLite meet at a Barrier just before
  the claim. Whoever claims first holds the write lock for 0.3 s, so the
  other UPDATE has to wait and then finds 0 rows.
  - Stable in 8 repeated runs.
  - Mutation check: with `AND status='needs_info'` removed, both race tests
    fail.
- **Old tests changed (approved by Peter).** Only a note was added, where a
  request goes back to submitted without one:
  - `test_notify_status.py` (4 calls)
  - `test_notify_not_applicable.py` (1)
  - `test_notify_resend.py` (3)
  - `test_queue.py` (1)
  - `test_register_guard.py` (1)
  - ticket 02's own `test_resubmit.py` (1)
- Code review, not changed (no wrong data, no one acting who should not, no
  data lost):
  1. A request deleted after the queue page opened answers 422, not 404, on
     this button: the queue's `_error` does not map RequestNotFound.
  2. `_claim_from_needs_info` does not end an open read transaction first,
     unlike `resubmit_request`. On SQLite (default journal) and PostgreSQL
     READ COMMITTED, our settings, the loser still gets 0 rows → 409. Under
     WAL or REPEATABLE READ it could be an error (500) instead.
  3. Procurement's note may itself start with "duplicate candidates:" or
     "ขอแทน:", so it can look like a system line in the history. Procurement
     writes it; the docstring now says one line is all that is promised.
  4. `change_status(new_status="submitted")` on a request in another status
     now answers 409 ("ไม่ได้รอข้อมูลแล้ว") instead of 422 (bad transition).
     Nothing is written either way.
  5. The race tests look for the loser's text in the request row and its
     events only. These paths write no other table.
