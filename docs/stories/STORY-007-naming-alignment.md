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
