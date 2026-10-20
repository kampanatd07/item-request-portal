# 05: The classified-master import uses the same prefix rule

Status: ready-for-agent
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

- [ ] Dry-run result reported: number of differing rows + 5 examples
- [ ] Only if 0 (or Peter decides): the import uses the shared rule
- [ ] An import of a file with prefixed names gives the same searchable text
      as before
- [ ] A row whose name does not start with its Sub-Category's prefix keeps its
      whole name as searchable text
- [ ] The import still rejects invalid coded rows as today (existing tests
      pass unchanged)
