# 05: Postgres race: two resends send one email; a notifier that cannot lock gives up

Status: todo
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01

**What to build:** proof on real PostgreSQL (AC 4, STORY-002) that two
resends of the same notification at the same moment send one email (row
lock and state check before sending), and that a notifier which cannot get a
request row within its `lock_timeout` (`SET LOCAL`, 30 s in production)
gives up and leaves the requests `created` on the resend list instead of
hanging its background task.

- [ ] Two resends of one `created` group at once: the fake outbox holds one
      email; the request is recorded as notified once
- [ ] Two resends of one status email (`needs_info` / `rejected`) at once:
      one email
- [ ] A transaction holds the request row; the notifier's timeout is lowered
      to about 1 s for the test: the notifier gives up within a few seconds,
      nothing is sent, the request is still on the resend list, and the
      failure is recorded as the existing code records it
- [ ] The `SET LOCAL` really applies on PostgreSQL (the wait ends at the
      lowered timeout, not at the test timeout)
- [ ] A rejection (`approved → rejected`) while an export holds that row
      (added by Peter, 2026-10-22, from the ticket 03 review): the loser
      waits on the lock, and the outcome is consistent: if the request is in
      the file it is `exported`, not `rejected`; if it is `rejected` it is
      not in the file
- [ ] Waits bounded; no production code change unless a test shows a real
      problem; if one does, stop and tell Peter before fixing. No migration
