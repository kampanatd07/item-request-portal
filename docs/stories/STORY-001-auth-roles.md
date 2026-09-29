# STORY-001: Login + roles

Status: todo

## Why
Anyone who has the URL can approve requests, override codes and export files.
Since the portal now owns the group's central running register, an unauthorised
approval burns a real code number permanently. This must exist before the
4 plants get access.

## Scope
- App-managed **Accounts** (email + password, hashed with a standard library such
  as `passlib[bcrypt]` or `argon2-cffi`) — decision already recorded in
  `docs/decisions.md` (2026-07-24): simple auth first, Azure AD SSO later
- **Roles**: Requester (tied to exactly one Plant), Procurement, Administrator
  (the Data Steward + one backup; more than one allowed). One Role per Account
- Session cookie auth (signed, HttpOnly, SameSite=Lax), `SECRET_KEY` from env.
  Session expires 8 hours after login, no "remember me"; a password change or
  deactivation invalidates existing sessions immediately
- Login / logout pages (Thai UI)
- Passwords: minimum 12 characters; Administrator sets a temporary password and
  the Account must change it at first login; self-service change-password page
- Lockout: an email is locked for 15 minutes after 10 consecutive failed logins
  (counter stored in the DB, not in memory)
- Administrator page to create Accounts, assign Role + Plant, change a Plant,
  deactivate an Account and reset its password. Accounts are never deleted and
  their email is not editable
- CLI command to create the first Administrator: `python -m app.create_admin`
- Replace every hardcoded `actor="procurement"` in routes with the logged-in
  Account's email
- `requester_name` / `requester_email` on the form prefilled from the Account
  and not editable
- Plant: locked to the Account's Plant for a Requester; Procurement and
  Administrator choose it. When submitting on someone's behalf, the request is
  in their own name and the originator goes in the note
- "My requests" page: read-only list of the Account's own requests with Request
  Status, `review_note` and Central Code
- `in_review` means "checked by Procurement, waiting for Approval"; change its
  Thai label from "กำลังตรวจสอบ" to "ตรวจแล้ว รออนุมัติ"

## Authorisation matrix
Approval, re-categorising a request that already has a code, and overriding a
code all consume the Running Register, so they are Administrator-only
(decision 2026-09-29, Governance v1 §3).

| Action | Requester | Procurement | Administrator |
|---|---|---|---|
| Submit request | own Plant only (locked) | any Plant, in own name | any Plant, in own name |
| "My requests" page | yes | yes | yes |
| Queue, edit name, re-categorise (before a code), Needs Info, reject, set In Review | no | yes | yes |
| **Approval, re-categorise after a code, override code** | no | no | yes |
| Export, mark created | no | yes | yes |
| Snapshot upload, config pages, Account admin | no | no | yes |
| Change own password | yes | yes | yes |

## Out of scope
- Azure AD / Microsoft 365 SSO (structure the code so a provider can be swapped:
  keep "who is the logged-in Account" behind one dependency function)
- Password reset by email (Administrator resets manually for v1)
- Audit of logins
- Plant Steward as a Role (Governance §2 preliminary check) — approval workflow
  beyond procurement is out of scope for v1
- Requester editing and resubmitting a Needs Info request — **STORY-009**
- One Account for several Plants

## Acceptance criteria
1. Unauthenticated request to any page except `/login` redirects to `/login`
2. Requester cannot open `/queue`, `/exports`, `/admin/*` (403)
3. Requester cannot submit for another Plant even by editing the form (server-side check)
4. Every `RequestEvent.actor` holds the real Account's email
5. Passwords are never stored or logged in plain text
6. Wrong password shows a Thai error, does not reveal whether the email exists
7. Existing 113 tests still pass (add an authenticated test client fixture)
8. Procurement gets 403 on Approval, override code, and re-categorising a
   request that has a code — and the Running Register does not change
9. The 10th consecutive failed login locks that email for 15 minutes, with the
   same error message as AC6
10. An existing session stops working after a password change, after
    deactivation, and 8 hours after login
11. First login always redirects to change password; a password shorter than
    12 characters is rejected
12. "My requests" shows only the logged-in Account's requests

## Files likely touched
`app/models/core.py` (Account), new `app/services/auth.py`, new `app/routes/auth.py`,
every file in `app/routes/`, `app/templates/base.html`, `app/templating.py`
(status label), `tests/conftest.py`, new migration, `.env.example`, `requirements.txt`

## Domain rules that apply
HANDOFF §6.5 (batch mode migration), §6.8 (verify migration on fresh DB)

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes

### Grilling session 1 (2026-09-28) — paused, resume with `/grill-with-docs`
Glossary updated in `CONTEXT.md` (Access: Account, Role, Administrator).

Settled:
- Q1 The login is an **Account** (one email, one Role). "user" stays avoided.
- Q2 **Administrator** Role, can be more than one: Peter + one backup
  (Governance §1: Data Steward 1 + backup 1). Superset of Procurement.
- Q3 "My requests" page is in this story: read-only list of the Account's own
  requests with Request Status and Central Code.
- Q4 Procurement submitting on someone's behalf: the request is in the
  Procurement Account's name; Procurement picks the Plant (a Requester cannot,
  it is the Account's Plant); the originator's name goes in the note.
- Q5 A Requester Account belongs to exactly one Plant (no many-to-many yet).
- Q6 Accounts are deactivated, never deleted; email is not editable;
  Administrator may change an Account's Plant (old requests keep their Plant).
- Q7 Administrator sets a temporary password; forced change at first login;
  self-service change-password page; minimum 12 characters.
- Q8 Lock an email for 15 minutes after 10 consecutive failed logins, counter
  stored in the DB; same Thai error message as AC6.

- Q9 (2026-09-29) Only **Administrator** approves, re-categorises after a code
  exists, and overrides a code — all three consume the register
  (`services/requests.py:167`, `:250`). Procurement keeps review, name edit,
  re-categorise before a code, needs_info, reject, export. Recorded in
  `docs/decisions.md`; `CONTEXT.md` gains **Approval**.
- Q10 (2026-09-29) The **Requester edits and resubmits** a Needs Info request
  in the web (matches the glossary). Chosen over Procurement re-keying replies,
  because Procurement can only edit the whole name, not size/brand/model/UoM,
  which would bypass name composition. Split into **STORY-009** (Q14);
  Q15–Q18 continue there.
- Q11 Session expires 8 hours after login; no "remember me"; a password
  change or deactivation invalidates existing sessions immediately.
- Q12 Plant Steward is not a Role in v1 (approval workflow beyond procurement
  is out of scope); a Plant Steward uses a Requester Account.
- Q13 `in_review` now means "Procurement has checked it, waiting for Approval"
  (glossary: **In Review**). No new status. Administrator may still approve
  straight from `submitted`. Thai label must change to match.

Open (asked, not yet answered — recommendation in brackets):
- none for this story.

Matrix, scope and acceptance criteria updated 2026-09-29. Next: `/to-spec`.
