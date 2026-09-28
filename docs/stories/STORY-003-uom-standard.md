# STORY-003: Adopt the 24-unit UoM standard

Status: todo

## Why
The app still seeds 5 legacy units (`Pcs`, `PC`, `Set`, `Job`, `JOB`). The group
standard (`docs/group-standard/Carabao_Item_Master_UoM_Standard_v1.md`) defines 24
units and distinguishes Base UoM from Purchase UoM. Wrong UoM means wrong PO
quantities from the very first order.

## Scope
- Seed the 24 standard codes: EA, SET, PAIR, PK, BOX, BAG, BTL, CAN, DRUM, ROLL,
  SHT, REAM, M, YD, L, ML, GAL, KG, G, JOB, HR, DAY, MTH, YR
- Alias the legacy codes to them: Pcs/PC/ชิ้น/อัน/ตัว/ใบ → EA, Set/ชุด → SET,
  Job/JOB/งาน/ครั้ง → JOB (use the existing `UomAlias` mechanism)
- Deactivate the legacy codes after aliasing
- Request fields: `base_uom` (required), `purchase_uom` (required, defaults to base),
  `pack_size` (decimal), `pack_uom`
- Rule: if `purchase_uom != base_uom` then `pack_size` is required
- Default suggestion: Item categories → EA, Service categories → JOB (from the
  sub-category's `product_type`)
- Export builders write base/purchase/pack fields where the plant template has them

## Out of scope
- The 118-decision UoM confirmation exercise for existing items (that is data
  work in the group master, not this app)
- Unit conversion arithmetic

## Acceptance criteria
1. Only the 24 codes are selectable; typing `pcs` or `ชิ้น` normalizes to `EA`
2. Submitting purchase ≠ base without pack size is rejected with a Thai message
3. Existing requests with legacy UoM are rewritten to the standard code by a data
   migration (reversible)
4. Export header parity tests (`tests/test_export.py`) still pass
5. Choosing a Service sub-category preselects JOB; an Item sub-category preselects EA

## Files likely touched
`app/seed.py`, `app/models/core.py` (ItemRequest fields), `app/services/requests.py`,
`app/services/config_admin.py`, `app/services/exporter.py`,
`app/templates/request_form.html`, new migration, tests

## Domain rules that apply
HANDOFF §6.1 (no `\b` near Thai in any new alias regex), §6.5, §6.8.
`canonical_uom()` deliberately refuses to merge ambiguous look-alikes — keep that.

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
