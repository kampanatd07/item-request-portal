# STORY-007: Align name composition with the group naming standard

Status: todo

## Why
The code renders units and punctuation differently from the approved naming
standard (Restructure Proposal §2.3). Every name issued before this is fixed
will differ from names in the central master, which weakens duplicate
detection and forces a rename later. Peter confirmed the standard's form on
2026-09-28.

## Scope
- `normalize_size`: millilitre renders as `mL` (was `ml`); inch renders as
  `N in` (was `N"`). All input spellings (`มล.`, `ml`, `ML`, `นิ้ว`, `inch`,
  `IN`, `"`) map to the new form.
- `compose_name`: remove every `,` from all segments, spaced or not
  (`ชุดตรวจ ,Funnel` → `ชุดตรวจ Funnel`, `1,000` → `1000`).
- `/` stays allowed inside a spec when unspaced (`208 L/Drum`); spaced ` / `
  keeps being removed.

## Out of scope
- Renaming names already stored on existing requests.
- Word-order enforcement (noun before modifier) — stays enforced by field order.
- Abbreviation Dictionary enforcement (needs the full 52-term list first).

## Acceptance criteria
1. `normalize_size("500 มล.") == "500 mL"`; `normalize_size("500ml") == "500 mL"`.
2. `normalize_size("4 นิ้ว") == "4 in"`; same for `4นิ้ว`, `4 inch`, `4 IN`, `4"`.
3. `normalize_size("10 mm. x 20 mm.") == "10x20 mm"` still holds.
4. `compose_name` output never contains `,`.
5. `compose_name(..., size="208 L/Drum")` keeps `208 L/Drum`.
6. Full suite passes; existing expectations in `tests/test_units_and_category.py`
   updated to the new form (`4"` → `4 in`, `500 ml` → `500 mL`).

## Files likely touched
`app/services/units.py`, `app/services/naming.py`,
`tests/test_units_and_category.py`, `tests/test_naming.py`

## Domain rules that apply
HANDOFF §6.1 (no `\b` next to Thai or between digit and letter — the inch
pattern `\bin\b` must not start matching inside words like `pin`, `inlet`).
Skill `carabao-item-master` §3.

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes

- From STORY-009 ticket 01 (2026-10-16): a Base Name that cleans to nothing
  (`"--"`, `"(ยกเลิก)"`) is accepted when a brand or model is given; the
  brand then becomes the name part (`BEARING - SKF`). That breaks the
  noun-first rule: the name has no head noun, and "noun before modifier is
  enforced by field order" (Scope) does not hold. Reject it in
  `compose_name` ("กรุณากรอกชื่อเรียกสินค้า"). The Base Name is stored as
  NULL in that case today.
- Also from STORY-009 ticket 01: the Base Name, Item Name and other name
  parts are not NFC + fix_thai normalised on submit (only the originator
  name is; HANDOFF §6.2). Changing it changes Item Names, so decide it here.
  The same holds for a Name Override (`edit_name`, STORY-013 ticket 06
  review): it is stored as typed, so a pasted decomposed SARA AM counts
  as two characters against the 110 cap and is exported decomposed.
- From STORY-013 (Peter, 2026-10-20): a **Name Override** (an Item Name
  Procurement types in the queue, `edit_name`) is checked for nothing but
  empty and, from STORY-013 ticket 06, length ≤ 110. The other naming rules
  `compose_name` enforces (no `,`, `--`, ` : `, ` / `, `=`, `|`, no
  `(ยกเลิก)`, number + unit spaced, ` - ` the only separator, segment lengths)
  do not apply to it, so a Name Override can reach the AX/D365 export
  breaking them. Decide here which of these rules a Name Override must obey,
  and whether it is refused or cleaned.
- From STORY-013's closing review (Peter, 2026-10-21): a Name Override can
  carry its CATEGORY in mixed case (`Seal - O-ring 20 mm`) and is exported
  that way; the standard writes CATEGORY in upper case. A category move now
  upper-cases a fitting prefix (STORY-013), but an override typed in mixed
  case and never moved is not touched. Also: a `,` without spaces
  (`PIPE, FITTING`) is not removed by `clean_part` (only ` , ` is), so the
  "no `,`" rule holds neither for names nor for Name Prefixes in
  `taxonomy.json` (the seed guard refuses only what cleaning would change).
