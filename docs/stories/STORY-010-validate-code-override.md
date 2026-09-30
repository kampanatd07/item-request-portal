# STORY-010: Validate code override against the Running Register

Status: todo
Triage: ready-for-agent

## Why
An Administrator can override an approved request's Central Code with any
text today: no 11-digit check, no check that the Group + Sub-Category match
the request's category, and the Running Register is never told. That breaks
the rule that running numbers come only from the register (HANDOFF §6.4). If
someone types a number above the register's last value, the register will
later issue that same number to another item, and the collision only shows up
in AX/D365 — after the import files have gone out. Found while building
STORY-001 ticket 03 (2026-09-29); deliberately left out of that ticket.

## Scope
- `override_code` (in `app/services/requests.py`) validates the new code
  before saving:
  - exactly 11 digits
  - digits 1–3 = the request's Group code, digits 4–5 = its Sub-Category code,
    digits 6–7 = `00` (Item Type)
- If the code's running number (digits 8–11) is higher than the register's
  `last_running` for that Group + Sub-Category, move the register up to that
  number in the same transaction, and record a `RequestEvent`
  (e.g. `register_advanced`, detail `old -> new`)
- The register never moves backwards: a lower or equal running number leaves
  it untouched
- Thai error messages for each refusal; the Administrator-only guard from
  STORY-001 ticket 03 stays first, before any register read

## Out of scope
- Re-syncing the whole register from a file (STORY-005)
- Overrides on legacy (non-CENTRAL) code systems — they are inactive
- Changing who may override (Administrator only, STORY-001)

## Acceptance criteria
1. A code that is not exactly 11 digits is refused with a Thai error; the
   request's code and the register are unchanged
2. A code whose Group + Sub-Category (digits 1–5) do not match the request's
   category, or whose digits 6–7 are not `00`, is refused; nothing changes
3. A valid code whose running number is higher than the register's last value
   moves the register up to exactly that number, and an event records the move
4. A valid code whose running number is lower than or equal to the register's
   last value leaves the register untouched (never moves backwards)
5. A code already used by another request is still refused (existing unique
   check)
6. A code that was ever issued and then **burned** is refused too. Today the
   unique constraint misses one case: when an Administrator re-categorises a
   coded request, the old code is replaced on the request and survives only in
   the `code_reissued` event (`<old> -> <new>`), so an override could put that
   burned number on another item. (A request rejected after approval keeps its
   code, so the unique check already covers it — see `code_burned`.)
7. Every AC has a service-level test using `central_ids()` and
   `account_for(db, "administrator")`

## Depends on
STORY-001 (ticket 03: Administrator-only override). **Must be done before
STORY-006 (deploy).**

## Files likely touched
`app/services/requests.py` (`override_code`), `app/services/codegen.py`
(a register helper next to `_allocate_from_register`), `tests/test_codegen.py`
or a new test file

## Domain rules that apply
HANDOFF §6.4 — running numbers come only from `running_register`; the
register is the single owner. Code layout
`[Group 3][Sub-Category 2][Item Type 2 = 00][Running 4]` (HANDOFF §3).

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
- AC6 found while closing STORY-001 ticket 03 (2026-09-29).
