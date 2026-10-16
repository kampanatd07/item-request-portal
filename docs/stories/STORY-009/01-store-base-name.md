# 01: Store the Base Name; one validation path for request fields

Status: ready-for-agent
Triage: ready-for-agent
Parent: STORY-009
Blocked by: None (can start immediately)

**What to build:** A new Item Request remembers the Base Name the Requester
typed, so a later resubmit form can be prefilled with it. One Alembic
migration adds a nullable `base_name` column (batch mode); existing rows stay
empty, with no backfill. As a prefactor, the field validation and Item Name
composition of a new submission move into one service function that ticket 02
reuses for resubmit. The duplicate-candidates line written into the
`submitted` event moves into its own function too. Nothing a person sees
changes.

- [ ] A new submission stores the Base Name, cleaned the same way the Item
      Name composition cleans it
- [ ] Every existing test passes without any change to it; if one has to
      change, behaviour changed: stop and report
- [ ] Migration: `upgrade head` → `downgrade -1` → `upgrade head` on a fresh
      DB and on a copy of `dev.db`, then `python -m app.seed`; `alembic check`
      shows no drift (HANDOFF §6 traps 5 and 8)
- [ ] Tests use `central_ids()`
