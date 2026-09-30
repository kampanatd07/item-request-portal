# 04: Account administration

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-001
Blocked by: 01

**What to build:** An Administrator manages Accounts in the web instead of the
command line: list Accounts, create one with Role, Plant (Requester only) and a
temporary password, change a Requester's Plant, deactivate an Account, and
reset a password to a new temporary one. Accounts are never deleted and their
email cannot be edited, because request history names Accounts by email.
Deactivating or resetting bumps the session version, so that Account's open
sessions stop working at once. A new or reset Account is marked
must-change-password (the forced change itself is ticket 05). Changing a Plant
does not move existing requests. Only Administrators reach these pages
(`require_role` from 01). No migration: the columns exist from 01.

- [x] Administrator can create an Account for each Role; a Requester without
      a Plant is refused with a Thai error
- [x] Duplicate email is refused with a Thai error
- [x] There is no way to delete an Account or edit its email
- [x] After deactivation, the Account cannot log in and its existing session
      is rejected (AC10, deactivation part)
- [x] After a password reset, the old password fails, the temporary one works,
      and existing sessions are rejected
- [x] Changing a Requester's Plant leaves their old requests' Plant unchanged
- [x] Procurement and Requester get 403 on these pages

Implementation notes (2026-09-29, decisions by Peter):
- Temporary passwords are random (`secrets.token_urlsafe`, 16 chars), shown
  once, sent with `Cache-Control: no-store`, never logged.
- Also built: reactivate (clears failed-login count and lock, keeps old
  sessions dead because deactivation bumped the session version) and Role
  change (to Requester needs a Plant; any other Role clears it; a Role change
  ends open sessions, a Plant-only change does not).
- Guards: no self-deactivation; the last active Administrator can be neither
  deactivated nor demoted.
- Every admin action is logged to logger `app.accounts` (who, action, target);
  a DB audit trail is STORY-011.
- `SnapshotImport.uploaded_by` now records the uploading Account's email.
- Code review fixes: the last-Administrator guard locks active Administrator
  rows (FOR UPDATE, ordered by id to avoid deadlocks) so two Administrators
  cannot deactivate each other at once (Postgres test: STORY-006 AC4); emails
  must match local@domain.tld with no whitespace/control characters, and every
  value written to the account log has CR/LF escaped.
