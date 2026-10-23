# 04: Postgres race: two Administrators, and parallel wrong logins for one email

Status: todo (plan waiting for Peter's approval)
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
      empty)
- [ ] Three Administrators deactivating each other in a cycle at once (added
      in the plan, Peter 2026-10-22): all finish, no deadlock, at least one
      active Administrator remains
- [ ] Waiting is checked; waits bounded
- [ ] No production code change unless a test shows a real race; if one
      does, stop and tell Peter before fixing. No migration
