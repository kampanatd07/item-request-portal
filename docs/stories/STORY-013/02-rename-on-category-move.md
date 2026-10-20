# 02: A category move swaps the Name Prefix in the Item Name

Status: done
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

- [x] `A_PREFIX - name - detail` → `B_PREFIX - name - detail` (STORY-013 AC1)
- [x] A Name Override that starts with the old prefix keeps its name and
      detail parts (AC2)
- [x] The old prefix is matched without case; the new one is written in upper
      case (AC3)
- [x] New name > 110 characters: refused, Thai message with the length; group,
      Sub-Category, name, code and register unchanged; no events (AC5)
- [x] Events in order `category_changed` → `name_prefix_changed` →
      `code_reissued` (if any); history label "เปลี่ยน prefix ตามหมวด" (AC6)
- [x] An Administrator's move of a coded `approved` request re-issues the code
      and renames the prefix (AC7)
- [x] The response updates the name panel too (AC8)
- [x] Procurement types a name → category move → the Requester edits the size
      and resubmits → the replaced-name warning still shows (AC10)
- [x] Allowed old-test change (Q9): `tests/test_categorizer.py:178` from "last
      event is `category_changed`" to "`category_changed` is among the
      events"; no other existing test changed without asking

## Notes (2026-10-20)

- `naming.swap_prefix(name, old, new)`: the name with `old` replaced by `new`
  (as written), or None when the name does not start with `old` (ticket 03
  handles that case; here the name is simply left alone).
- `change_category` works out the new name **before** changing anything; a
  name over 110 is refused with "ย้ายหมวดไม่ได้: ชื่อสินค้าจะยาว N ตัวอักษร
  (เกิน 110) … แก้ชื่อให้สั้นลงก่อน แล้วค่อยย้ายหมวด", so no category, code or
  register change. Events: `category_changed` → `name_prefix_changed`
  (`old → new`) → `code_reissued`.
- `name_prefix_changed` is its own action, so ticket 05's replaced-name rule
  (only `name_edited` and a `request_edited` name line set a name) skips it.
- The category move answers with `partials/category_moved.html`: the
  category panel plus the name panel out of band (`hx-swap-oob`), with
  ticket 01's warning recomputed.
- Category learning still gets the renamed name whole; ticket 04 cuts the
  prefix.
- **Tests:** `tests/test_category_rename.py`, 13 (all failed first). Old
  test changed (allowed, Q9): `tests/test_categorizer.py:178`, "last event
  is category_changed" → "category_changed is among the events". Suite: 774.
- **Mutation check:** no length check (3 fail), logging the rename as
  `name_edited` (3 fail), the length check after the move (1 fail: the coded
  move's register).

## Code review (2026-10-20)

Ran `/code-review` on the uncommitted diff. 7 findings. **No (ก).** Peter:
fix 1, 4, 6, 7; not 2, 3, 5; plus two additions (below).

1. **A move into a Sub-Category without a Name Prefix drops the CATEGORY
   part** (`BEARING - ตลับลูกปืน - 6204` → `ตลับลูกปืน - 6204`). That is what
   `compose_name` gives a new request in such a category too, so it is
   consistent; all 130 Sub-Categories have a prefix today (the seed guard
   checks length, not presence). **Recommend: keep the behaviour, pin it with
   tests** (with 7).
2. **Learning gets the renamed name with the new prefix** until ticket 04.
   **Recommend: no change here** (ticket 04 is next but one).
3. **A name already over 110 cannot be moved even when the swap shortens
   it.** Only a Name Override can be over 110 today; ticket 06 stops new
   ones. The spec says refuse when the new name is over 110. **Recommend: no
   change.**
4. **`swap_prefix` repeats the cut** that `searchable_part` does.
   **Recommend: fix** (build on it).
5. **`name_prefix_changed` uses ` → `; `name_edited` and `category_changed`
   use ` -> `.** ` → ` is the spec's format (Q3) and the `request_edited`
   lines'. **Recommend: no change.**
6. **Function-local imports of `naming` in `change_category`.**
   **Recommend: fix** (module level; no cycle).
7. **No test for a move into or out of a Sub-Category without a prefix.**
   **Recommend: fix** with 1.

### Outcome (2026-10-20)
- 1 + 7: pinned with tests: a move into a Sub-Category without a prefix
  drops the CATEGORY part (as `compose_name` would); a move out of one
  leaves the name and writes no `name_prefix_changed`.
- 4: `swap_prefix` builds on `starts_with_prefix` / `searchable_part`.
- 6: `naming` imported at module level in requests.py (no cycle).
- Added (Peter): the seed also refuses a central Sub-Category with an empty
  Name Prefix ("Name Prefix ว่าง"), since every Item Name must have a
  CATEGORY part; the shipped taxonomy has none, so the seed still passes.
- Added (Peter): ticket 05's refusal message counts the two kinds apart:
  "พบรหัสที่ไม่ใช่ Central Code ที่ถูกต้อง N แถว" and "พบหมวดที่ระบบไม่รู้จัก N
  แถว" (`InvalidRow.kind`).
- 7 more tests (5 failed first; the 2 pins passed, as pins do). Suite 781.
  Mutation: no empty-prefix check (3 fail), one count for both kinds (2 fail).
- Review of the fix diff only: no correctness defects. Notes: a taxonomy row
  without `group`/`sub` would raise KeyError, not SeedError (no such row).
