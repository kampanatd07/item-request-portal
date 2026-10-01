# STORY-010: Validate code override against the Running Register

Status: done (ready for Peter's merge, 2026-10-01)
Triage: ready-for-agent

## Why
An Administrator can override an approved request's Central Code with any
text today: no 11-digit check, no check that the Group + Sub-Category match
the request's category, and the Running Register is never told. That breaks
the rule that running numbers come only from the register (HANDOFF §6.4). A
wrong override either points a request at another item that already owns
that number in the group master, or leaves the register behind so it later
issues the same number again — and the collision only shows up in AX/D365,
after the import files have gone out. Numbers thrown away along the way
(re-issue, override, reject after approval) are also not tracked, so nothing
stops them being used again. Found while building STORY-001 ticket 03.

## Scope
- **Override has one purpose** (grilling Q1, Q6): the item already has a
  Central Code X in the group master (`New_Item_Master`) but not yet in this
  Plant's AX, so the request should carry X instead of the Y the portal issued
  at Approval, and still be exported. A duplicate found after Approval is
  handled by rejecting the request with the reason "ซ้ำกับ X ให้ใช้ X"
  (existing reject-after-approval, STORY-001 ticket 03), not by override.
- **Retired Codes**: a new table `retired_codes` (one Alembic migration) holds
  every Central Code that was issued and then thrown away, with the reason
  (`reissued`, `overridden`, `rejected`, `skipped`), request, actor and time;
  `code` is unique. Every place that throws a number away writes to it in the
  same transaction. The migration backfills it from existing
  `code_reissued`, `code_overridden` and `code_burned` events.
- **Override checks**, in order, after the Administrator-only guard and the
  `approved`-status check:
  1. a reason is required (kept in the `code_overridden` event)
  2. exactly 11 digits; digits 1–3 = the request's Group, 4–5 = its
     Sub-Category, 6–7 = `00`
  3. X exists in the classified master (`ItemSnapshot` source `CENTRAL`, the
     "Master ที่จัดหมวดแล้ว" upload, whose Item Number is the Central Code);
     the Administrator sees that item's name and confirms before saving; no
     master uploaded → override refused
  4. X is not in this Plant's own snapshot (CBD or D365) when one is loaded —
     refused with advice to reject instead; no Plant snapshot → warning only
  5. X is not a Retired Code and not used by another request
  6. X's running number above the register's last value → the register moves
     up to it (event `register_advanced`), and every number skipped on the way
     becomes a Retired Code (`skipped`); a jump of more than 10 needs an
     explicit confirmation showing how many numbers will be lost. Lower or
     equal → register untouched
  - the replaced Y becomes a Retired Code (`overridden`)
- **Classified master upload** ("Master ที่จัดหมวดแล้ว"): rows without an Item
  Number (or otherwise incomplete) are still skipped — the real file has
  pending rows with no code yet. A row **with** an Item Number that is not a
  valid Central Code for its own Category/Sub-Category codes (not 11 digits,
  digits 1–3 or 4–5 not matching, digits 6–7 not `00`) rejects the whole
  file, listing the row numbers. After a successful upload, a prominent
  warning lists every Group + Sub-Category where the master's highest running
  number is above the register's (register behind the group; fix via
  STORY-005). The upload never moves the register itself.

## Out of scope
- Moving the register from the master upload or re-syncing it from a file
  (STORY-005, which will read `retired_codes` for its report)
- A structured "duplicate of X" field on rejection (free-text reason is
  enough for now; grilling Q10)
- Overrides on legacy (non-CENTRAL) code systems — they are inactive
- Changing who may override (Administrator only, STORY-001)

## Acceptance criteria
1. Override without a reason is refused; nothing changes
2. A code that is not exactly 11 digits, whose digits 1–5 do not match the
   request's Group + Sub-Category, or whose digits 6–7 are not `00`, is
   refused with a Thai error; the request's code and the register are unchanged
3. A code not found in the uploaded classified master is refused; with no
   master uploaded, override is refused
4. A code found in this Plant's own snapshot is refused with advice to reject
   instead; with no Plant snapshot the override goes ahead with a warning.
   For APM/APG/ACM the D365 snapshot is shared and has no company column, so a
   D365 match only warns ("รหัสนี้มีอยู่ใน D365 (APM/APG/ACM) แล้ว — ระบบแยก
   ไม่ได้ว่าเป็นของโรงงานไหน ตรวจก่อน import"); CBD is still refused
   (Peter 2026-10-01; plant-aware check is STORY-012)
5. A Retired Code, or a code used by another request, is refused
6. A valid code above the register's last value moves the register up to
   exactly that number, records `register_advanced`, and retires every
   skipped number the group master does not hold (master codes are real codes
   in use and are left alone); when more than 10 numbers would actually be
   thrown away, the override is refused unless confirmed (Peter, ticket 03)
7. A valid code lower than or equal to the register's last value leaves the
   register untouched (never moves backwards)
8. After an override, the replaced code is a Retired Code (`overridden`);
   after a re-issue, the old code is (`reissued`); after rejecting an approved
   request, its code is (`rejected`) — each in the same transaction
9. The migration creates `retired_codes`, backfills it from existing events,
   and runs cleanly on a fresh DB (`alembic upgrade head` + seed)
10. A classified master with a coded row that is not a valid Central Code for
    its own Category/Sub-Category is rejected whole, naming the rows; rows
    with no Item Number are skipped as before
11. After a classified master upload, Group + Sub-Categories where the master
    is ahead of the register are listed in a warning; the register is not moved
12. Every AC has a service-level test using `central_ids()` and
    `account_for(db, "administrator")`

## Depends on
STORY-001 (done). **Must be done before STORY-006 (deploy).**

## Files likely touched
`app/models/core.py`, one migration, `app/services/requests.py`
(`override_code`, `change_category`, `change_status`), `app/services/codegen.py`
(register helpers next to `_allocate_from_register`), `app/services/snapshots.py`
(`_extract_labeled_rows`, `import_labeled_master`), `app/routes/queue.py`,
`app/routes/admin.py`, `partials/status_panel.html`, snapshot templates, tests

## Domain rules that apply
HANDOFF §6.4 — running numbers come only from `running_register`; the
register is the single owner and never moves backwards. Code layout
`[Group 3][Sub-Category 2][Item Type 2 = 00][Running 4]` (HANDOFF §3).
HANDOFF §6.5/§6.8 — batch mode for SQLite ALTERs; verify the migration on a
fresh DB. Apply the `carabao-item-master` skill (codes, register).

## Plan
Tickets in `docs/stories/STORY-010/`:
1. `01-retired-codes.md` — table, migration + backfill, written at every burn point
2. `02-master-upload-validation.md` — strict coded-row validation + register-lag warning
3. `03-override-checks.md` — service-level override rules, register advance, skipped numbers
4. `04-override-screen.md` — override form: reason, name confirmation, jump confirmation

## Notes
- AC6 (burned codes) found while closing STORY-001 ticket 03 (2026-09-29).
- Closed 2026-10-01: migration verified on a temp DB (upgrade head, seed,
  alembic check, downgrade/upgrade); whole-branch review against the 12 ACs
  passed after the pre-merge fixes. AC12 passes with a note (Peter): the
  migration and master-upload tests (AC9–11) involve no request or Account,
  so they do not use `central_ids()` / `account_for()`.

### Grilling (2026-09-30, Peter) — settled
- Q1 Override is for an item that already has a Central Code outside the
  portal (group pipeline, or issued by hand before cut-over).
- Q2 The code an override replaces is burned for good (`code_burned`-style
  record); the register never moves back.
- Q3 Retired numbers live in a new `retired_codes` table with a unique code
  (a DB constraint, not parsing event text); the migration backfills from
  existing events.
- Q4 A register jump of more than 10 numbers needs explicit confirmation
  showing how many numbers will be lost.
- Q5 Override requires a reason.
- Q6 A duplicate found after Approval is rejected ("ซ้ำกับ X ให้ใช้ X"), not
  overridden. Override remains only for "X is in the group master but not yet
  in this Plant's AX", where exporting is right.
- Q7 Numbers skipped by a register jump are retired (`skipped`) so the group
  never issues them either.
- Q8 X must exist in the group's list of Central Codes; the Administrator
  confirms against the item name. Peter: that list is the classified master
  already uploaded as "Master ที่จัดหมวดแล้ว" (`ItemSnapshot` source `CENTRAL`,
  columns Item Number / Product Name / Category Code / Sub-Category Code in
  `_extract_labeled_rows`) — no new snapshot type.
- Q9 X must not already be in this Plant's snapshot (would create a duplicate
  item in AX); no snapshot loaded → warn, don't refuse.
- Q10 No structured "duplicate of X" field; free-text reason.
- Q11 The classified master stays Administrator-only and replaces the previous
  load. Peter: rows without an Item Number keep being skipped (the real file
  has pending rows with no code); only coded rows that are not a valid Central
  Code for their own Category/Sub-Category reject the whole file, with row
  numbers.
- Q12 An upload whose master runs ahead of the register shows a prominent
  per-sub-category warning pointing to STORY-005; it does not move the
  register.
- A row with an Item Number but a blank Category or Sub-Category Code counts
  as invalid (rejects the file), confirmed by Peter 2026-09-30. Ticket 02 is
  dry-run against the real Central_v4 file (kept in `D:\dev\private\`, never
  committed) before merge.
