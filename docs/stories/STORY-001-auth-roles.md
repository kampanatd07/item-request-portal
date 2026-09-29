# STORY-001: Login + roles

Status: planned
Triage: ready-for-agent

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

### Spec (written by /to-spec, 2026-09-29)

#### Problem Statement
Anyone who has the portal URL can approve Item Requests, override Central Codes,
export files and change reference data. Every Approval mints a Running Number
from the Running Register that can never be reused, so one unauthorised click
permanently burns a code in the group master. Request history records the
placeholder "procurement" instead of a real person, and a Requester can type
any name, email or Plant on the form. The portal cannot be opened to the four
Plants until it knows who is using it and what they may do.

#### Solution
Every page except login requires an Account. Each Account has one Role:
Requester (tied to one Plant), Procurement, or Administrator (the Data Steward
and one backup). The portal fills in who the Requester is and, for a Requester,
locks the Plant. Procurement reviews and readies requests (In Review), but only
an Administrator performs the three actions that consume the Running Register:
Approval, re-categorising a request that already has a Central Code, and
overriding a code. Requesters get a "My requests" page to follow their
requests. Administrators create and deactivate Accounts and set temporary
passwords; Accounts change their own password, and repeated wrong passwords
lock the email temporarily.

#### User Stories
1. As a Requester, I want to log in with my email and password, so that the
   portal knows which Plant I request for.
2. As a Requester, I want my name and email filled in automatically and not
   editable, so that my requests are always traceable to me.
3. As a Requester, I want my Plant preselected and locked, so that I cannot
   submit for the wrong Plant by mistake.
4. As Procurement, I want a Requester who tampers with the form to be refused
   by the server, so that a request can never land in another Plant's master.
5. As a Requester, I want a "My requests" page listing my requests with their
   Request Status, so that I do not have to ask Procurement for updates.
6. As a Requester, I want to see Procurement's note on a Needs Info or rejected
   request, so that I know what is missing or why it was refused.
7. As a Requester, I want to see the Central Code on "My requests" once it is
   issued, so that I can start using the item.
8. As a Requester, I want "My requests" to show only my own requests, so that
   other people's requests stay private.
9. As a Requester, I want to be refused access to the queue, exports and
   Administrator pages, so that I cannot change requests by accident.
10. As a person without an Account, I want to be sent to the login page from
    any URL, so that I know I must log in.
11. As an Account holder, I want a wrong password to show a Thai error that does
    not reveal whether my email exists, so that attackers cannot find valid
    emails.
12. As an Account holder, I want to be forced to change the temporary password
    at first login, so that the password the Administrator knows is not the
    one I keep.
13. As an Account holder, I want to change my own password at any time, so that
    I can react if I think it leaked.
14. As an Account holder, I want passwords shorter than 12 characters
    rejected, so that my Account is not easy to guess.
15. As an Account holder, I want to log out, so that the next person at a
    shared plant PC cannot act as me.
16. As an Account holder, I want my session to end 8 hours after login, so that
    a PC left logged in does not stay open indefinitely.
17. As an Account holder, I want my other sessions to stop working when I
    change my password, so that anyone using an old session is locked out.
18. As an Administrator, I want an email locked for 15 minutes after 10
    consecutive wrong passwords, so that nobody can guess passwords
    unhindered on the public URL.
19. As an Account holder, I want the lock to lift by itself after 15 minutes,
    so that I am not stuck waiting for an Administrator.
20. As Procurement, I want to open the queue and see all Plants' requests, so
    that I can review work from every Plant.
21. As Procurement, I want to edit the Item Name, re-categorise a request that
    has no Central Code yet, send it back as Needs Info, or reject it, so that
    it is correct before Approval.
22. As Procurement, I want to mark a request In Review, so that the
    Administrator knows it has been checked and waits for Approval.
23. As Procurement, I want the In Review label in Thai to say it has been
    checked and awaits Approval, so that nobody reads it as "still being
    checked".
24. As Procurement, I want to be refused Approval, re-categorising a coded
    request, and code override, with the Running Register left untouched, so
    that only the Data Steward consumes Running Numbers, as Governance
    requires.
25. As Procurement, I want to submit a request for any Plant in my own name and
    note the originator, so that I can help someone who phoned me.
26. As Procurement, I want to create Export Batches and mark requests created,
    so that I can finish the AX/D365 import.
27. As an Administrator, I want to approve requests from In Review or straight
    from submitted, so that I am not forced through an extra step when I
    checked the request myself.
28. As an Administrator, I want to re-categorise a coded request and override a
    code, so that I can fix mistakes as the Data Steward.
29. As an Administrator, I want every RequestEvent to record the real Account's
    email, so that the audit trail shows who did what.
30. As an Administrator, I want to create an Account with a Role, a Plant (for a
    Requester) and a temporary password, so that plant staff can start using
    the portal.
31. As an Administrator, I want to change a Requester Account's Plant, so that
    staff who move Plants keep one Account, while their old requests keep
    their original Plant.
32. As an Administrator, I want to deactivate an Account instead of deleting
    it, so that history still names a real Account and the person can no
    longer log in.
33. As an Administrator, I want a deactivated Account's open sessions to stop
    working immediately, so that someone leaving the company loses access at
    once.
34. As an Administrator, I want to reset an Account's password to a new
    temporary one, so that I can help someone who forgot theirs without email
    reset.
35. As an Administrator, I want the email to be fixed once the Account exists,
    so that history keyed by email stays correct.
36. As an Administrator, I want more than one Administrator Account, so that
    the backup Data Steward can approve when I am away.
37. As an Administrator, I want to be the only Role that uploads Snapshots and
    edits config and Accounts, so that group-wide reference data stays under
    the Data Steward.
38. As the person deploying the portal, I want to create the first
    Administrator from the command line, so that a fresh install is usable
    without editing the database.
39. As the person deploying the portal, I want the session signing key to come
    from an environment variable, so that no secret lives in the code.
40. As a future developer, I want "who is the logged-in Account" behind one
    dependency, so that Azure AD SSO can replace the password login later.

#### Implementation Decisions
- **Account model** (new table): email (unique, immutable), display name, Role
  (`requester` / `procurement` / `administrator`), Plant (required for a
  Requester, empty otherwise), password hash, must-change-password flag,
  active flag, a session version counter, failed-login count and locked-until
  time. Created with an Alembic migration (batch mode for SQLite) and verified
  on a fresh DB, since tests use `create_all`.
- **Auth service** (new, deep module; all auth rules live here): create
  Account, authenticate (email + password → Account or one generic failure,
  applying and resetting the lockout), change password (min 12 chars, bumps
  session version, clears must-change), reset password (Administrator; sets a
  temporary password + must-change, bumps session version), deactivate (bumps
  session version), change Plant. Password hashing uses a standard library
  (bcrypt or argon2); the choice is left to implementation.
- **Clock seam**: the auth service reads "now" from one injectable dependency
  so tests can move time for the 15-minute lockout and the 8-hour expiry.
- **Session**: signed, HttpOnly, SameSite=Lax cookie holding Account id,
  session version and login time; signed with `SECRET_KEY` from env. A request
  is authenticated only if the Account exists, is active, the version matches,
  and login time is under 8 hours ago. No "remember me".
- **Current-Account dependency**: one function resolves the logged-in Account;
  every route depends on it (the only thing an SSO provider would replace).
  Unauthenticated → redirect to login; must-change-password → redirect to
  change password. Role guards sit on routes per the Authorisation matrix;
  Administrator passes every Procurement guard.
- **Service-level guard for the Running Register** (seam 3, option b): the
  request service functions that mutate requests take the acting Account
  instead of an actor string. Approval, change category on a request that has
  a Central Code, and override code raise a domain error unless the Account is
  an Administrator — checked before any register read, so the register never
  moves on refusal. Routes map that error to 403. `RequestEvent.actor` stores
  the Account's email.
- **Submission**: requester name and email come from the Account, not the form.
  For a Requester, the Plant is the Account's Plant regardless of what is
  posted (server-side, AC3). Procurement and Administrator choose the Plant.
- **Status semantics**: `in_review` means checked by Procurement, waiting for
  Approval. Its Thai label changes to "ตรวจแล้ว รออนุมัติ". Allowed transitions
  are unchanged.
- **Pages**: login, logout, change password, "My requests" (the Account's own
  requests, newest first: Item Name, Plant, Request Status, review note,
  Central Code), Administrator Account list/create/edit. The base layout shows
  the logged-in Account and hides links the Role cannot use. Thai UI text.
- **CLI**: `python -m app.create_admin` prompts for email, name and password and
  calls the auth service's create Account.
- **Config**: `SECRET_KEY` is required outside dev; `.env.example` documents
  it. New dependencies go in `requirements.txt`.

#### Testing Decisions
- Good tests assert behaviour visible from outside — status codes, redirects,
  Thai messages, what a page lists, whether the Running Register moved — not
  internal calls or table layouts.
- **Seam 1 (primary): HTTP through the existing TestClient fixture.** New
  fixtures: `client_as(role, plant=None)` creates an Account and logs in
  through the real login endpoint; `anon_client` for unauthenticated checks.
  The existing `client` fixture logs in as an Administrator so the 113 existing
  tests keep passing (AC7).
- **Seam 2: clock override** for lockout (AC9) and expiry (AC10).
- **Seam 3: service-level tests** for the Administrator-only register actions
  (AC8), with a conftest helper that returns an Account per Role. The 19
  existing `actor="..."` service calls across 7 test files switch to that
  helper.
- Every AC has at least one test, happy and failure paths (CLAUDE.md). AC5 is
  tested by reading the stored hash and asserting it is not the password and
  verifies correctly.
- New request tests use `central_ids()`.
- Prior art: `tests/test_queue.py` (HTTP + service mix, transition errors),
  `tests/test_submit_request.py` (form posts), `tests/test_codegen.py`
  (register assertions).
- Migration: run `alembic upgrade head` on a fresh SQLite DB by hand
  (HANDOFF §6 trap 8).

#### Out of Scope
- Azure AD / Microsoft 365 SSO (keep the one dependency swappable)
- Password reset by email; audit of logins
- Plant Steward Role (Governance §2) — approval workflow beyond procurement
- Requester editing and resubmitting a Needs Info request — STORY-009
- One Account for several Plants
- Emails of any kind — STORY-002

#### Further Notes
- Decision 2026-09-29 (only Administrators consume the register) and
  Governance v1 §1/§3 drive the matrix; decision 2026-07-24 drives simple auth
  first.
- The first deploy (STORY-006) must set `SECRET_KEY` and run `create_admin`.
- Existing requests keep their free-text requester name and email; no backfill
  to Accounts.

### Tickets (written by /to-tickets, 2026-09-29)
All in `docs/stories/STORY-001/`. Work order: 01 → 03 → 02 → 07 → 04 → 05 → 06.

| # | Ticket | Blocked by | ACs |
|---|---|---|---|
| [01](STORY-001/01-login-tracer-bullet.md) | Login tracer bullet (complete Account table, `require_role`) | — | 1, 5, 6, 7 |
| [02](STORY-001/02-role-guards-requester-submission.md) | Role guards + Requester submission | 01 | 2, 3 |
| [03](STORY-001/03-administrator-only-register.md) | Only Administrators consume the Running Register | 01 | 4, 8 |
| [04](STORY-001/04-account-administration.md) | Account administration | 01 | 10 (deactivation) |
| [05](STORY-001/05-password-lifecycle-session-expiry.md) | Password lifecycle + session expiry | 01 | 10, 11 |
| [06](STORY-001/06-login-lockout.md) | Login lockout | 01 | 9 |
| [07](STORY-001/07-my-requests-page.md) | "My requests" page | 02 | 12 |

Rules agreed for this story:
- **One migration only**, in 01, with every Account column. No other ticket
  adds a migration.
- `require_role` is built in 01, so 04 does not wait for 02.
- 02 and 03 both change the queue and request routes; do not run them in
  parallel worktrees.

Merge flow: each ticket gets its own branch off `story/001-auth-roles`
(`story/001-NN-short-name`, e.g. `story/001-01-login`; a branch cannot sit
*under* `story/001-auth-roles/` because that name is already a branch), and
merges back into `story/001-auth-roles` after Peter reviews it.
`story/001-auth-roles` merges into `master` **once**, when all 7 tickets are
done.

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

Matrix, scope and acceptance criteria updated 2026-09-29. Spec and 7 tickets written in
`## Plan`. Next: ticket 01.
