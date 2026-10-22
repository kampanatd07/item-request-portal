# 03: Postgres race: Approval or re-categorise against an export of the same request

Status: in-progress (waiting for CI)
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01

**What to build:** proof on real PostgreSQL row locks (AC 4, STORY-001
ticket 03) that an export of a Plant's approved requests and a change to one
of those requests (a re-categorise, which can re-issue the code, or an
Approval landing while the export runs) never interleave: the loser waits,
re-checks status after it gets the lock, and no exported request ends up
with a code different from the one in its export file.

- [ ] Export holds the rows, re-categorise waits: after the export commits,
      the re-categorise sees the request is exported and is refused as the
      existing rules say; the request's code equals the code in the file
- [ ] Re-categorise holds the row, export waits: the export includes the
      request with its new code (or leaves it out if its status changed),
      and the file matches the database
- [ ] An Approval committing while an export waits on the rows: the result
      follows the re-check after the lock (in the batch with its code, or
      not in it), never in the file with a different code
- [ ] Waiting is checked; waits bounded
- [ ] No production code change unless a test shows a real race; if one
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
