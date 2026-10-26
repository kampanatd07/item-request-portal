# 05: Postgres race: two resends send one email; a notifier that cannot lock gives up

Status: in-progress (CI proved the flake fix; review running)
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

## CI red on `8d72f07` (2026-10-26)

(An earlier "green, 933" message was sent before Peter looked at the run;
the real result was red.) Two problems:
1. `test_a_status_email_whose_row_stays_locked_is_recorded_for_resend` hung
   to the 60 s timeout in `_record_failure`'s commit. Cause (from the code):
   after both claims hit 55P03 and rolled back (ending the claim's `SET
   LOCAL`), `_record_failure` INSERTs a `notify_failed` event whose foreign
   key needs a KEY SHARE lock on the request row; the test's FOR UPDATE holder
   blocks it, with no lock_timeout, and the holder is released only after the
   notifier returns. In production: a notifier that gave up on a row held
   FOR UPDATE for over 2 × 30 s then waited on it without limit. Since
   STORY-002.
2. The three-Administrator cycle test (`test_pg_account_race.py`, 5th) shows
   F although it passed on `0be8445`; the error text was lost because the
   thread timeout method ended the process. Nothing the cycle test runs
   changed since `0be8445` (it does not use `Race`); cause not found yet.

Peter's decisions (2026-10-26): (1) `_record_failure` gets a lock_timeout in
its own transaction; on timeout a warning, no raise (app change approved);
decisions.md records that every notifier transaction taking a lock or
writing has a lock_timeout. (2) The status lock-timeout test (new in this
ticket) split in two and run in a worker thread with a bound (approved).
(3) CI runs `pytest -ra -o timeout_method=signal --durations=10`, so a hung
test fails alone and every failure is printed. If the cycle test still
fails, analyse its error; no expectation change without asking.

- Status email, holder keeps the row: `failed` within the bound (2 claims +
  the record, about 3 s), both claims 55P03, no `notify_failed` row, one
  warning whose error is 55P03, and the change is on the resend list once
  older than `LOST_AFTER`.
- Status email, holder lets go right after the notifier gave up:
  `notify_failed` "ระบบไม่ว่าง" recorded for the change.
- The `created` lock-timeout test also runs in a bounded worker thread now.
- Local: 898 passed, 36 skipped.

CI on `f429488` (Peter, 2026-10-26, from the run itself): green, **934
passed, 0 skipped**. The three-Administrator cycle test
(`test_pg_account_race.py`, 5th) passed this time; it failed on `8d72f07`
with no error text and nothing it runs had changed: **possibly flaky**. The
review of this round also looks at that test for anything that can pass on
one run and fail on another.

## Code review of this round (2026-10-26)

Ran `/code-review` on `8d72f07..f429488`, plus the cycle test and its
helpers (Peter). 9 findings. The first explains the flaky cycle test; fixing
it changes an existing test (ticket 04's), so it waits for Peter.

### The cycle test flake (test only; waiting for Peter)
1. **When B is refused, nothing rolls B back, so B keeps its locks and C
   waits behind them.** The cycle test submits the actions bare, not through
   `_rolled_back_on_error` as `Race` does. After A commits, whichever of B
   (a2→a3) and C (a3→a1) gets a1's lock first decides the run: if C wins, C
   commits, then B is refused: pass. If B wins, B locks a1 and a3, is
   refused (`PERMISSION_CHANGED`) and keeps both locks open; C waits on a1
   until the test's `finally`, and `_all_done` fails after 15 s. About half
   the runs: red on `8d72f07`, green on `0be8445` and `f429488`, no code
   change. Production is not affected: a request's session is rolled back
   when the request ends (STORY-016 item 5 notes the locks are held until
   then).
2. With 1, the `finally` rolls back and closes C's session from the main
   thread while C's worker may still be using it, which can hide the real
   assertion or hang (fits "F with no error text").

### (ข) Notes
3. `_record_failure` now logs *every* failure as a warning (was an error):
   a real failure (connection lost, constraint) drops to WARNING too.
   Recommend: warning only for a lock timeout (55P03), `log.exception` for
   the rest.
4. In `notify_created`'s error path, `_record_failure` runs once per claimed
   request; each can now wait a full lock_timeout (20 requests × 30 s).
   Recommend: stop recording after the first lock timeout (the rest are
   owed anyway).
5. After both claims time out on a row someone holds, recording the failure
   almost always times out too (same row): about 90 s instead of 60 s, and
   the reason is lost anyway. The root is FOR UPDATE vs the foreign key's
   KEY SHARE; FOR NO KEY UPDATE in `_get_locked` / `export_pending` would let
   the record through (rejected as too large in decisions.md 2026-10-26).
6. `_bounded` leaves a timed-out worker running; non-daemon threads are
   joined at interpreter exit, so a hang could keep CI running to its 20
   minute limit.
7. `if holder.is_active:` never filters (a closed Session reports active);
   harmless now.
8. A third copy of "run bounded in a worker" (`Race`, `_all_done`,
   `_bounded`); one shared helper in `pg_race.py` would do.
9. CI uses the signal timeout, local Windows the thread one; a hang in a
   worker thread can still lose the error text locally.

## Fix of this review (2026-10-26)

Peter's decisions (2026-10-26): fix the cycle test (an existing ticket 04
test; expectation unchanged) and prove it with a test that forces B before C:
it must fail on the old harness and pass on the fixed one. Fix note 3 (log
level) with tests. Note 4 → STORY-016; notes 5–9 → STORY-015 (items 12–16).

- **How the failure on the old harness is shown** (no PostgreSQL here, so in
  CI): two pushes, two runs. `2db6a41` moves the cycle into `_run_cycle(engine,
  b_first)` *unchanged* and adds
  `test_three_administrators_in_a_cycle_when_the_refused_one_goes_first`: C
  starts only after B is seen waiting in `pg_stat_activity`, so B is first in
  line for a1's row (PostgreSQL queues row-lock waiters in order: the first
  waiter holds the tuple lock while it waits). Expected on that run: **934
  passed, 1 failed** (that test, "1 call(s) still running after 15 s"). The
  next commit fixes the harness: expected **all green**.
- Harness fix: all three calls go through `_rolled_back_on_error` (a refused
  call gives its locks back at once); `finally` releases A, waits for every
  thread within the bound, and closes the sessions only when all are done,
  as `Race` does. Both cycle tests keep the same expectation.
- `_record_failure`: warning only when the error is a lock timeout (SQLSTATE
  `55P03`, `LOCK_NOT_AVAILABLE`), `log.exception` for anything else.
  `tests/test_notify_record_failure.py` (3, SQLite): 55P03 → WARNING; a
  RuntimeError and an OperationalError of another kind → ERROR, each with
  its traceback, never raised. The PostgreSQL "stays owed" test still sees
  one WARNING carrying 55P03.
- Local: 901 passed, 37 skipped.

**Proved in CI (Peter, 2026-10-26, from the runs):** `2db6a41` red as
expected, **934 passed, 1 failed**: the forced-order test, "still running
after 15 s". `c3055e7` green, **938 passed, 0 skipped**. The forced order
fails on the old harness and passes on the fixed one.
