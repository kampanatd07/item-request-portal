# 04: Postgres race: two Administrators, and parallel wrong logins for one email

Status: todo
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
- [ ] Waiting is checked; waits bounded
- [ ] No production code change unless a test shows a real race; if one
      does, stop and tell Peter before fixing. No migration
