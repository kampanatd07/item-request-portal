# 02: Classified master upload — valid codes only, and say when the register is behind

Status: in-progress (built; dry run on the real file pending)
Triage: ready-for-agent
Parent: STORY-010
Blocked by: None (can start immediately)

**What to build:** The classified master ("Master ที่จัดหมวดแล้ว" on the
Snapshot page, `import_labeled_master`, `ItemSnapshot` source `CENTRAL`)
becomes the trusted list of the group's Central Codes that override checks
against (ticket 03), so it must only hold valid codes, and the upload must
say when the group is ahead of the portal's register.

- Rows without an Item Number (or otherwise incomplete) are **skipped as
  today** — the real file has pending rows that have no code yet.
- A row **with** an Item Number that is not a valid Central Code for its own
  Category Code / Sub-Category Code — not 11 digits, digits 1–3 ≠ Category
  Code, digits 4–5 ≠ Sub-Category Code, or digits 6–7 ≠ `00` — rejects the
  **whole file**, and the Thai error lists the sheet row numbers (first few
  plus a count if many). Nothing is imported; the previous load stays.
- A row with an Item Number but a blank Category or Sub-Category Code, or a
  blank Product Name, is **invalid** and rejects the file (confirmed by Peter
  2026-09-30: override needs the name to confirm against). If the dry run
  finds coded rows with a blank name in the real file, report them to Peter
  before deciding anything.
- Codes and category codes must be ASCII digits 0–9; Thai numerals or
  fullwidth digits make the row invalid.
- After a successful upload, the result shows a prominent warning listing
  every Group + Sub-Category where the master's highest running number
  (digits 8–11) is above the register's `last_running`, with both numbers
  and the gap, pointing to STORY-005 (register sync). No warning when the
  register is level or ahead. The upload **never moves the register**.
- Category suggestion keeps working from the same rows (unchanged).

- [x] A file with a coded row whose code is 10 digits, has wrong digits 1–3,
      wrong digits 4–5 or non-`00` digits 6–7 is rejected whole, naming the
      rows; the previous CENTRAL load is still there afterwards
- [x] Rows with no Item Number are skipped and do not cause rejection
- [x] Numbers stored as Excel numbers (not text) are read as the same
      11-digit string
- [x] The warning lists exactly the sub-categories where the master is ahead
      of the register, with register value, master value and gap; none when
      level or behind
- [x] The register is unchanged after any upload
- [x] Only Administrators reach the upload (already guarded; keep a test)
- [ ] **Before merge — dry run on the real file** (Peter puts
      `Carabao_Group_Item_Master_Central_v4.xlsx` in `D:\dev\private\`, outside
      the repo; never committed): run the validator read-only and report total
      rows / valid / skipped (no Item Number) / invalid, 5 example invalid rows,
      and the sub-categories where the register is behind the master. Nothing
      is written to `dev.db`.

Implementation notes (2026-09-30):
- `check_labeled_master(filename, data)` reads without writing (counts total /
  valid / skipped / invalid with sheet row numbers); `import_labeled_master`
  refuses the whole file on any invalid row before deleting the old load.
- `register_lag(db, item_numbers)` / `central_register_lag(db)` are read-only;
  the upload result lists lagging sub-categories. The register is never written.
- Excel numbers are read as text: an integral float (`9.0001000002E+10`) is
  the same code as `"90001000002"`.
- Code review: digits must be ASCII 0–9. `\d` / `isdigit()` accept Thai
  numerals; a mixed code like `๙๐๐๐๑00๐๐๐๑` with a Thai category passed every
  other rule and would have been stored as a code that never matches a real one.
- Dry-run script kept outside the repo (scratchpad), reads the file and dev.db
  read-only.

