# STORY-009: Requester edits and resubmits a Needs Info request

Status: todo · Depends on: STORY-001 · Must ship before the plants get access

## Why
When Procurement sends a request back as Needs Info, today only Procurement can
move it back to the queue, and it can only edit the whole Item Name, not the
fields it is composed from (size, brand, model, UoM, spec). Re-keying a
requester's reply by typing the name bypasses name composition and leaves the
fields empty. The Requester who has the missing detail should fix the request
themselves. Split out of STORY-001 (grilling Q10, Q14) to keep that diff small.

## Scope
- On "My requests", a Needs Info request opens the request form prefilled with
  its current values, including any Sub-Category Procurement changed
- Every field is editable except Plant (locked to the Account's Plant)
- Store the Base Name on the request (new `base_name` column) so the form can be
  prefilled; the Item Name is always recomposed from the fields on resubmit
- Duplicate Check runs again on resubmit
- Only the request's own Requester may resubmit, and only while it is `needs_info`
  (server-side check)
- Resubmit moves `needs_info` → `submitted` and logs a `RequestEvent`

## Out of scope
- Editing a request in any status other than Needs Info
- Editing items that already exist in AX/D365 (out of scope for v1)

## Acceptance criteria
_(to be finalised after Q17–Q18 and `/to-spec`)_
1. A Requester can resubmit their own Needs Info request; the Item Name is
   recomposed from the edited fields
2. A Requester cannot resubmit another Account's request, or one not in
   Needs Info, even by posting the form directly (403)
3. Plant cannot be changed on resubmit, even by editing the form
4. A name Procurement typed earlier is replaced by the recomposed name; the old
   name remains in the request's events
5. Duplicate Check results are shown again before resubmit

## Files likely touched
`app/models/core.py` (`base_name`), new migration, `app/services/requests.py`,
`app/routes/requests.py`, request form template, "My requests" template, tests

## Domain rules that apply
HANDOFF §6 Thai-text traps (form re-parsing), §6.5 (batch mode migration),
§6.8 (verify migration on fresh DB). Decision 2026-07-30 (names are composed,
not typed).

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes

### Decided in STORY-001 grilling (2026-09-29)
- Q10 The Requester edits and resubmits (not Procurement re-keying replies).
- Q14 Separate story, depends on 001, must ship before the plants open.
- Q15 All fields editable except Plant; prefilled with current values; name
  recomposed and Duplicate Check re-run on resubmit.
- Q16 The name is always recomposed from the fields, even if Procurement typed
  one earlier; the typed name survives in `RequestEvent` history.

Open:
- Q17 Required "reply to Procurement" text on resubmit, logged as the event
  detail? [Yes, required.]
- Q18 Keep Procurement's "ผู้ขอส่งข้อมูลแล้ว รับเข้าคิวใหม่" button for phone
  replies? [Yes, but a note becomes required.]
- Existing requests created before `base_name` exists: how is the form
  prefilled? (decide in `/to-spec`)
