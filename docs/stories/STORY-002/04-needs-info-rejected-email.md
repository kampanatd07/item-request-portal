# 04: Needs Info and rejection emails

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-002
Blocked by: 01

**What to build:** When Procurement sends a request back (`needs_info`) or
rejects it, the requester gets one Thai email per request with the reason
(`review_note`). A rejection of an approved request (code already issued and
now burned) says "รหัส X ยกเลิกแล้ว ห้ามใช้" prominently, so nobody orders
with it. Sent after commit (BackgroundTasks), with the same atomic dedupe:
under the row lock, send only if the latest status event for that change has
no `notified` event after it. Status does not change; success adds a
`notified` event (detail names the kind), failure a `notify_failed` event.
Until STORY-009, the needs_info email says how to reply (Reply-To / contact
Procurement).

- [x] needs_info → one email with the reason; rejected (before a code) → one
      email with the reason (AC6)
- [x] Rejected after approval → the email names the cancelled code and says
      it must not be used
- [x] Double send of the same change → one email
- [x] No email on `approved`

Implementation notes (2026-10-02, decisions by Peter):
- Each email belongs to one status change E (the `needs_info` / `rejected`
  event). `request_events.ref_event_id` (FK to `request_events.id`, indexed)
  was added to the story's single migration `e52ce808c5d5` (Peter: a real
  column, not text in `detail`); `notified` / `notify_failed` events point at
  E, and "already announced?" is `ref_event_id = E.id AND action = 'notified'`.
- `notify_status(factory, request_id, E.id, sender, actor)`: under the row
  lock (the same `UPDATE … WHERE status` claim + PostgreSQL lock_timeout),
  send only if the request is still in E's status, E is still its latest
  status change, and nothing has announced E yet. A stale or superseded
  change is skipped quietly (logged, no notify_failed). Two needs_info
  rounds are two changes, so two emails. A failed send can be resent.
- Rejected after approval: subject and body say "รหัส X ยกเลิกแล้ว ห้ามใช้".
- dev.db was backed up, downgraded, and upgraded again with the new column
  (no originator data; the 4 seeded domains came back from seed).
- Code review fixes: the reason shown is the note of *this* change (its
  event's detail; "-" when empty), never `review_note`, which keeps an older
  note when a change comes without one; "busy twice" and errors in the
  post-claim checks are recorded as `notify_failed` (with `ref_event_id`), since
  a needs_info/rejected request has no leftover state for ticket 06 to find.

