# 03: A name without the old prefix is kept, with a warning

Status: done
Triage: ready-for-agent
Parent: STORY-013
Blocked by: 02

**What to build:** when a request moves to another Sub-Category but its Item
Name does not start with the old Sub-Category's Name Prefix (a Name Override
without one, or a Name Prefix edited in the taxonomy since), the move goes
ahead and the name is left exactly as it is: the system never guesses where
the category part is (Q7). The category panel shows a red warning
"ชื่อไม่ได้ขึ้นต้นด้วย prefix ของหมวดเดิม (<prefix เดิม>) — ตรวจและแก้ชื่อเอง",
and `category_changed` notes that the name did not change. The standing
warning from ticket 01 then stays on the queue detail until the name is fixed.

- [x] Name without the old prefix: moved, name unchanged (STORY-013 AC4)
- [x] Red warning on the category panel naming the old prefix
- [x] `category_changed` says the name did not change; no
      `name_prefix_changed` event
- [x] The queue detail's standing warning shows afterwards (ticket 01)
- [x] Same for an Administrator's move of a coded `approved` request (the code
      is still re-issued)

## Notes (2026-10-20)

- `change_category` returns `CategoryMove(req, kept_name_prefix)`; only the
  queue route reads it (tests ignore the return value, no old test changed).
  When the name does not start with the old prefix, the move goes ahead,
  the name is kept, `category_changed` gets a second line "ชื่อไม่ได้เปลี่ยน —
  ไม่ได้ขึ้นต้นด้วย prefix ของหมวดเดิม (BEARING)", and no
  `name_prefix_changed` is written. The category panel shows the red
  warning; the name panel (out of band) shows ticket 01's standing warning
  against the new prefix.
- As the spec says, the warning shows even if the kept name already starts
  with the **new** prefix (the standing warning then says nothing).
- **Bug found and fixed here (on master too):** after a move without a code,
  `req.group` / `req.subgroup` still held the old objects
  (`expire_on_commit=False`; only the coded path refreshed). The category
  panel drawn by the move showed the **old** category until a reload, and
  ticket 02's name panel warned against the old prefix right after a correct
  rename. Display only; the database was right. `change_category` now
  assigns the relationships (`req.group`, `req.subgroup`) instead of the ids,
  so nothing read afterwards is stale (review fix 1; this also drops the
  refresh the coded path needed before issuing the code). Test:
  `test_the_move_response_shows_the_new_category_and_no_stale_warning`
  (failed before the fix).
- **Tests:** `tests/test_category_kept_name.py`, 6 (4 failed first, 2 were
  already right after ticket 02). Old tests: none changed. Suite: 787.
- **Mutation check:** no kept prefix, no refresh: each fails tests.

## Code review (2026-10-20)

Ran `/code-review` on the uncommitted diff. 8 findings, **no (ก)**. Under
Peter's rule for tickets 03/04/06, the recommended (ข) are fixed without
asking.

1. **The refresh patches a symptom:** setting `group_id`/`subgroup_id` leaves
   the relationships stale until a reload. **Fix:** assign `req.group` /
   `req.subgroup` instead; drop both refreshes (with 5).
2. **The warning shows even when the kept name already starts with the new
   prefix**, contradicting the standing warning. This is the agreed rule
   (Q7, spec); changing it needs Peter. **Not changed; raised in the story
   report.**
3. **The `category_changed` note's line break collapses in the history**
   (`{{ e.detail }}` in a plain cell). Multi-line details from STORY-009
   (`request_edited`, `submitted`) collapse too. **Fix:** the history's
   detail cell keeps line breaks (`white-space: pre-line`).
4. **Moving out of a category without a prefix keeps the name silently.**
   Unreachable: the seed refuses an empty prefix; pinned in ticket 02.
   **No change.**
5. **A coded move refreshes twice.** **Fix** with 1.
6. **`change_category`'s return type changed**; only the route reads it.
   **No change.**
7. **No type hints in the test file.** Peter: follow the test files' style.
   **No change.**
8. **The regression test cuts the response at the first `</p>`.** **Fix:**
   cut at the category panel's heading.

### Outcome (2026-10-20)
- Fixed 1 + 5 (relationships assigned, no refresh), 3 (history keeps line
  breaks, also for STORY-009's multi-line details), 8 (test anchored on the
  category heading). 1 more test (failed first). Suite: 788. Mutation: ids
  only again → 3 fail.
- Review of the fix diff only: no correctness defects. `generate_code` reads
  the relationship objects, so it sees the new category without a refresh.
- Not changed: 2 (agreed rule, raised in the story report), 4, 6, 7.

### Rule change (Peter, 2026-10-21)
A kept name that already starts with the new category's prefix gets no red
warning and no "ชื่อไม่ได้เปลี่ยน" note (it fits; the two warnings used to
contradict each other). Test:
`test_a_kept_name_with_the_new_prefix_is_not_warned_about` (failed first).
