# STORY-020: Converter from the reviewed Thai-label xlsx to taxonomy_th.json

Status: todo · Branch: none yet · Depends on: STORY-019
Triage: needs-triage

## Why
STORY-019 ships `app/data/taxonomy_th.json` empty. The wording comes back
as a reviewed xlsx (`docs/stories/STORY-019/thai-labels-draft.xlsx`, 150
rows, columns ผลตรวจ / ชื่อไทยที่แก้ / ตัวอย่างที่แก้). Writing 150 JSON
entries by hand invites a bad key or an over-long text, which stops the
seed and, in the container, the app start. The user chose (2026-11-11) a
converter instead of hand-writing.

## Scope
A command (proposed: `python -m app.import_thai_labels <file.xlsx>`) that
reads the reviewed xlsx, takes the corrected text where a row says
แก้ไข and the draft where it says อนุมัติ, runs the same checks as the
seed (`thai_labels.parse_label_file`) and writes `taxonomy_th.json`.
On a แก้ไข row with only one corrected column, the other column keeps
the draft text.

## Out of scope
- Writing to the database; the seed loads the file (HANDOFF §2 steps).
- Changing the reviewed wording.

## Acceptance criteria
To be confirmed with the user before work starts. Proposed:
- [ ] A fully reviewed file produces `taxonomy_th.json` that the seed
  loads.
- [ ] The command writes nothing if any row has no ผลตรวจ or says
  ไม่แน่ใจ, and lists those rows.
- [ ] A row that fails the seed's checks (key, length) stops the command
  with a Thai message naming the row.

## Domain rules that apply
Thai stored NFC with SARA AM recomposed (`thai_labels.clean_label`); never
NFKC. The wording is `[BUSINESS-OWNER]`'s call: the converter only copies
what was approved.

## Files likely touched
A new `app/import_thai_labels.py`, `app/services/thai_labels.py`,
`app/data/taxonomy_th.json` (output), a new test file, HANDOFF §2.

## Plan
Not yet confirmed by the user. Open question for `[BUSINESS-OWNER]`:
if only some rows are approved (for example 140 of 150), may the
approved rows be loaded and the rest stay English, or must every row be
reviewed first?

## Notes
