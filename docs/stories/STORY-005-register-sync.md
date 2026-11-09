# STORY-005: Re-sync the running register

Status: todo — needed only if the delta runs through the pipeline (option B
in `Rule of Item/Handover 2026-11/04-pipeline-master-กลาง.md`, location in
`docs/IT-HANDOVER.md` C3); not needed if
the delta goes through the portal (option A, the portal issues the numbers
itself). Successor decides. The Decision Sheet (D1–D4) was filled and
applied on 2026-08-06, so the story no longer waits for it (HANDOFF §2).

## Why
The register was seeded from `Carabao_Item_Master_Running_Number_Register_v1.xlsx`
(Aug 2026), which refers to the final master `Central_v5_with_DCM` (13,400
codes; chain: `Decision_Sheet_v2_corrected` → group pipeline → `Central_v4` →
`Central_v5_with_DCM`). The plants still open items in the old system: items
opened after 2026-08-07 need a delta before cutover (Cutover Plan phase 1).
If that delta goes through the pipeline (option B), it moves the last-issued
number per group+sub; if the portal keeps the old numbers, it will issue
codes that the delta also issued — a collision.

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
- Reading the Decision Sheet or the delta directly (the group pipeline runs
  them; this story consumes its output register)

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

- 2026-09-29 (found in STORY-001 ticket 03, for Peter to confirm): the
  "codes issued by the portal" report must also list **burned** numbers — the
  old code of a `code_reissued` event and the code of a `code_burned` event
  (approved request rejected by an Administrator). They were issued from the
  register and must never be reissued by the group master either.
- 2026-09-30, from the STORY-010 ticket 02 dry run against
  `Carabao_Group_Item_Master_Central_v4.xlsx` — **for Peter to confirm at sync**:
  1. The seeded register is **ahead of the master** by 1–2 numbers in 5
     sub-categories the portal never issued in: `700-02` (register 415,
     master 413), `900-99` (1235 vs 1233), `901-06` (29 vs 27), `906-02`
     (149 vs 148), `908-99` (3 vs 2). The register seed
     (`Running_Number_Register_v1`) knows numbers the v4 master does not —
     perhaps items merged or dropped after the register was made. Safe
     direction (no clash), but those numbers are neither in the master nor
     retired; decide whether they are burned (retire them) or were never used.
     (`907-01`, 64 vs 62, is explained by dev.db test approvals.)
     **Partly explained (2026-10-27; checked against v5 by Claude in another
     chat, passed on by Peter):**
     - Verified: `900-99` (`90099001234` / `90099001235` = DCM `64SVSP0199` /
       `64SVSP0200`) and `908-99` (`90899000003` = DCM `64MD000292`) are DCM
       items in `Central_v5_with_DCM` but not in `Central_v4`: real codes in
       the final master, not burned, nothing to retire.
     - `700-02`, `901-06`, `906-02`: likely the same cause (DCM in v5), not
       yet verified: check against an unencrypted copy of v5.
     The dry run read v4 only because v5 is IRM-encrypted and cannot be read
     by code (HANDOFF §4).
  2. The file's `Taxonomy` sheet says **20 groups / 105 sub-categories**; the
     portal's `app/data/taxonomy.json` has **130** sub-categories (HANDOFF §3).
     Confirm which taxonomy is current before syncing.

