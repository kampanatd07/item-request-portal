# 04: Account administration

Status: todo
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

- [ ] Administrator can create an Account for each Role; a Requester without
      a Plant is refused with a Thai error
- [ ] Duplicate email is refused with a Thai error
- [ ] There is no way to delete an Account or edit its email
- [ ] After deactivation, the Account cannot log in and its existing session
      is rejected (AC10, deactivation part)
- [ ] After a password reset, the old password fails, the temporary one works,
      and existing sessions are rejected
- [ ] Changing a Requester's Plant leaves their old requests' Plant unchanged
- [ ] Procurement and Requester get 403 on these pages
