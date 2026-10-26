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

## From the STORY-006 ticket 05 review (2026-10-26, notifier and test helpers)
12. After both claims time out on a row someone holds FOR UPDATE, recording
    the failure almost always times out on the same row: about 90 s per
    background notification instead of 60 s, and the "ระบบไม่ว่าง" reason is
    lost. Root: FOR UPDATE vs the foreign key's KEY SHARE; FOR NO KEY UPDATE in
    `_get_locked` / `export_pending` would let the record through
    (decisions.md 2026-10-26 judged it too large for the bug).
13. `_bounded` (`tests/test_pg_notify_race.py`) leaves a timed-out worker
    running; non-daemon threads are joined at interpreter exit, so a hang can
    keep CI running to its 20-minute limit.
14. `if holder.is_active:` never filters (a closed Session reports active);
    harmless now, misleading.
15. Three copies of "run in a worker, bounded, never wait on a hung thread"
    (`Race`, `_all_done`, `_bounded`); one helper in `tests/pg_race.py`.
16. CI uses the signal timeout, local Windows the thread one; a hang inside
    a worker thread can still lose the error text locally. Document the split
    in `pytest.ini`, or bound every thread wait.

## From the STORY-006 ticket 05 second review (2026-10-26)
17. `_record_failure` treats only PostgreSQL 55P03 as an expected busy row:
    SQLite's "database is locked" (dev) and PostgreSQL 40P01 (deadlock) /
    57014 (statement timeout) are now logged as errors. One
    `_is_lock_timeout(e)` helper, also used by the two claim paths, which
    still take any `OperationalError` for a lock timeout (a lost connection
    there reads as "busy" with no traceback).
18. `db.rollback()` in `_record_failure`'s `except` is unguarded (as before
    this ticket): if it raises, the "never raises" contract breaks and
    nothing is logged.
19. `tests/test_pg_notify_race.py` keeps its own `LOCK_NOT_AVAILABLE`; use
    `notify.LOCK_NOT_AVAILABLE`. The SQLite log-level test fakes `.sqlstate`
    instead of using psycopg's `LockNotAvailable`.
20. `_run_cycle` copies `Race`'s cleanup (see 15); its success path waits and
    shuts the pool down twice; `_admin_id` rebuilds the e-mail format instead
    of returning a3's id; with `b_first` it polls B's lock wait twice.

## From the STORY-006 part A whole-branch review (2026-10-26)
21. `FORWARDED_ALLOW_IPS` with a trailing comma (`10.0.0.0/8,`) gives an
    empty entry that `trusted_proxies()` rejects, so the app refuses to
    start (fails closed, message names `''`). Drop empty entries. Worth
    doing before part B sets the value.
    **Done** on `story/006-reset-password-cli` (2026-10-26): empty entries
    are dropped; only commas (`" , "`) count as unset. This changed an
    existing test, approved by Peter (2026-10-26):
    `test_a_value_that_is_not_an_ip_or_cidr_refuses_to_start` no longer
    lists `"10.0.0.5,"`, which moved to `test_accepted_values`. Reason: an
    empty entry left by a stray comma is a typo, not a wrong value; real
    wrong values (`"none, 10.0.0.5"`, `"10.0.0.300"`, a hostname, `*`) still
    fail closed.
22. On SQLite (dev only) `_lock_ip_row`'s `begin_nested()` is the outermost
    SAVEPOINT for a new IP; pysqlite then commits at RELEASE, so step 1 of
    a login is not atomic on SQLite. PostgreSQL is unaffected.
23. The new login-limit test files have no type hints on helpers/tests
    (CLAUDE.md). Most existing test files have none either; decide once
    whether the rule covers tests.

## From the review of the unblock log fix (2026-10-26, `2ad9b3d..7a0ec12`)
24. `setup_logging` relies on `basicConfig` being a no-op when a handler
    exists: a deploy whose root logger is at WARNING drops every
    `app.accounts` INFO line (blocked, unblocked, Account admin). Set
    `logging.getLogger("app").setLevel(logging.INFO)` explicitly.
    (Same as before the fix; main.py had the same call.)
25. `%(asctime)s` is local time while the lines carry `... UTC` times: on a
    Bangkok machine one line shows two clocks 7 h apart. Use UTC
    (`Formatter.converter = time.gmtime`) or label the time.
26. The subprocess test (`test_the_real_command_writes_who_unblocked_to_its_log`):
    no `timeout=` (a stall hangs the run until pytest-timeout's 60 s), no
    `cwd` (needs pytest run from the repo root, like the two sibling
    subprocess tests), inherits the whole `os.environ`, does not re-read the
    DB to check the block was lifted (other tests cover that through
    `run()`), and matches the exact `INFO app.accounts` prefix of
    `LOG_FORMAT`.

## Out of scope
- Changing the limits themselves (10 / 50 / 15 minutes).

## Acceptance criteria
_(at triage)_

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
