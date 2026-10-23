# 05: Postgres race: two resends send one email; a notifier that cannot lock gives up

Status: in-progress (waiting for Peter: CI)
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

## Notes (2026-10-23)

Plan approved by Peter 2026-10-23, with one addition: the lock-timeout
tests must prove the notifier gave up on a PostgreSQL lock timeout, not only
take about 2 s.

`tests/test_pg_notify_race.py`, 7 tests, all PostgreSQL:
- Two resends of one `created` email at once (`Race`: A sent and holds its
  claim, B waits on the row): one email, one `notified` event, status
  `notified`; counts sent 1 / skipped 1.
- Two resends of one status email at once, `needs_info` and `rejected`
  (parametrized): B gets the row but finds the change announced; one email,
  one `notified` event pointing at the change.
- Lock timeout lowered to 1 s, another transaction holding the row:
  `created` → skipped, no email, still `created`, still on the resend list;
  status email → `failed` with the existing "ระบบไม่ว่าง" `notify_failed`
  pointing at the change. In both, the claim's `OperationalError` is
  recorded: SQLSTATE **55P03** (lock_not_available) on both tries, and the
  time is 1.5 s to the wait bound (2 × 1 s: `SET LOCAL` applied).
- Rejection vs export, both orders: export first → the rejection waits and
  is refused; the request is exported, its code in the file, nothing retired.
  Rejection first → the export waits and leaves it out (a second approved
  request gives the export its batch); rejected, not in the batch or the
  file, its code retired `rejected`.

**Test infrastructure changed (no test expectation changed):** `Race` now
pins each session to one connection (`pinned_session`). The notifier rolls
back after its unlocked read, and a plain session then continues on any
pooled connection, possibly not the backend watched in `pg_stat_activity`.
Found while writing these tests, before any CI run.

No production code change, no migration. Local: 898 passed, 35 skipped.
