# STORY-013: Category change updates the name prefix

Status: review · Depends on: — · Must ship before the plants get access (STORY-006)
Triage: ready-for-agent

## Why
The CATEGORY part of an Item Name (`[CATEGORY] - [name] - [detail]`) is the
Sub-Category's Name Prefix, so the name and the Central Code always describe
the same category. But re-categorising a request (`change_category`) only
moves the Item Group / Sub-Category; the Item Name keeps the old prefix. That
request is then exported into AX/D365 with a name that names the wrong
category: wrong data in the item master, not just a cosmetic issue. Found
while planning STORY-009 ticket 02 (2026-10-16).

## Scope
- **One prefix rule** for the whole system: an Item Name "starts with" a Name
  Prefix when it begins with that prefix followed by `" - "`, compared
  without case (Q1, Q8). Used by the rename, the queue check and the
  searchable text for category suggestion.
- **Rename on a category move.** When a request moves to another
  Sub-Category and its Item Name starts with the **old** Sub-Category's Name
  Prefix, replace only that prefix with the new one, in upper case as
  `compose_name` writes it. The name and detail parts stay as they are, so a
  Name Override is not lost.
  (The earlier wording "everything before the first `" - "`" was wrong: it
  would cut the first real segment of a Name Override such as
  `Ball Bearing SKF - 20 L`. Q1.)
- **No old prefix found** (a Name Override without one, or a Name Prefix
  edited in the taxonomy since): the move goes ahead, the name is left as it
  is, the category panel shows a red warning "ชื่อไม่ได้ขึ้นต้นด้วย prefix ของ
  หมวดเดิม (<prefix เดิม>) — ตรวจและแก้ชื่อเอง", and `category_changed` notes
  that the name did not change (Q7).
- **Standing check on the queue detail:** every time the request detail page
  is shown, if the Item Name does not start with the current Sub-Category's
  Name Prefix, it shows a warning until the name is fixed. Display only;
  Approval is not blocked (Q7).
- **Too long:** if the new prefix makes the name longer than 110 characters,
  the whole move is refused with a Thai message giving the length and asking
  Procurement to shorten the name first; nothing changes, no code re-issue
  (Q2, AC4).
- **Event:** a new action `name_prefix_changed`, detail `old name → new
  name`, written in the same transaction right after `category_changed` (and
  before `code_reissued`, if any). History label "เปลี่ยน prefix ตามหมวด". It
  is **not a name setter** for STORY-009 ticket 05's replaced-name warning
  (Q3, Q9).
- **Both panels update at once:** the category move answers with the
  category panel and, out of band, the name panel, so Procurement sees the
  new name without a reload (Q4).
- **Learning:** `learn_from_correction` learns the name after the rename,
  with its Name Prefix cut off by the same `searchable_part(name, prefix)`
  that the classified-master import uses (Q5, Q10, Q11).
- Applies everywhere a category change happens: before a code (Procurement)
  and after a code while still `approved` (Administrator, with re-issue).

## Out of scope
- Recomposing the whole name from the stored fields (that would undo a Name
  Override; STORY-009 does a full recompose only when the Requester edits
  fields)
- Fixing names of requests already exported (none in production; not
  deployed)
- Blocking Approval on a name without the right prefix (warning only, Q7)
- The live name preview on the request forms (STORY-014)

## Acceptance criteria
1. Moving a request from Sub-Category A to B turns `A_PREFIX - name - detail`
   into `B_PREFIX - name - detail`; name and detail parts unchanged.
2. A Name Override that starts with the old prefix keeps its name and detail
   parts; only the prefix changes.
3. The old prefix is matched without case (`Bearing - x` → `SEAL - x`); the
   new prefix is written in upper case.
4. A name that does not start with the old prefix is left unchanged; the move
   still happens; the panel shows the red warning; `category_changed` says the
   name did not change; no `name_prefix_changed` event.
5. A move whose new name would exceed 110 characters is refused with a Thai
   message giving the length; group, sub-category, name, code and register
   all unchanged; no events.
6. The rename is one `name_prefix_changed` event (`old → new`), after
   `category_changed`, before `code_reissued`; history label
   "เปลี่ยน prefix ตามหมวด".
7. After an Administrator's move of a coded `approved` request, both the code
   is re-issued (as today) and the prefix is renamed.
8. The response updates the name panel too (out-of-band swap), showing the
   new name.
9. The queue detail warns whenever the Item Name does not start with the
   current Sub-Category's Name Prefix; no warning when it does; Approval
   still possible either way.
10. STORY-009 ticket 05: Procurement types a name → category move → the
    Requester edits the size and resubmits → the replaced-name warning still
    shows (`name_prefix_changed` is not a name setter).
11. Category suggestion learns the renamed name with its prefix cut off;
    `suggest_category("<name without prefix>")` finds the new category.
12. The classified-master import uses `searchable_part(name, prefix)` with the
    row's Sub-Category prefix. Before the switch, a read-only dry run over the
    real file (`D:\dev\private\Carabao_Group_Item_Master_Central_v4.xlsx`)
    counts rows whose searchable text differs from the old rule ("after the
    first `" - "`"), with 5 examples; **if more than 0, stop and report to
    Peter before changing the import.**

## Files likely touched
`app/services/requests.py` (`change_category`), `app/services/naming.py`
(the prefix rule), `app/services/snapshots.py` (`searchable_part`,
`check_labeled_master`), `app/services/categorizer.py`
(`learn_from_correction`), `app/services/queue_view.py`,
`app/routes/queue.py`, `app/templates/partials/category_panel.html`,
`app/templates/partials/name_panel.html`, `app/templates/request_detail.html`,
`app/templating.py` (event label), tests

## Domain rules that apply
HANDOFF §6 (Thai text: never `\b` next to Thai, NFC not NFKC), the naming
rules in CLAUDE.md, decision 2026-07-30 (names are composed, not typed).
Glossary: Name Prefix, Name Override (CONTEXT.md).

## Plan
Tickets in `docs/stories/STORY-013/` (Peter, 2026-10-20), one branch
`story/013-category-change-name-prefix`, one ticket at a time, in this order:

1. 01 One Name Prefix rule; the queue warns when a name does not fit its
   category (no blockers)
2. 05 The classified-master import uses the same rule: dry run on the real
   file first, stop if any row differs (blocked by 01)
3. 02 A category move swaps the Name Prefix, refusing a name over 110
   characters (blocked by 01)
4. 03 A name without the old prefix is kept, with a warning (blocked by 02)
5. 04 Category suggestion learns from the renamed name (blocked by 01, 02)

AC5 (too long → refuse) sits in ticket 02, not 03, so the prefix is never
swapped without the length check (Peter, 2026-10-20).

Added 2026-10-20 (Peter): a seed guard (no Name Prefix over 16 in
`taxonomy.json`), done with ticket 01; and

6. 06 A Name Override longer than 110 characters is refused (no blockers;
   before the plants open, since a longer name would be exported to AX).
   Other Name Override naming rules: STORY-007's Notes.

Order from here: 05 → 02 → 03 → 04 → 06.

## Notes
- Peter (2026-10-16): replace only the prefix, keep the rest; log the rename;
  blocks STORY-006.
- From STORY-009 ticket 05 (2026-10-19): the queue's replaced-name warning
  (`queue_view._replaced_name`) asks which event last set the Item Name
  before a resubmit; only `name_edited` and a `request_edited` with a
  `ชื่อสินค้า:` line count. The event this story writes when a category move
  changes the prefix **must not count as a name setter**: if it did, it would
  hide that the rest of the name was typed by Procurement, and a later
  resubmit that replaces that name would no longer warn. Keep it a separate
  action (or keep its name line out of `request_edited`), and add a test that
  a typed name, then a category move, then a replacing resubmit still warns.

### Decided in grilling (Peter, 2026-10-19/20)
- Q1 The CATEGORY part is recognised only as the old Sub-Category's Name
  Prefix + `" - "`; not "everything before the first `" - "`".
- Q2 Too long → refuse the whole move (AC4), give the length, Procurement
  shortens the name itself; never truncate.
- Q3 New action `name_prefix_changed`; not a name setter for ticket 05's rule.
- Q4 Out-of-band swap of the name panel with the category panel.
- Q5 Learn from the renamed name.
- Q6 "Name Override" added to CONTEXT.md.
- Q7 No old prefix → move, keep the name, red warning, note in
  `category_changed`; plus a standing warning on the queue detail whenever the
  name does not start with the current prefix; Approval not blocked.
- Q8 Prefix compared without case; written in upper case.
- Q9 Event order `category_changed` → `name_prefix_changed` →
  `code_reissued`. Allowed old-test change: `tests/test_categorizer.py:178`
  from "last event is category_changed" to "category_changed is among the
  events" (one line).
- Q10 Learning cuts the Name Prefix off first, using the import's cut, no new
  rule.
- Q11 One `searchable_part(name, prefix)` for the import and the learning;
  cut only when the name starts with that prefix (Q8 comparison), else keep
  the whole name. Dry run on the real file first (AC12).
