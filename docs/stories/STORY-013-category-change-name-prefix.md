# STORY-013: Category change updates the name prefix

Status: todo · Depends on: — · Must ship before the plants get access (STORY-006)
Triage: ready-for-human

## Why
The CATEGORY part of an Item Name (`[CATEGORY] - [name] - [detail]`) is the
Sub-Category's Name Prefix, so the name and the Central Code always describe
the same category. But re-categorising a request (`change_category`) only
moves the Item Group / Sub-Category; the Item Name keeps the old prefix. That
request is then exported into AX/D365 with a name that names the wrong
category: wrong data in the item master, not just a cosmetic issue. Found
while planning STORY-009 ticket 02 (2026-10-16).

## Scope
- When a request moves to another Sub-Category, replace only the CATEGORY
  part of its Item Name (everything before the first `" - "`) with the new
  Sub-Category's Name Prefix. The name and detail parts stay as they are, so a
  name Procurement typed by hand is not lost.
- Record the rename in the request's events (old name → new name), alongside
  the existing `category_changed` event.
- Applies everywhere a category change happens: before a code (Procurement)
  and after a code while still `approved` (Administrator, with re-issue).

## Out of scope
- Recomposing the whole name from the stored fields (that would undo a typed
  name; STORY-009 does a full recompose only when the Requester edits fields)
- Fixing names of requests already exported (none in production; not deployed)

## Acceptance criteria
_(to be finalised in /to-spec)_
1. Moving a request from Sub-Category A to B changes `A_PREFIX - name - detail`
   into `B_PREFIX - name - detail`; name and detail unchanged.
2. A name Procurement typed earlier keeps its name and detail parts.
3. The rename is in the request's events.
4. The new name still obeys the naming rules (≤ 110 characters); if the new
   prefix makes it too long, the move is refused with a Thai message and
   nothing changes.
5. A name without a CATEGORY part (no `" - "`): decide in /to-spec.

## Files likely touched
`app/services/requests.py` (`change_category`), `app/services/naming.py`,
tests

## Domain rules that apply
HANDOFF §6 (Thai text), the naming rules in CLAUDE.md, decision 2026-07-30
(names are composed, not typed).

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
- Peter (2026-10-16): replace only the prefix, keep the rest; log the rename;
  blocks STORY-006.
