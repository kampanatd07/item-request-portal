# 04: Category suggestion learns from the renamed name

Status: done
Triage: ready-for-agent
Parent: STORY-013
Blocked by: 01, 02

**What to build:** after a category move, the correction fed to category
suggestion is the Item Name after the prefix swap, with its Name Prefix cut
off by the shared searchable-part rule (Q5, Q10, Q11), so the learned name
and the learned category agree, and the learned text has the same shape a
Requester types (no prefix). Today it learns the old-prefixed name under the
new category.

- [x] After a move, suggesting a category for the name without a prefix finds
      the new category (STORY-013 AC11)
- [x] The learned text has no Name Prefix
- [x] A name kept without a prefix (ticket 03) is learned whole
- [x] `tests/test_categorizer.py` keeps passing; if any of its assertions
      would have to change beyond the one allowed in ticket 02, stop and ask

## Notes (2026-10-20)

- `change_category` passes `searchable_part(item name after the move, the new
  category's Name Prefix)` to `learn_from_correction`, so the learned text
  has the shape a Requester types and the same cut as the master import
  (ticket 05). A name kept without a prefix (ticket 03) is learned whole.
- **Tests:** `tests/test_learn_from_renamed_name.py`, 3. The "no prefix in
  the learned text" test failed first (it learned `seal ซีลยาง…`); the two
  others passed already (fuzzy matching still found the category, and a
  kept name had no prefix to cut). `tests/test_categorizer.py` passes
  unchanged. Suite: 791. Mutation: learning the whole name → 1 fails.

## Code review (2026-10-20)

Ran `/code-review` on the uncommitted diff. 8 findings, **no (ก)**:
the two that look like gaps follow the agreed rules, so they are raised in
the story report instead of changed (changing them changes a rule).

1. **A kept name that starts with another category's prefix is learned
   with it** (`VALVE - ซีลยาง X` moved to SEAL → learns `valve ซีลยาง x`).
   This is the agreed rule (Q11: cut only the new category's prefix; a name
   that does not start with it is learned whole). **Not changed; raised in
   the story report.** Pinned with a test (6).
2. **The kept-name warning also shows when the name already starts with the
   new prefix** (same as ticket 03's finding 2). **Raised in the report.**
3. **Rows learned before this change keep their prefix; the cut is at the
   call site, not in `learn_from_correction`.** Not deployed, so no
   production rows; one caller. **No change.**
4. **An old prefix in another written form is learned with it.** Edge of 1.
   **No change.**
5. **The suggestion test passed before the fix.** **Fix:** also check the
   learned row's text and name exactly.
6. **No test for a kept name with a foreign prefix.** **Fix:** pin the
   agreed behaviour (learned whole).
7. **The new category's prefix is worked out twice.** **Fix:** once.
8. **Type hints in tests.** Peter: test files' style. **No change.**

### Outcome (2026-10-20)
- Fixed 5 (the suggestion test also checks the learned row exactly: it
  now fails without the cut), 6 (a kept name with another category's prefix
  is learned whole, pinned), 7 (the new prefix worked out once). Suite 792.
  Mutation: learning the whole name → 2 fail.
- The fix diff is 20 lines (one local variable, two tests); reviewed by
  reading it, not by a separate agent.
