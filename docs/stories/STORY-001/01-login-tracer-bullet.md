# 01: Login tracer bullet

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-001
Blocked by: None (can start immediately)

**What to build:** An Administrator created from the command line can log in to
the real app and log out; every page except login redirects an anonymous
visitor to the login page. At this stage any logged-in Account can still do
everything; later tickets narrow that. This ticket lays the foundation every
other STORY-001 ticket builds on:

- The **Account** table with **every column the story needs**, in **one**
  Alembic migration: email (unique, immutable), display name, Role
  (`requester` / `procurement` / `administrator`), Plant (required for a
  Requester only), password hash, must-change-password flag, active flag,
  session version, failed-login count, locked-until. **No other STORY-001
  ticket adds a migration**, so everything later is behaviour only.
- The auth service: create Account, authenticate (email + password → Account
  or one generic failure), password hashing with a standard library.
- A single injectable clock that the auth service reads "now" from.
- A signed, HttpOnly, SameSite=Lax session cookie holding Account id, session
  version and login time, signed with `SECRET_KEY` from env. A session counts
  only while the Account exists, is active and the version matches.
- One current-Account dependency (the only piece an SSO provider would
  replace) and a `require_role(...)` dependency where Administrator passes
  every Procurement check. `require_role` is built and tested here; ticket 02
  applies it to the existing routes, and 04 uses it for its new pages.
- Login and logout pages in Thai.
- `python -m app.create_admin` creating the first Administrator.
- Test fixtures: `client` logs in as an Administrator through the real login
  endpoint; `client_as(role, plant=None)`; `anon_client`.

- [x] Migration creates the complete Account table and runs cleanly with
      `alembic upgrade head` on a fresh SQLite DB (HANDOFF §6 trap 8; batch
      mode, trap 5)
- [x] Anonymous request to any page except login redirects to login (AC1)
- [x] Stored password is a hash, never the plain text, and verifies (AC5)
- [x] Wrong password and unknown email show the same Thai error (AC6)
- [x] A deactivated Account, or a session whose version no longer matches,
      is treated as logged out
- [x] `require_role` refuses a lower Role with 403 and lets Administrator
      through a Procurement check
- [x] `create_admin` creates an Administrator who can then log in
- [x] `SECRET_KEY` documented in `.env.example`; new packages in requirements
- [x] All 113 existing tests pass (AC7)
