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
