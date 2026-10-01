# 04: Needs Info and rejection emails

Status: todo
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

- [ ] needs_info → one email with the reason; rejected (before a code) → one
      email with the reason (AC6)
- [ ] Rejected after approval → the email names the cancelled code and says
      it must not be used
- [ ] Double send of the same change → one email
- [ ] No email on `approved`
