# 02: A category move swaps the Name Prefix in the Item Name

Status: ready-for-agent
Triage: ready-for-agent
Parent: STORY-013
Blocked by: 01

**What to build:** when Procurement (before a code) or an Administrator
(after a code, while `approved`) moves a request to another Sub-Category and
its Item Name starts with the old Sub-Category's Name Prefix, only that
prefix is replaced by the new one, in upper case; the name and detail parts,
including a Name Override, stay as they are. If the new name would be longer
than 110 characters, the whole move is refused with a Thai message giving the
length, and nothing changes (Q2; moved here from ticket 03 so there is never
a window where the prefix is swapped without the length check). The rename is
logged as `name_prefix_changed` (`old → new`) and is not a name setter for
STORY-009 ticket 05's replaced-name warning (Q3). The queue detail shows the
new name at once: the name panel is updated together with the category panel
(Q4).

- [ ] `A_PREFIX - name - detail` → `B_PREFIX - name - detail` (STORY-013 AC1)
- [ ] A Name Override that starts with the old prefix keeps its name and
      detail parts (AC2)
- [ ] The old prefix is matched without case; the new one is written in upper
      case (AC3)
- [ ] New name > 110 characters: refused, Thai message with the length; group,
      Sub-Category, name, code and register unchanged; no events (AC5)
- [ ] Events in order `category_changed` → `name_prefix_changed` →
      `code_reissued` (if any); history label "เปลี่ยน prefix ตามหมวด" (AC6)
- [ ] An Administrator's move of a coded `approved` request re-issues the code
      and renames the prefix (AC7)
- [ ] The response updates the name panel too (AC8)
- [ ] Procurement types a name → category move → the Requester edits the size
      and resubmits → the replaced-name warning still shows (AC10)
- [ ] Allowed old-test change (Q9): `tests/test_categorizer.py:178` from "last
      event is `category_changed`" to "`category_changed` is among the
      events"; no other existing test changed without asking
