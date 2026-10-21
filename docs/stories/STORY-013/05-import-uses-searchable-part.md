# 05: The classified-master import uses the same prefix rule

Status: done
Triage: ready-for-agent
Parent: STORY-013
Blocked by: 01

**What to build:** the classified-master import (Snapshot page, "Master ที่
จัดหมวดแล้ว") takes each row's searchable text with the shared rule and the
row's own Sub-Category Name Prefix, instead of "everything after the first
`" - "`", so the whole system has one prefix rule (Q11).

**First, a dry run (STORY-013 AC12):** read
`D:\dev\private\Carabao_Group_Item_Master_Central_v4.xlsx` read-only and
count the rows whose searchable text differs between the old rule and the new
one, with 5 examples. **If more than 0, stop and report to Peter before
changing the import.** The dry run writes nothing (no database, no file in
the repo).

- [x] Dry-run result reported: number of differing rows + 5 examples
- [x] Only if 0 (or Peter decides): the import uses the shared rule
- [x] An import of a file with prefixed names gives the same searchable text
      as before
- [x] A row whose name does not start with its Sub-Category's prefix keeps its
      whole name as searchable text
- [x] The import still rejects invalid coded rows as today (existing tests
      pass unchanged)

## Notes

### Dry run (2026-10-20), before any import change
Read-only over `D:\dev\private\Carabao_Group_Item_Master_Central_v4.xlsx`
through `check_labeled_master` (no DB, no writes; the file's sha256 is the
same before and after), with ticket 01's `searchable_part(name, prefix)` and
each row's prefix from `app/data/taxonomy.json`:
- rows: 13,391 read, 13,391 valid, 0 skipped, 0 invalid
- rows whose Sub-Category is not in the taxonomy: 0
- **rows whose searchable text differs from the old rule: 0** (no examples
  to show)
- check that the comparison did something: all 13,391 names start with
  their own Sub-Category's prefix, and the old rule cut a prefix off all
  13,391.
Import code not changed until Peter saw this (2026-10-20: "dry-run ได้ 0 →
เปลี่ยน import ไปใช้ searchable_part ได้เลย").

### The change (2026-10-20)
- `check_labeled_master(filename, data, prefixes)` cuts the row's own
  Sub-Category prefix with `naming.searchable_part`; without `prefixes`
  nothing is cut (callers that only check codes are unchanged).
- `import_labeled_master` passes `central_prefixes(db)`: (group, sub) →
  Name Prefix from the central taxonomy in the database (seeded from
  `app/data/taxonomy.json`).
- **Tests:** `tests/test_master_searchable.py`, 5. Written first: the two
  rows where the rules differ (another category's prefix, a Name Override
  without one) failed; the three where they agree passed. Old tests: none
  changed. Suite: 755 passed.
- **Mutation check:** not passing the prefixes (2 fail, incl. the old
  `test_import_labeled_master_strips_category_prefix`), the old rule back
  (2 fail).

## Code review (2026-10-20)

Ran `/code-review` on the uncommitted diff. 8 findings; same sorting
((ก) wrong data / someone acting who should not / data lost / AC not met;
(ข) note). Peter's decisions: (ก) 1 → option (a); fixed 4, 6, 7, 8; 2, 3, 5
not changed.

### (ก) Must fix
1. **A row whose Sub-Category the portal does not know keeps its whole name,
   CATEGORY included, as searchable text, silently.** `_code_problem` checks
   only that the code's digits match the row's group/sub, not that the
   Sub-Category exists in the portal's taxonomy. The old rule cut such a
   prefix anyway; the new rule has no prefix to cut. Duplicate search and
   category suggestion then see `bearing ...` in every row of that
   Sub-Category. Not in today's file (dry run: 0 rows outside the
   taxonomy), but it is the first thing a new Sub-Category in the group
   master would hit. Options:
   - (a) refuse the file, like an invalid code: "หมวด 900-27 ไม่มีใน
     taxonomy ของระบบ" (a code under a Sub-Category the portal does not know
     cannot be issued or overridden here either);
   - (b) import it, cut with the old rule for those rows only, and list them
     in the upload result;
   - (c) import it whole, and list them in the upload result.
   **Recommend: (a)**, with a test (also closes finding 6).

### (ข) Notes
2. **A prefix renamed in the taxonomy while the master file still has the
   old one keeps the whole name.** The review assumed admins edit prefixes
   on a page; they cannot (only `taxonomy.json` + seed). Same effect as 1
   for a renamed prefix; (a) does not catch it. **Recommend: no change**:
   taxonomy and master come from the same group standard, and the queue's
   standing warning (ticket 01) shows the mismatch on requests.
3. **`prefixes` is optional and "None" means "cut nothing".** Making it
   required would change 3 calls in `tests/test_master_upload.py` (old
   tests). **Recommend: no change**: only the import reads the searchable
   text.
4. **`central_prefixes` does not require the parent to be a top-level
   group**, so duplicate top-level codes would overwrite each other's keys.
   **Recommend: fix** (filter on top-level parents; one line).
5. **A master prefix longer than 16 or with different spacing no longer
   matches.** Master names carry the prefix as written (they came from the
   same standard); today all 13,391 match. **Recommend: no change.**
6. **No test for a row outside the taxonomy.** **Recommend: fix** with 1.
7. **Function-local imports** in `check_labeled_master` and
   `central_prefixes`. **Recommend: fix** (module level, no cycle).
8. **`(prefixes or {})` per row.** **Recommend: fix** (once, before the
   loop).

### Outcome (2026-10-20)
- A row whose Sub-Category is not in the portal's taxonomy is an invalid row
  ("หมวด 900-27 ไม่มีใน taxonomy ของระบบ — อัปเดต taxonomy ของระบบก่อน
  อัปโหลด"), so the whole file is refused and nothing is imported. Code
  checks come first; rows without an Item Number are still skipped first.
  The real v4 file has no such row (dry run: 0 of 13,391 outside the
  taxonomy), so its upload is unaffected.
- `central_prefixes` takes top-level groups only as parents; imports at
  module level (no cycle); `prefixes` normalised once.
- 2 more tests (the unknown Sub-Category one failed first); suite 761.
- Review of the fix diff only: no correctness defects. Notes: the refusal
  header still reads "พบรหัสที่ไม่ใช่ Central Code ที่ถูกต้อง N แถว", which is
  not accurate for a row refused only for its Sub-Category (the per-row
  reason is right); not changed, for Peter to decide.
