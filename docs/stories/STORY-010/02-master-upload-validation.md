# 02: Classified master upload — valid codes only, and say when the register is behind

Status: todo
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
- **To confirm with Peter before building:** a row with an Item Number but a
  blank Category or Sub-Category Code is treated as invalid (cannot be checked
  against its category) rather than skipped.
- After a successful upload, the result shows a prominent warning listing
  every Group + Sub-Category where the master's highest running number
  (digits 8–11) is above the register's `last_running`, with both numbers
  and the gap, pointing to STORY-005 (register sync). No warning when the
  register is level or ahead. The upload **never moves the register**.
- Category suggestion keeps working from the same rows (unchanged).

- [ ] A file with a coded row whose code is 10 digits, has wrong digits 1–3,
      wrong digits 4–5 or non-`00` digits 6–7 is rejected whole, naming the
      rows; the previous CENTRAL load is still there afterwards
- [ ] Rows with no Item Number are skipped and do not cause rejection
- [ ] Numbers stored as Excel numbers (not text) are read as the same
      11-digit string
- [ ] The warning lists exactly the sub-categories where the master is ahead
      of the register, with register value, master value and gap; none when
      level or behind
- [ ] The register is unchanged after any upload
- [ ] Only Administrators reach the upload (already guarded; keep a test)
