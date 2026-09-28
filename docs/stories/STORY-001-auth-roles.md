# STORY-001: Login + roles

Status: todo

## Why
Anyone who has the URL can approve requests, override codes and export files.
Since the portal now owns the group's central running register, an unauthorised
approval burns a real code number permanently. This must exist before the
4 plants get access.

## Scope
- App-managed accounts (email + password, hashed with a standard library such as
  `passlib[bcrypt]` or `argon2-cffi`) — decision already recorded in
  `docs/decisions.md` (2026-07-24): simple auth first, Azure AD SSO later
- Roles: `requester` (tied to one factory), `procurement`, `admin`
- Session cookie auth (signed, HttpOnly, SameSite=Lax), `SECRET_KEY` from env
- Login / logout pages (Thai UI)
- Admin page to create users and assign role + factory
- CLI command to create the first admin: `python -m app.create_admin`
- Replace every hardcoded `actor="procurement"` in routes with the logged-in user
- `requester_name` / `requester_email` on the form prefilled from the user and
  not editable
- Requester's factory preselected and locked to their own

## Authorisation matrix
| Action | requester | procurement | admin |
|---|---|---|---|
| Submit request | own factory only | yes | yes |
| See own requests | yes | — | — |
| Queue, approve, reject, re-categorise, edit name/code | no | yes | yes |
| Export, mark created | no | yes | yes |
| Snapshot upload, config pages, user admin | no | no | yes |

## Out of scope
- Azure AD / Microsoft 365 SSO (structure the code so a provider can be swapped:
  keep "who is the user" behind one dependency function)
- Password reset by email (admin resets manually for v1)
- Audit of logins

## Acceptance criteria
1. Unauthenticated request to any page except `/login` redirects to `/login`
2. Requester cannot open `/queue`, `/exports`, `/admin/*` (403)
3. Requester cannot submit for another factory even by editing the form (server-side check)
4. Every `RequestEvent.actor` holds the real user's email
5. Passwords are never stored or logged in plain text
6. Wrong password shows a Thai error, does not reveal whether the email exists
7. Existing 113 tests still pass (add an authenticated test client fixture)

## Files likely touched
`app/models/core.py` (User), new `app/services/auth.py`, new `app/routes/auth.py`,
every file in `app/routes/`, `app/templates/base.html`, `tests/conftest.py`,
new migration, `.env.example`, `requirements.txt`

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

Open (asked, not yet answered — recommendation in brackets):
- Q9 Who may mint a Central Code? Governance §3 says only the central Data
  Steward. In code, approve (`services/requests.py:167`), re-categorise after a
  code exists (`requests.py:250`) and override code all consume the register,
  and the matrix above gives them to Procurement.
  [Only Administrator does those three; Procurement keeps review, name edit,
  re-categorise before a code, needs_info, reject, export. Record in
  `docs/decisions.md`.] → then fix Procurement's "Acts as the Data Steward"
  line in `CONTEXT.md`.
- Q10 Who resubmits after Needs Info? Glossary says the Requester; code has
  Procurement do it; no requester edit form exists.
  [Show `review_note` on "My requests"; Procurement edits and resubmits;
  requester self-edit becomes a new story; fix glossary wording.]
- Q11 Session lifetime. [8 hours from login, no "remember me"; password change
  or deactivation invalidates existing sessions immediately.]
- Q12 Plant Steward (Governance §2 preliminary check). [Not a Role in v1 —
  "approval workflow beyond procurement" is out of scope; add to Out of scope.]

Next after Q9–Q12: update the Authorisation matrix and acceptance criteria,
then `/to-spec`.
