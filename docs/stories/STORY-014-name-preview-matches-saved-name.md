# STORY-014: The name preview shows the name that will be saved

Status: todo · Depends on: — · After the plants get access (not a STORY-006 prerequisite)
Triage: needs-triage

## Why
The request form shows a live preview of the Item Name. It starts right, but
after the first keystroke the browser builds the preview itself
(`compose()` in `app/templates/request_form.html`): a plain space-joined
string without the Sub-Category's Name Prefix, without the ` - ` separators
and without unit spacing (`20L` instead of `20 L`). The server then saves the
properly composed name (`[CATEGORY] - [name] - [detail]`). A Requester checks
one name and gets another. Found in STORY-009's closing review (item 3,
2026-10-19); it is older than STORY-009 and affects both pages.

## Scope
- The preview on the new-request page and on the resubmit page shows exactly
  the name the server would compose from the current fields, including the
  category prefix and the naming rules (separators, unit spacing, ≤ 110
  characters).
- One composer: the preview asks the server's name composition (the same
  code `_validated_fields` uses), never a second copy in JavaScript.

## Out of scope
- Changing the naming rules themselves (STORY-007)
- The category prefix on a category change (STORY-013)

## Acceptance criteria
_(to be finalised in /to-spec)_
1. After any field edit, the preview equals the Item Name the server saves
   for the same fields.
2. Changing the Sub-Category changes the preview's prefix.
3. Thai text and spaced units appear in the preview as they will be saved
   (HANDOFF §6).
4. Same behaviour on the new-request page and the resubmit page.

## Files likely touched
`app/templates/request_form.html`, a fragment route next to the other
`/fragments/*` routes, `app/services/naming.py` / `app/services/requests.py`,
tests

## Domain rules that apply
HANDOFF §6 (Thai text, no `\b` next to Thai, NFC not NFKC), the naming rules
in CLAUDE.md.

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
- Peter (2026-10-19): opened after STORY-009 merged; ships after the plants
  get access, not a condition of STORY-006.
