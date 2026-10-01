# STORY-012: Plant-aware D365 snapshot

Status: blocked — waiting for Peter: a sample D365 item export showing which
column holds the company / legal entity (APM, APG, ACM)
Triage: needs-info

## Why
APM, APG and ACM are uploaded as one combined `D365` item snapshot with no
company column, so the portal cannot tell which plant already has an item.
Found in the STORY-010 whole-branch review (2026-10-01): code override exists
for "the item has Central Code X in the group master but not yet in this
Plant's AX", yet an APM request whose X is only in APG's D365 looked like "X
is already in APM's system". Until this story ships, a D365 match only warns
("รหัสนี้มีอยู่ใน D365 (APM/APG/ACM) แล้ว — ระบบแยกไม่ได้ว่าเป็นของโรงงานไหน
ตรวจก่อน import"); CBD, which has its own AX snapshot, is still refused.
Duplicate check (search) has the same blind spot.

## Scope
- The D365 snapshot keeps the company / legal entity of every row: a new
  column on `item_snapshot` (one Alembic migration, verified on a fresh DB)
  and the importer reads it from the D365 export
- Each D365 Plant (APM, APG, ACM) maps to its company code (reference data,
  not hardcoded logic)
- Override's "already in this Plant's AX" check filters D365 rows by the
  request's company: found → refused with advice to reject (as CBD today);
  found only under another company → allowed, saying which company has it
- Duplicate check can show which company an existing item belongs to

## Out of scope
- Releasing an existing D365 product to another company from the portal
  (export files only — decisions 2026-07-24)
- CBD (separate AX snapshot already)

## Acceptance criteria
1. A D365 upload without the company column is refused with a Thai error
   naming the missing column
2. Override of an APM request: X in APM's company → refused; X only in APG's
   → allowed, with the company named in the preview
3. Re-uploading replaces all D365 rows for all companies, as today
4. Migration runs cleanly on a fresh DB (`alembic upgrade head` + seed)

## Depends on
STORY-010 (done). Peter's sample export (column name and company codes).
**Decision input:** the real AX/D365 import test in HANDOFF §7 — if importing
a code that exists in one company into another fails or creates a duplicate,
the D365 match may need to go back to a refusal regardless of company.

## Files likely touched
`app/models/core.py`, one migration, `app/services/snapshots.py`,
`app/services/requests.py` (`check_override`), `app/data/` (plant → company),
`app/templates/snapshots.html`, tests

## Domain rules that apply
HANDOFF §6.5/§6.8 (batch mode, verify migrations on a fresh DB).

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
