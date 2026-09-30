# STORY-011: Account admin audit trail in DB

Status: todo
Triage: needs-triage

## Why
Since STORY-001 ticket 04, every Account administration action (create,
Role/Plant change, deactivate, reactivate, password reset) is written only to
the application log (`logging` logger `app.accounts`: who, action, target).
Application logs on Render/Railway rotate and are not searchable from the
portal, so "who deactivated this Account, and when?" cannot be answered a few
weeks later. Request history already has a durable audit trail
(`RequestEvent`); Accounts should have the same.

## Scope
- A new append-only table (e.g. `account_events`: at, actor email, action,
  target Account, detail) via one Alembic migration, verified on a fresh DB
  (HANDOFF §6 trap 8)
- `app/services/auth.py` account admin functions write a row in the same
  transaction as the change; the application log line stays
- The Account admin page shows each Account's recent events
- Never store a password, hash or temporary password (same rule as the log)

## Out of scope
- Login audit (successful/failed logins) — out of scope for STORY-001 too
- Editing or deleting audit rows

## Acceptance criteria
1. Each of create, change Role/Plant, deactivate, reactivate and reset password
   writes exactly one row with actor, action, target and time
2. A refused action (e.g. last Administrator) writes no row
3. No row or log line ever contains a password, hash or temporary password
4. The migration runs cleanly with `alembic upgrade head` on a fresh DB

## Depends on
STORY-001 ticket 04. Lower priority than STORY-002/006/010 (Peter, 2026-09-29).

## Files likely touched
`app/models/core.py`, new migration, `app/services/auth.py`,
`app/templates/partials/accounts_table.html`, tests

## Domain rules that apply
HANDOFF §6 traps 5 and 8 (SQLite batch mode, verify migrations on a fresh DB).

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
