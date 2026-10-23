# STORY-015: Login limit follow-ups (review notes from STORY-006 ticket 08)

Status: todo · Depends on: STORY-006 ticket 08 · Not a go-live condition (Peter, 2026-10-23: the (ข) notes go to the backlog)
Triage: needs-triage

## Why
The login limits (10 failures per Account, 50 per client IP, "being
checked" slots, STORY-006 tickets 07–08) passed three code reviews with no
open (ก). These (ข) notes were left: each needs a rare race, a cost change,
or is tidiness. Collected here so they are not lost.

## Scope (pick per item at triage)
Timing (AC6: a locked or wrong case must not be told apart by time)
1. A full or locked Account is checked against a dummy hash at the current
   Argon2 cost; an Account whose own hash still has an older cost (cost
   raised, not yet upgraded) answers faster while unlocked, so time shows
   the lock. Only after a cost change. (ticket 08, 2nd review, 3)
2. A deactivated Account whose hash changes during the check still gets the
   re-check: a right guess costs two hashes, a wrong one one. Add
   `account.active` to the re-check guard. (3rd review, 3)

Counting
3. A hash that changes again during the re-check refuses a right password
   through the wrong-password path, counting a failure on the Account and
   the IP. Refuse without counting. (3rd review, 1)
4. A password changed by its owner during an old-password login costs that
   login a second hash before it is refused. (3rd review, 4)
5. An Account at 9 failures + 1 being checked refuses the owner's right
   password until that check settles, and counts it on the owner's IP.
   (2nd review, 6)
6. A count full of logins being checked (no block set) answers 429 "wait 15
   minutes" and writes no `login_ip_blocked` line; the CLI calls that IP "not
   blocked". Give it its own short message and a log line. (1st review, 2 / 7)
7. Slots have no identity: on expiry all are cleared, including live ones
   (accepted impact in HANDOFF §2; exact fix: one row per slot, new table).
   (2nd review, 1 / 8)

Robustness and tidiness
8. Only `Exception` is caught around the hash upgrade; a `BaseException`
   (interrupt) after the settling commit, or a failing `rollback()` there,
   reaches the error path and frees the slots a second time. Catch
   `BaseException`, or move the upgrade out of the guarded block. (3rd
   review, 2)
9. The prune's expiry boundary (`pending_since < now - 1 min`) differs from
   `_pending` (`>= 1 min`), and a row with slots but no `pending_since` is
   never pruned. (3rd review, 5)
10. `_free_slots_after_error` locks IP then Account by hand instead of
    `_lock_rows`; the re-check calls `verify_password` instead of
    `_verify`. (3rd review, 6 / 7)
11. `unblock_ip` leaves `window_started_at`; an expired block whose row still
    counts ≥ 50 cannot be cleared by the CLI. (1st review, 8)

## Out of scope
- Changing the limits themselves (10 / 50 / 15 minutes).

## Acceptance criteria
_(at triage)_

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
