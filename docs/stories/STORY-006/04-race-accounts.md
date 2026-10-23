# 04: Postgres race: two Administrators, and parallel wrong logins for one email

Status: in-progress (waiting for Peter: CI)
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01

**What to build:** proof on real PostgreSQL row locks (AC 4 and AC 5) that
(a) two Administrators deactivating or demoting each other at the same
moment always leave at least one active Administrator (lock on all active
Administrator rows, in id order, STORY-001 ticket 04), and (b) parallel
wrong logins for one email never push the count past 10 (row lock from
STORY-001 ticket 06).

- [ ] Deactivate vs deactivate, demote vs demote, deactivate vs demote:
      exactly one succeeds, the other is refused with the existing "last
      Administrator" message; one active Administrator remains
- [ ] No deadlock in any of those pairs (lock order by id holds)
- [ ] N parallel wrong passwords for one email (N well above 10): the stored
      failure count and the lock behave exactly as 10 sequential failures
      **Reworded for ticket 08's slots (2026-10-23, plan pending Peter):** 30
      parallel wrong passwords at one email from 30 IPs (one IP would stop at
      the IP limit first), raced freely (no gate, unlike ticket 08's
      200-guess test): the Account's real hash is checked at most 10 times,
      `failed_login_count` is exactly 10, the Account is locked, "locked" is
      logged once, and no slot is left (`pending_checks` 0, `pending_since`
      empty). Added by Peter (2026-10-23): all 30 get the same answer (status
      and error text), slot or not; run 3 times (parametrized), and if a round
      fails, do not re-run until it passes: stop and report
- [ ] Three Administrators deactivating each other in a cycle at once (added
      in the plan, Peter 2026-10-22): all finish, no deadlock, at least one
      active Administrator remains
- [ ] Waiting is checked; waits bounded
- [ ] No production code change unless a test shows a real race; if one
      does, stop and tell Peter before fixing. No migration

## Notes (2026-10-23)

Plan approved by Peter 2026-10-23. `tests/test_pg_account_race.py`, 8 tests,
all PostgreSQL:
- Two Administrators (A1, A2), A held at its commit, B waiting on the
  Administrator row locks (`pg_stat_activity`), in 4 orders: deactivate vs
  deactivate, demote vs demote, deactivate vs demote, demote vs deactivate.
  The second is refused with the existing "…ผู้ดูแลระบบคนสุดท้ายที่ใช้งานอยู่"
  message; A1 is the one active Administrator left.
- Three Administrators deactivating each other in a cycle, started together
  (barrier): all finish within the bound (no deadlock), only "deactivated" or
  the last-Administrator refusal, at least one active Administrator left.
- 30 parallel wrong passwords at one email from 30 IPs through `POST /login`
  (the app on this test's PostgreSQL database), raced freely, 3 rounds: all
  30 answers identical (401, the generic message), the real hash checked at
  most 10 times, `failed_login_count` exactly 10, locked, one "locked" log
  line, no slot left.
No production code change, no migration. Local: 896 passed, 28 skipped.
