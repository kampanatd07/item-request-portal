# 01: One Name Prefix rule; the queue warns when a name does not fit its category

Status: ready-for-agent
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

- [ ] A name starting with the current prefix + `" - "` (any case): no warning
- [ ] A Name Override without the prefix, or with another category's prefix:
      warning on the queue detail
- [ ] Fixing the name (Procurement edits it) makes the warning go away
- [ ] Approval still works while the warning shows
- [ ] The searchable part: prefix cut when the name starts with it (any case),
      whole name kept otherwise; a name that is only the prefix, a prefix
      followed by `"-"` without spaces, and Thai text after the prefix
      (HANDOFF §6) behave as the rule says
