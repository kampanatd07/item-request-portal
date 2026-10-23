# 04: Postgres race: two Administrators, and parallel wrong logins for one email

Status: in-progress (review found (ก); waiting for Peter's decision)
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

CI on `9e87db4` (Peter, 2026-10-23): green, **924 passed, 0 skipped**
(`test_pg_account_race.py` 8 passed).

## Code review (2026-10-23)

Ran `/code-review` on `e4d4a36..9e87db4`. 10 findings. **One (ก)**, a race in
production code that the cycle test accepted instead of reporting (the
ticket says: stop and tell Peter); not fixed yet.

### (ก) Must fix — waiting for Peter
1. **An Administrator deactivated or demoted a moment ago still finishes
   their own deactivate/demote.** `deactivate_account` and `change_access`
   check the acting Account's role when the request starts (the route's
   guard) and never again once they hold the Administrator row locks. In the
   cycle a1→a2, a2→a3, a3→a1: a1's change commits first; a2's call, already
   past the guard, then gets the locks and deactivates a3, although a2 is no
   longer an active Administrator. At least one Administrator always remains
   (the AC holds), but someone acts who should not. Same gap in the
   two-Administrator demote cases: the demoted one is refused only by the
   last-Administrator rule, not for losing the role. The cycle test's
   `outcomes <= {"deactivated", "refused"}` accepted it.

### (ข) Notes
2. The cycle test does not show the three calls overlapped (a barrier only
   syncs the thread start); a serial run passes too. "Waiting is checked"
   is met by the four two-Administrator tests, not by this one.
3. The 30-login test does not show the logins overlapped (e.g. slots in use
   above 1 at some moment); each thread builds its own TestClient, which can
   stagger them. The gated 200-guess test of ticket 08 is what proves the
   parallel cap; this one proves the free race ends right.
4. The cycle test's assertions are weaker than every order's actual result
   (exactly 2 deactivated, 1 refused, 1 Administrator left).
5. Waits are not truly bounded on failure: `with ThreadPoolExecutor` waits
   for hung workers on exit, and 30 sequential `result(timeout=30)` add up;
   a hang ends only at pytest's 60 s timeout.
6. `real_checks <= 10` could be `== 10` (exactly 10 slots are given).
7. The two-Administrator test checks A's result loosely (either label).
8. The "same answer" failure message shows only status codes, not the
   differing text, so a failing round would be hard to diagnose.
9. The "app on this PostgreSQL database" override repeats one in
   `test_notify_resend.py`; belongs in conftest.
10. Type hints missing on some test parameters (CLAUDE.md).
