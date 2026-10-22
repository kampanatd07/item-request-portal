# 03: Postgres race: Approval or re-categorise against an export of the same request

Status: done (2026-10-22)
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01

**What to build:** proof on real PostgreSQL row locks (AC 4, STORY-001
ticket 03) that an export of a Plant's approved requests and a change to one
of those requests (a re-categorise, which can re-issue the code, or an
Approval landing while the export runs) never interleave: the loser waits,
re-checks status after it gets the lock, and no exported request ends up
with a code different from the one in its export file.

- [x] Export holds the rows, re-categorise waits: after the export commits,
      the re-categorise sees the request is exported and is refused as the
      existing rules say; the request's code equals the code in the file
- [x] Re-categorise holds the row, export waits: the export includes the
      request with its new code (or leaves it out if its status changed),
      and the file matches the database
- [x] An Approval committing while an export waits on the rows: the result
      follows the re-check after the lock (in the batch with its code, or
      not in it), never in the file with a different code
      **Changed (Peter, 2026-10-22):** an export never waits on an Approval
      (it locks only rows already committed as approved), so the test proves
      the export does not wait, R2 is not in that batch, and the next export
      carries R2 with the same code
- [x] Waiting is checked; waits bounded
- [x] No production code change unless a test shows a real race; if one
      does, stop and tell Peter before fixing. No migration

## Notes (2026-10-22)

**Checked first (Peter):** the export marks exactly the rows it locked, not
a conditional UPDATE. `export_pending` selects the Plant's `approved`,
unexported rows `FOR UPDATE`, re-checks each after the lock, and sets
`status`/`export_batch_id` per object (UPDATE by id); the download builds the
file from `export_batch_id`. So "exported" and "in the file" are the same
rows; no bulk `update(ItemRequest)` exists in `app/`.

`tests/test_pg_export_race.py`, 3 tests (PostgreSQL only). R1 approved in
APM 900-01; the move is to 900-02 (same Item Group). "The file" is the
batch's workbook built as the download builds it.
1. Export holds, move waits: refused "เปลี่ยนหมวดไม่ได้หลัง export แล้ว"; R1
   exported in the batch with its code, which is in the file; 900-02
   register unchanged; nothing retired.
2. Move holds, export waits: R1 exported with the new 900-02 code; the file
   has the new code, not the old; the old code retired `reissued`.
3. Approval of R2 holds, export must **not** wait (Peter: test it this way):
   the export locks only rows committed as approved, so it finishes while
   the Approval holds. R2 not in that batch (`export_batch_id` empty, still
   approved, its code not in the file); the next export has R2 with the
   same code in its file. New helper `Race.run_without_wait`. If CI shows the
   export waiting here, stop and report.
Review notes from ticket 02 applied to this file: type hints, codes built
with `central_code`, checks limited to this test's requests and codes. No
production code change, no migration.

## Code review (2026-10-22)

Ran `/code-review` on `ba5fc9c..abf3e33`. 8 findings, sorted as before
(**(ก)** wrong data, someone acting who should not, data lost, or an
acceptance criterion not met; **(ข)** a note). **No (ก).**

### (ข) Notes — not changed (Peter: fix only (ก))
1. **Timers in `run_without_wait` (and `run`) both use 15 s.** If B really
   blocks, A's hold also runs out at about 15 s and raises inside
   `before_commit`; A's transaction stays open and B stays blocked until the
   test's database is dropped `WITH (FORCE)` in teardown. The reviewer called
   it a hang to the 60 s timeout. Reading the code, it ends in about 30 s with
   the right message ("B did not finish…"), so the ticket 01 AC "bounded
   waits, no 60 s hang" still holds; not run to confirm. Not (ก) for that
   reason. **Recommend: fix** before 04/05 lean on it more: A's hold longer
   than B's wait, and roll A back on the failure path.
2. `run_without_wait` decides "not blocked" by B finishing in time, not by
   `pg_stat_activity`; a slow runner (> 15 s) fails it, and a B that raises
   at once passes it (the test's `isinstance` check catches that). Recommend:
   poll for `wait_event_type = 'Lock'` and fail at once if seen.
3. `_codes_in_file` rebuilds the workbook from the database after the race,
   so "the code is in the file" cannot differ from the database check; the
   real guard is that the stored code did not change (asserted). The ticket
   note "the file has the new code" overstates it. Recommend: snapshot the
   bytes right after A commits, if the file check should carry weight.
4. `_codes_in_file` copies the download route's query and plant choice
   instead of sharing a service function. Recommend: one
   `batch_workbook_bytes(db, batch_id)` used by route and test (production
   code, so its own change).
5. AC 3 text described a wait that cannot happen; now marked with Peter's
   decision above. Not covered: a **rejection** (`approved → rejected`) of a
   row the running export holds; it would wait on the row and be refused
   after the export. Recommend: add to ticket 04/05 or a later race file.
6. `run_without_wait` copies most of `run`. Recommend: one shared core.
7. `run_without_wait`'s failure path (B blocked) has no test of its own
   (CLAUDE.md: happy + failure path). Recommend: fix with 1–2.
8. Test 1 does not check that the refused move left Sub-Category, name and
   events untouched. Recommend: add those checks.

## Closed (2026-10-22)

CI on `abf3e33` (Peter): green, **823 passed, 0 skipped**. No race found, no
production code change, no migration.
