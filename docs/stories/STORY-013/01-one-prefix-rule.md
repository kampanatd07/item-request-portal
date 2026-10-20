# 01: One Name Prefix rule; the queue warns when a name does not fit its category

Status: done
Triage: ready-for-agent
Parent: STORY-013
Blocked by: None (can start immediately)

**What to build:** the system has one rule for "this Item Name starts with
this Name Prefix": the prefix followed by `" - "`, compared without case
(grilling Q1, Q8). The same rule also gives the searchable part of a name
(the name with that prefix cut off, or the whole name when it does not start
with it; Q11). First visible use: every time Procurement opens a request's
detail in the queue, if the Item Name does not start with the current
Sub-Category's Name Prefix, a warning shows until the name is fixed. It
never blocks Approval (Q7).

- [x] A name starting with the current prefix + `" - "` (any case): no warning
- [x] A Name Override without the prefix, or with another category's prefix:
      warning on the queue detail
- [x] Fixing the name (Procurement edits it) makes the warning go away
- [x] Approval still works while the warning shows
- [x] The searchable part: prefix cut when the name starts with it (any case),
      whole name kept otherwise; a name that is only the prefix, a prefix
      followed by `"-"` without spaces, and Thai text after the prefix
      (HANDOFF §6) behave as the rule says

## Notes (2026-10-20)

- **The rule** lives in `app/services/naming.py`, next to `compose_name`:
  `starts_with_prefix(name, prefix)` and `searchable_part(name, prefix)`.
  The prefix is first put in the form `compose_name` writes it (cleaned,
  upper case, cut to 16), then compared with the start of the name plus
  `" - "` in upper case. Thai after the prefix is untouched (no NFKC).
- **The warning** is in the name panel (Peter, 2026-10-20), worked out by
  `queue_view.name_prefix_warning(req)` from the request's Sub-Category (or
  Group) prefix, on the detail page and on every name-panel redraw: fixing
  the name clears it in the same response. Display only.
- Added on Peter's request: a Name Prefix edited in the taxonomy after the
  request got its name → the detail page warns.
- **Tests:** `tests/test_name_prefix_rule.py`, 24 (written first: 21 failed
  before the code, the 3 "no warning" cases passed as they should). Old
  tests: none changed. Suite: 744 passed.
- **Mutation check:** each made at least one test fail: a case-sensitive
  compare, no `" - "` after the prefix, no 16-character cut, the rename
  response without the check.

## Code review (2026-10-20)

Ran `/code-review` on the uncommitted diff. 9 findings, sorted as before:
**(ก)** wrong data, someone acting who should not, data lost, or an
acceptance criterion not met; **(ข)** a note. Peter's decisions: fixed 1, 2,
4, 5, 6, 7, 9; 3 (ticket 02) and 8 not changed.

Fact for 1–2: all 130 Name Prefixes in today's taxonomy are ≤ 16 characters,
so neither is reachable today. **Correction (2026-10-20):** this first said an
Administrator could type a longer prefix on the Settings page. That is wrong:
no page edits Name Prefixes; they come only from `app/data/taxonomy.json`
through `python -m app.seed`, which overwrites them on every run (the column
allows 30).

### (ก) Must fix
1. **The warning can name a prefix that never clears it.** It shows the
   stored prefix (`prefix.upper()`), but the check uses the prefix as
   `compose_name` writes it (cleaned, cut to 16). With a stored prefix like
   `MAINTENANCE SERVICE WORK`, Procurement types exactly what the warning
   says and the warning stays. Acceptance criterion "fixing the name makes
   the warning go away" not met for such a prefix.
   **Recommend: fix**: show the prefix as written; test with a > 16 prefix.
2. **A cut on a space leaves a trailing space** (`SPARE PARTS AND ` + `" - "`
   → double space). `compose_name` already does this on master, so it would
   write such names with a double space (wrong data), and no name Procurement
   types can match it (`edit_name` collapses spaces).
   **Recommend: fix** in one helper used by both `compose_name` and the rule
   (strip after the cut), with 5 below; test it.

### (ข) Notes
3. **A category move does not redraw the name panel**, so the warning
   appears only after a reload. This is ticket 02's out-of-band swap (AC8).
   **Recommend: no change here** (ticket 02).
4. **The warning says "ตรวจและแก้ชื่อ" on exported/created/notified
   requests**, where the name can no longer be edited. **Recommend: fix**:
   keep the warning, drop "และแก้ชื่อ" when the name cannot be edited.
5. **`compose_name` still has its own copy of the prefix form and `" - "`.**
   **Recommend: fix** (with 2).
6. **The prefix source (`subgroup or group`) is chosen in two places**
   (`_validated_fields` and the warning). **Recommend: fix**: one helper.
7. **`searchable_part(None, …)` returns None** despite `-> str`, and works
   out the prefix twice. Ticket 05 would call it on import rows.
   **Recommend: fix.**
8. **No type hints on the new test functions** (CLAUDE.md "Type hints on all
   functions"). The existing test files do not annotate test functions
   either. **Recommend: no change** (follow the test files' style); say if you
   want tests annotated from now on.
9. **No test with a prefix > 16 or a space at position 16.**
   **Recommend: fix** with 1 and 2.

### Outcome (2026-10-20)
- `naming.prefix_as_written(prefix)`: cleaned, upper case, cut to 16, then
  stripped. `compose_name`, the rule and the warning all use it, so the
  warning names the prefix exactly as a name carries it, and a cut on a space
  no longer gives `"SPARE PARTS AND  - "`. compose_name output is unchanged
  for all 130 real prefixes (all ≤ 16, no spaces to strip).
- `requests.name_prefix_of(group, sub)`: the one choice of prefix source.
- On exported/created/notified requests the warning says "ตรวจชื่อ".
- `searchable_part(None, …)` returns `""`.
- 6 more tests (5 failed before the fix); suite 750 passed. Mutation check:
  no strip after the cut, the stored prefix in the warning, no `None` guard,
  "แก้ชื่อ" in every status: each fails a test.
- Review of the fix diff only: no correctness defects. Its notes: the
  `name_prefix_of` docstring was imprecise (fixed); `upper()` maps the
  dotless `ı` to `I` (harmless).
- **Not done here, waiting for Peter:** Peter asked for the Settings page to
  refuse a Name Prefix longer than 16. No page edits prefixes (see the
  correction above); the root-cause guard would go in the seed instead.
