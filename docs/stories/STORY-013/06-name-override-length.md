# 06: A Name Override longer than 110 characters is refused

Status: done
Triage: ready-for-agent
Parent: STORY-013
Blocked by: None (can start immediately)

**What to build:** when Procurement types a Name Override in the queue, the
system refuses a name longer than 110 characters with a Thai error giving
the length, and changes nothing. Today only an empty name is refused, so a
longer name would be exported into AX/D365, which the group standard does
not allow (Item Name ≤ 110). Must ship before the plants get access, with
the rest of STORY-013 (Peter, 2026-10-20). Found while planning ticket 02:
a category move refuses a name over 110, but the same name could be typed
directly.

- [x] A Name Override of 110 characters is saved
- [x] 111 characters: refused with a Thai message giving the length; the
      Item Name and the events unchanged
- [x] The length counts the name as it would be stored (spaces collapsed, as
      `edit_name` stores it)
- [x] The queue's name panel shows the error and keeps the old name

Other naming rules for a Name Override (no `,`, separators, unit spacing):
not here, see STORY-007's Notes.

## Notes (2026-10-20)

- `edit_name` refuses a name longer than 110 after collapsing spaces (as it
  stores it): "ชื่อยาว N ตัวอักษร (เกิน 110) — ย่อชื่อให้สั้นลง". Checked before
  the "unchanged" shortcut, so re-saving an older over-long override also
  says it is too long.
- The queue answers 422; the page's existing HTMX handler puts the message
  in the name panel's form, so the old name stays on screen (client side,
  not covered by pytest).
- **Tests:** `tests/test_name_override_length.py`, 4 (the two refusals
  failed first). Old tests: none changed. Suite: 796. Mutation: `>=` for
  `>` → the 110 test fails.

## Code review (2026-10-20)

Ran `/code-review` on the uncommitted diff. 7 findings, **no (ก)**.

1. **`edit_name` neither NFC-normalises nor `fix_thai`s the override**, so a
   decomposed SARA AM counts as two characters and is stored decomposed.
   Older than this ticket, and the same gap the composed name has: STORY-007
   already owns the decision ("Base Name, Item Name … not NFC + fix_thai
   normalised on submit … Changing it changes Item Names, so decide it
   here"). The count itself is right for what is stored and exported.
   **No change here; added to STORY-007's note.**
2. **A second whitespace clean-up next to the module's NFC one.** Same
   decision as 1. **No change.**
3. **The 110 cap is checked in three places** (`compose_name`,
   `change_category`, `edit_name`). They share `MAX_NAME_LEN`; the messages
   differ on purpose (each says what to do in its place). **No change.**
4. **No decomposed-Thai test.** With 1. **No change.**
5. **Type hints in tests.** Peter: test files' style. **No change.**
6. **Other naming rules still bypassed by a Name Override.** STORY-007
   (Peter, 2026-10-20). **No change.**
7. **No hint of the 110 cap before submitting.** **Fix:** the label says
   "ไม่เกิน 110 ตัวอักษร". Not a `maxlength`: the browser would cut a pasted
   name silently.

### Outcome (2026-10-20)
Fixed 7 (+1 test). Suite: 797. The fix (a label and a test) was reviewed by
reading it.
