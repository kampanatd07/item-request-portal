# STORY-009: Requester edits and resubmits a Needs Info request

Status: done (2026-10-19) · Depends on: STORY-001, STORY-002 · Must ship before the plants get access
Triage: ready-for-agent

## Why
When Procurement sends a request back as Needs Info, today only Procurement can
move it back to the queue, and it can only edit the whole Item Name, not the
fields it is composed from (size, brand, model, UoM, spec). Re-keying a
requester's reply by typing the name bypasses name composition and leaves the
fields empty. The Requester who has the missing detail should fix the request
themselves. Split out of STORY-001 (grilling Q10, Q14) to keep that diff small.

## Scope
- On "My requests", a Needs Info request has an "แก้ไขและส่งกลับ" button that
  opens the request form prefilled with its current values, including any
  Sub-Category Procurement changed
- The Requester, or the Originator if they have an Account in the request's
  Plant, may resubmit
- Every field is editable except Plant; the Originator also cannot change the
  originator fields
- Store the Base Name on the request (new `base_name` column) so the form can be
  prefilled; the Item Name is always recomposed from the fields on resubmit
- A reply to Procurement is required on resubmit
- Duplicate Check runs again on resubmit (on load and while typing; never blocks)
- Resubmit moves `needs_info` → `submitted` through a conditional row claim
- Procurement gets a best-effort email when a Requester or Originator resubmits
- "My requests" also lists requests where the Account is the Originator
- Procurement's "รับเข้าคิวใหม่" button requires a note and uses the same claim

## Out of scope
- Editing a request in any status other than Needs Info
- Editing items that already exist in AX/D365 (out of scope for v1)
- Email to Procurement on new submissions
- Putting the Procurement email on the resend list

## Acceptance criteria
1. A Requester can resubmit their own Needs Info request; the Item Name is
   recomposed from the edited fields and the request is `submitted` again.
2. An Originator with an active Account in the request's Plant can resubmit it
   too; any other Account gets 403, even when posting the form directly.
3. Resubmitting one's own request that is no longer Needs Info gives 409 with
   "คำขอนี้ไม่ได้รอข้อมูลแล้ว (สถานะปัจจุบัน: …)"; nothing is saved, no event,
   no email.
4. Plant cannot be changed on resubmit, even by editing the form; the
   Originator cannot change the originator fields.
5. A name Procurement typed earlier is replaced by the recomposed name; the old
   name stays in the request's events, and the queue detail warns
   "ชื่อที่จัดซื้อแก้ไว้ถูกแทนที่: <เดิม> → <ใหม่>".
6. Duplicate Check results show on the resubmit form as soon as it loads.
7. A reply is required, both on resubmit and on Procurement's "รับเข้าคิวใหม่"
   button. Both clear the request's Procurement note.
8. Two concurrent attempts to leave Needs Info (resubmit vs resubmit, or
   resubmit vs the queue button): exactly one wins; the other gets 409.
9. Active Procurement and Administrator Accounts get one email per resubmit by a
   Requester or Originator; none when Procurement/Administrator resubmits; a
   failed send is logged and nothing else changes.
10. The Needs Info email links to the resubmit page.

## Files likely touched
`app/models/core.py` (`base_name`), new migration, `app/services/requests.py`,
`app/services/notify.py`, `app/routes/requests.py`, `app/routes/queue.py`,
request form, "My requests", queue detail and status panel templates, email
templates, tests

## Domain rules that apply
HANDOFF §6 Thai-text traps (form re-parsing), §6.5 (batch mode migration),
§6.8 (verify migration on fresh DB). Decision 2026-07-30 (names are composed,
not typed). Decisions 2026-10-16 (Originator may resubmit; resubmit email is
best-effort).

## Plan

### Problem Statement
When Procurement sends an Item Request back as Needs Info, the person with the
missing detail cannot fix it. Only Procurement can put the request back in the
queue, and Procurement can only overwrite the whole Item Name, so the reply is
typed into the name by hand: name composition is bypassed and the Brand, Model,
Size, Variant, spec and UoM fields stay wrong or empty. For on-behalf requests
the Needs Info email goes to the Originator, who has no way to answer in the
portal at all.

### Solution
The Requester, or the Originator if they have an Account, opens the Needs Info
request from "My requests", sees what Procurement asked for, edits the same form
they would use for a new request (prefilled, Plant locked), sees the Duplicate
Check again, writes a required reply and sends it back. The portal recomposes the
Item Name, records what changed, puts the request back in the queue and emails
Procurement. Procurement sees the reply, the changed fields and, if its own
hand-typed name was replaced, a clear warning.

### User Stories
1. As a Requester, I want a "แก้ไขและส่งกลับ" button on my Needs Info request in "My requests", so that I can answer Procurement without calling them.
2. As a Requester, I want the resubmit form prefilled with the request's current values, so that I only change what Procurement asked about.
3. As a Requester, I want the form to show the Sub-Category Procurement chose, so that I don't undo their correction by accident.
4. As a Requester, I want to see what Procurement asked for at the top of the form, so that I know what to fix.
5. As a Requester, I want to edit Base Name, Brand, Model, Size, Variant, spec and UoM, so that the Item Name is composed correctly from them.
6. As a Requester, I want to change the Item Group, Sub-Category and the other request fields too, so that I can fix anything Procurement questioned.
7. As a Requester, I want the Plant locked, so that a request never moves to another Plant's AX/D365.
8. As a Requester, I want a live preview of the recomposed Item Name, so that I see the result before sending.
9. As a Requester, I want the Duplicate Check to show as soon as the form opens, so that I notice an existing item before resubmitting.
10. As a Requester, I want the Duplicate Check to refresh as I type, as on a new request, so that edits are checked too.
11. As a Requester, I want to resubmit even if similar items are shown, so that a false match does not block me.
12. As a Requester, I want to write a reply to Procurement that is required, so that Procurement knows what I changed and why.
13. As a Requester, I want a clear message if the request is no longer waiting for me, so that I don't think my edit was saved.
14. As a Requester, I want my old Needs Info note gone from "My requests" after I resubmit, so that the page does not show a question I already answered.
15. As a Requester whose request had no stored Base Name, I want an empty Base Name field I must fill, so that the name is never guessed.
16. As an Originator with an Account, I want requests made on my behalf listed in "My requests" in every status, labelled "ขอแทนโดย <Requester>", so that I can follow them.
17. As an Originator, I want to resubmit a Needs Info request made on my behalf, so that I can answer the question that was emailed to me.
18. As an Originator, I want the same form and rules as the Requester except the originator fields, so that I cannot hand the request to someone else.
19. As an Originator, I want the Needs Info email to link straight to the resubmit page, so that I go from email to answer in one click.
20. As an Originator without an Account, I want the email to still tell me I can reply to it, so that I can answer by email.
21. As a Requester from another Plant, or with a deactivated Account, I want to be refused (403), so that only the right people change a request.
22. As Procurement, I want an email when a Requester or Originator resubmits, so that I don't have to watch the queue.
23. As Procurement, I want that email to show the request number, new Item Name, Plant, who resubmitted, their reply, the changed fields and a queue link, so that I can decide whether to open it now.
24. As Procurement, I want no email when I or another Procurement/Administrator resubmit, so that I'm not told about my own action.
25. As Procurement, I want a failed resubmit email to never block or undo the resubmit, so that the request still reaches the queue.
26. As Procurement, I want a "ส่งกลับแล้ว" badge in the queue on submitted requests that came back from Needs Info, so that I can tell them from new requests.
27. As Procurement, I want the queue detail to show the latest reply and the changed fields above the history, so that I see the answer first.
28. As Procurement, I want a clear warning "ชื่อที่จัดซื้อแก้ไว้ถูกแทนที่: <เดิม> → <ใหม่>" when a resubmit replaced a name I typed, so that I can retype it if mine was better.
29. As Procurement, I want the old Item Name kept in the request's events, so that nothing I typed is lost.
30. As Procurement, I want to keep the "ผู้ขอส่งข้อมูลแล้ว รับเข้าคิวใหม่" button for replies by phone, so that requests with nothing to edit can go back to the queue.
31. As Procurement, I want that button to require a note, so that the reason it went back is on record.
32. As Procurement, I want that button to clear the Needs Info note too, so that "My requests" agrees with the queue.
33. As Procurement, if I press "รับเข้าคิวใหม่" while the Requester is resubmitting, I want exactly one of us to win and the other to get a clear 409, so that the request is never moved twice or logged twice.
34. As Procurement, I want a Needs Info request I submitted on someone's behalf to be resubmittable by me through the same form, so that I can apply an Originator's emailed reply to the fields.
35. As an Administrator, I want the Needs Info → submitted change logged as a normal `submitted` status event with the reply and the top Duplicate Check matches, so that the history reads the same as a first submission.
36. As an Administrator, I want a `request_edited` event listing each changed field as `field: old → new` only when something changed, so that the history shows exactly what the resubmit changed.

### Implementation Decisions
- **Schema:** `item_requests.base_name` (nullable, same length as the Base Name
  input). New submissions store it. One Alembic migration, batch mode for
  SQLite. Existing rows stay NULL; the resubmit form then shows an empty,
  required Base Name field. No backfill from the Item Name.
- **Who may resubmit** (one service-level check, used by both the GET form and
  the POST):
  - the Requester: normalised `requester_email` equals the Account's email;
  - or the Originator: normalised `originator_email` equals the Account's email,
    the Account is active, and its Plant (if it has one) is the request's Plant.
  - Anyone else: 403. The ownership check runs before the status check.
- **Status check and claim:** leaving Needs Info (resubmit, or Procurement's
  "รับเข้าคิวใหม่") claims the row with a conditional update, the same pattern as
  STORY-002's notifier: `UPDATE item_requests SET status = 'submitted' … WHERE
  id = :id AND status = 'needs_info'`. Rowcount 0 → 409 with "คำขอนี้ไม่ได้รอข้อมูลแล้ว
  (สถานะปัจจุบัน: <status>)", nothing written, no event, no email. Field updates,
  events and the cleared note are written in the same transaction as the claim.
  The queue button moves from the generic status-change path to this claim for
  the needs_info → submitted transition only.
- **What may change:** every field the new-request form posts, except Plant
  (always taken from the stored request, never from the form). The originator
  fields are ignored unless the actor is the request's Requester; when the
  Requester changes them, they are validated exactly as on a new request.
  Category rules are the same as on submit (Service requests never get an
  Item-type Sub-Category).
- **One validation path:** resubmit reuses the new-request validation and name
  composition (the service that builds an Item Name from Base Name, Brand,
  Model, Size, Variant and the Sub-Category's Name Prefix), so the two can't
  drift. The Item Name is always recomposed, even when Procurement edited it
  earlier.
- **Events:** at most two per resubmit, in this order:
  1. `request_edited` (new action; not a status action) with one line per
     changed field, `field: old → new`, Item Name included; only written when
     something changed.
  2. `submitted` (the existing status action, so the notifier's "latest status
     change" logic is unchanged) with the reply as detail, followed by the top
     3 Duplicate Check matches in the same format a first submission uses.
  The queue button writes only `submitted`, with its required note.
- **Procurement note:** `review_note` is cleared on both ways out of Needs Info.
- **Replaced-name warning:** shown on the queue detail when the request's
  latest `request_edited` changed the Item Name and a `name_edited` event exists
  before it, after the previous `submitted`/`needs_info` cycle began. Text:
  "ชื่อที่จัดซื้อแก้ไว้ถูกแทนที่: <ชื่อที่จัดซื้อแก้> → <ชื่อใหม่>". Display only.
- **Queue display:** the "ส่งกลับแล้ว" badge shows on `submitted` requests whose
  events include an earlier `needs_info`. The detail shows the latest reply and
  the `request_edited` lines above the history.
- **My requests:** lists requests where the Account is the Requester or the
  Originator; Originator rows carry "ขอแทนโดย <requester_name>". The
  "แก้ไขและส่งกลับ" button appears on Needs Info rows the Account may resubmit.
- **Routes:** GET and POST `/my-requests/{id}/resubmit` under the logged-in
  router (any Role); the checks above live in the service.
- **Procurement email:** after commit, a background task sends one email to all
  active Accounts with Role Procurement or Administrator. It is sent only when
  the actor is neither. Content: request number, new Item Name, Plant, who
  resubmitted, the reply, the changed-field lines, and a link to the request in
  the queue. No Duplicate Check results. Best-effort: on any `MailError` it logs
  and stops. No `notified`/`notify_failed` event, never on the resend list. It
  goes through the existing `MailSender` (and rate limiter), with its own
  template pair (txt + html).
- **Needs Info email:** its link points to `/my-requests/{id}/resubmit`, and the
  text reads "แก้ไขและส่งกลับในระบบ (สำหรับผู้มีบัญชี)". "กรุณาตอบกลับอีเมลนี้…"
  stays.

### Testing Decisions
- Test external behaviour only: HTTP status, the HTML a person sees, stored
  request fields and events, and the emails in the fake outbox. Never private
  helpers.
- **Main seam: HTTP via `TestClient`.**
  - Log in with `client_as(role, plant)`; create requests with
    `POST /requests` and `central_ids()`; move them to Needs Info through the
    queue endpoint.
  - Assert on responses, DB state and `mail_outbox`.
  - Prior art: `test_my_requests.py`, `test_originator.py`, `test_queue.py`,
    `test_notify_status.py`.
- **Second seam: notify service with a sender that raises `MailError`.** Proves
  the Procurement email failure is logged only: no event, nothing on
  `pending_notifications`. Prior art: `test_notify_status.py`.
- **Concurrency:** two threads on a file-based SQLite database each try to
  leave Needs Info for the same request (resubmit vs resubmit, and resubmit vs
  the queue button). Exactly one `submitted` event, one 409, one email at most.
  Prior art: the claim tests of STORY-002.
- Each acceptance criterion gets a happy path and a failure path. Thai text in
  the fields (SARA AM, spaced units) goes through a resubmit unchanged
  (HANDOFF §6).
- **Migration:** not covered by tests (`create_all`). Verify by hand on a fresh
  database (`upgrade head` → `downgrade -1` → `upgrade head`) and on a copy of
  `dev.db`.

### Out of Scope
Editing requests in any status other than Needs Info; a Requester withdrawing a
request; emailing Procurement on new submissions; a resend list for the
Procurement email; backfilling `base_name` for existing rows; editing items that
already exist in AX/D365.

### Further Notes
- Decided in grilling 2026-10-16 (Q1–Q22) plus Peter's replaced-name warning
  and the conditional-claim requirement. See decisions.md 2026-10-16 for the
  two decisions with trade-offs.
- No production data exists yet (not deployed), so `base_name` NULL only
  occurs in dev databases.

## Notes

### Decided in STORY-001 grilling (2026-09-29)
- Q10 The Requester edits and resubmits (not Procurement re-keying replies).
- Q14 Separate story, depends on 001, must ship before the plants open.
- Q15 All fields editable except Plant; prefilled with current values; name
  recomposed and Duplicate Check re-run on resubmit.
- Q16 The name is always recomposed from the fields, even if Procurement typed
  one earlier; the typed name survives in `RequestEvent` history.

### Decided in STORY-009 grilling (2026-10-16)
- Q1 The Originator with an Account may resubmit too (decisions.md).
- Q2 "Originator" added to CONTEXT.md.
- Q3 No `base_name` backfill: empty required field on old rows.
- Q4 Reply required; it is the `submitted` event's detail.
- Q5 Keep Procurement's "รับเข้าคิวใหม่" button; its note becomes required.
- Q6 Every field editable except Plant; originator re-validated.
- Q7 Email Procurement on resubmit.
- Q8 Clear `review_note` on resubmit.
- Q9 403 for another Account's request; 409 for own request no longer in
  Needs Info.
- Q10 Duplicate Check on load and while typing; non-blocking; top 3 logged.
- Q11 `request_edited` (only if changed) + `submitted` events.
- Q12 Originator: active Account, same Plant if it has one; else 403.
- Q13 Originator sees all statuses in "My requests" with "ขอแทนโดย <Requester>".
- Q14 Originator cannot edit Plant or originator fields.
- Q15 Needs Info email links to the resubmit page.
- Q16 Procurement email to all active Procurement/Administrator Accounts.
- Q17 Best-effort; failure logged only, not on the resend list (decisions.md).
- Q18 Only when a Requester/Originator resubmits; not for new submissions.
- Q19 Email content as in the Plan; no Duplicate Check results.
- Q20 The queue button clears `review_note` too.
- Q21 Button in "My requests"; reason box on top; reply above the send button.
- Q22 Queue: "ส่งกลับแล้ว" badge; latest reply and changes above history.
- Peter: warn on the queue detail when a resubmit replaced a name Procurement
  typed; do not block.
- Peter: conditional claim `WHERE status = 'needs_info'` for both ways out of
  Needs Info; 0 rows → 409; tested with two threads on file SQLite.

## Closing check (2026-10-19)

Tickets 01–06 are done and pushed (last commit 5f03c87). Suite: 711 passed.

### Migration `db44eba12672` (adds `item_requests.base_name`)
- Fresh temporary SQLite: `upgrade head` → seed → `downgrade -1` →
  `upgrade head` → seed, all clean; `alembic check`: no differences between
  the models and the schema.
- A copy of dev.db in a temporary folder (2 requests, 13 events):
  upgrade → downgrade → upgrade. A sha256 over every request column (except
  `base_name`) and every event is the same at each step; `base_name` stays
  NULL (no backfill, Q3). dev.db itself was only read: its sha256 is the
  same before and after.
- master has gained one commit since the branch (933689d, STORY-013 docs
  only): no second migration head.

### Branch review: `/code-review master..story/009-requester-resubmit`
Checked against this story's acceptance criteria, its six tickets and
decisions.md (2026-10-16, 2026-10-19). 9 findings. Same sorting as the
ticket reviews: **(ก)** wrong data, someone acting who should not, or data
lost, or an acceptance criterion not met; **(ข)** everything else, a note.
Peter's decisions: fixed 1, 2, 4, 5, 7, 8, 9; 3 → a new story after the
merge (TODO below); 6 not changed. Outcomes at the end of this file.

#### (ก) Must fix

1. **A resubmit accepts another Plant's code system, or an inactive one.**
   `_validated_fields` checks only that the group belongs to the posted
   `code_system_id`; it never checks that the code system is linked to the
   request's Plant (`FactoryCodeSystem`) or is active. A resubmit locks the
   Plant but a hand-made post can move a CBD request into an APM-only
   system, or into the inactive stock system (whose groups are still
   active). Wrong data, and against "Stock code systems stay inactive".
   Verified in the code. The same gap exists on *new* requests since before
   STORY-009 (shared validation), so one fix in `_validated_fields` closes
   both. **Recommend: fix** (refuse with a Thai error; test both paths).
2. **The server does not require a Base Name on old rows** (user story 15).
   With `base_name` NULL, a posted empty `item_name` counts as "not edited"
   (`_same(None, "")`), so the resubmit goes through and the Base Name stays
   empty; only the browser's `required` enforces it. No data is wrong, but
   the acceptance criterion is not met on the server. **Recommend: fix**:
   refuse an empty Base Name on resubmit, in the service.

#### (ข) Notes

3. **The live preview does not show the name the server will save** (user
   story 8). After the first keystroke the preview is a plain space-joined
   string, without the category prefix, ` - ` separators or unit spacing.
   Verified: the same `compose()` is on master for new requests, so this is
   older than STORY-009. **Recommend: a separate story** (the preview should
   ask the server's name composer), not a STORY-009 change.
4. **The Duplicate Check search runs while the row is claimed**
   (`_duplicate_line` after `_claim_from_needs_info`). On SQLite that holds
   the database write lock for the fuzzy search over the snapshot (~22k
   rows); other writers wait. No wrong data. **Recommend: fix** (cheap: work
   it out before the claim, as the Search name already is).
5. **Ownership rule written twice**: `queue_view._is_owner` repeats
   `is_requester`/`_named_originator`. **Recommend: fix** (reuse them).
6. **Two maps from RequestError to HTTP status** (`routes/requests.py
   _error_status`, `routes/queue.py _error`). Already noted in ticket 03
   (queue answers 422 for a deleted request). **Recommend: no change** in
   this story.
7. **"Who is Procurement" in two forms**: `procurement_recipients` lists the
   roles by hand; `notifies_procurement` uses the `ROLES` order. Same result
   today. **Recommend: fix** (derive the list from `ROLES`).
8. **Same whitespace collapse twice** (`_same`'s inner `text()` and
   `_shown`). **Recommend: fix** (one helper).
9. **`queue_page` has no return type** (CLAUDE.md: type hints on all
   functions); the branch changed it. **Recommend: fix.**

#### Outcome (2026-10-19)

- **1 fixed** in `_validated_fields`, shared by new requests and resubmits:
  the code system must be in `catalog.systems_for_factory` (linked to the
  request's Plant and active), the same list the form offers. **The bug is on
  master too** (new requests). Tests in `tests/test_story009_closing.py`:
  another Plant's system and the inactive stock system, both on a new request
  and on a resubmit, plus over HTTP.
- **2 fixed:** `resubmit_request` refuses an empty Base Name before the
  claim, even when nothing else changed.
- **4 fixed:** the Duplicate Check line is worked out before the claim. The
  race tests of tickets 03/04 still catch a claim without
  `AND status='needs_info'` (3 of 3 fail with it, 5 of 5 pass without).
  Their helper comment in `tests/test_requeue.py` ("the winner holds the
  claim; the other UPDATE must wait") no longer describes what the sleep
  does; left as is because it is an existing test (Peter to decide).
- **5, 7, 8, 9 fixed** as refactors: `requests.named_on` (queue card),
  `procurement_recipients` derived from `ROLES`, one `_flat` helper,
  `queue_page -> HTMLResponse`. No behaviour change, so no failing test
  first; mutation checks show existing tests cover each (owner rule: 2 fail,
  whitespace collapse: 2 fail, role list: 8 fail).
- Tests: 9 new (written first, all 7 that check a fix failed before it).
  Old tests: none changed. Suite: 720 passed.

### TODO after STORY-009 merges
- **Open a new story on master: the name preview does not match the saved
  name**, on both the new-request page and the resubmit page (closing
  review item 3). After the first keystroke the preview drops the category
  prefix, the ` - ` separators and unit spacing; it should come from the
  server's name composer.
- Add to STORY-013's Notes the name-setter rule from ticket 05 (see its
  Notes).

#### Review of the closing fix diff only (2026-10-19)

No new (ก). One (ข) note: if the request's stored code system has been
switched off or unlinked since, the resubmit form still shows it selected
(`with_current`); an untouched form passes, but editing another field is
refused with "ระบบรหัสนี้ใช้กับโรงงานของคำขอไม่ได้". That matches how a
switched-off stored group or sub-category already behaves. Also confirmed:
`_validated_fields` has only the two callers; the Base Name check runs after
the ownership and status checks; the Duplicate Check inputs are unchanged;
`named_on` no longer matches an empty actor email to a missing originator
(cannot happen: events always record the Account email).
