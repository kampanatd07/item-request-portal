# STORY-005: Re-sync the running register

Status: blocked — waiting for Peter to fill `Carabao_Item_Master_Decision_Sheet.xlsx` (D1–D4)

## Why
The register was seeded from `Carabao_Item_Master_Running_Number_Register_v1.xlsx`
(Aug 2026). The Decision Sheet will change which legacy items get central codes,
so the last-issued number per group+sub will move. If the portal keeps the old
numbers, it will issue codes that the final migration also issues — a collision.

## Scope
- Admin upload of an updated register file (same format as the v1 register, sheet
  `ทะเบียนเลขรัน`, columns `Item Group`, `Sub`, `เลขรันล่าสุด`)
- Preview screen: per group+sub, current value vs file value, highlighting rows
  where the file is **lower** than the current register
- Apply rule: a counter may only move forward. Lower values are rejected with a
  report, never applied
- Every change logged (who, when, old → new)
- A report of codes already issued by the portal since the last sync, so Peter
  can feed them back into the group master

## Out of scope
- Reading the Decision Sheet directly (Peter runs the group pipeline; this story
  consumes its output register)

## Acceptance criteria
1. Uploading a register never moves any counter backwards
2. Preview shows exactly what will change before anything is written
3. Export of portal-issued codes since a date, as xlsx
4. Tested with a register that has higher, equal and lower values

## Files likely touched
`app/services/codegen.py` or new `app/services/register.py`, `app/routes/admin.py`,
new templates, tests

## Domain rules that apply
HANDOFF §6.4 — the register is the single owner of numbers.

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
