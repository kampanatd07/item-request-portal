# 01: Retired Codes — every thrown-away number is recorded

Status: done
Triage: ready-for-agent
Parent: STORY-010
Blocked by: None (can start immediately)

**What to build:** A Central Code that was issued and then thrown away can
never be used again, and the portal knows which ones those are. A new table
`retired_codes` holds one row per retired number: `code` (unique), the
request it came from, a reason (`reissued`, `overridden`, `rejected`,
`skipped`), the acting Account's email and the time. It is created in **one**
Alembic migration that also **backfills** it from existing events:
`code_reissued` (the old code in `<old> -> <new>`), `code_overridden` (the old
code) and `code_burned` (the code on a request rejected after approval). The
migration is the only one in STORY-010; tickets 02–04 are behaviour only.

Every place that throws a number away writes a row **in the same
transaction** as the change:
- re-categorising a coded request (`change_category`, reason `reissued`)
- rejecting an approved request (`change_status`, reason `rejected`; the code
  also stays on the request as today)
- overriding a code (`override_code`, reason `overridden`) — the checks on the
  new code are ticket 03

A small service helper (e.g. `retire_code(db, code, request, reason, account)`
next to the register helpers in `codegen.py`) is the only writer, and
`is_retired(db, code)` the only reader, so ticket 03 and STORY-005 reuse them.

- [x] Migration creates `retired_codes` with a unique `code`, reads cleanly,
      and runs with `alembic upgrade head` + `python -m app.seed` on a fresh
      DB (HANDOFF §6 traps 5 and 8); `alembic check` shows no drift
- [x] Backfill: a DB with existing `code_reissued`, `code_overridden` and
      `code_burned` events gets the matching Retired Codes, once (re-running
      the migration step does not duplicate)
- [x] Re-issue, reject-after-approval and override each write exactly one
      Retired Code with the right reason and actor, in the same transaction
      (a failure rolls both back)
- [x] A refused action (e.g. Procurement trying to re-categorise a coded
      request) writes nothing
- [x] Retiring the same code twice is refused by the unique constraint and
      reported as a Thai error, not a 500
- [x] Tests use `central_ids()` and `account_for(...)`

Implementation notes (2026-09-30):
- `retire_code` adds to the caller's session without flushing; `is_retired`
  checks pending rows in the session and queries under `no_autoflush`. Found
  by a test: flushing inside the check pushed the caller's pending new code
  out early, so a clash on another request was reported as "old code already
  retired".
- Backfill (Peter: production starts empty, so it only matters for dev.db):
  one row per code, a `code_burned` event wins as the reason, otherwise the
  first event; codes still on a live request are skipped and counted. On
  dev.db: 2 added (90701000063 overridden, 90701000064 rejected), 0 skipped.
- Code review fix, ahead of ticket 03: `override_code` already refuses a
  retired new code. Without it, overriding A -> B -> A left a request carrying
  a retired A that no reject/re-categorise/override could retire again.
- Overriding to the code the request already has is now a no-op (no event).
- Events (`code_burned` etc.) stay as the human-readable history; the table is
  what rules read.

