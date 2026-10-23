# STORY-016: Re-check the acting role under the lock for other Administrator actions

Status: todo · Depends on: STORY-006 ticket 04 · Not a go-live condition (Peter, 2026-10-23)
Triage: needs-triage
**Priority: the first story after go-live** (Peter, 2026-10-23), because of
item 1 of the ticket 04 second review below: a `session_version` bump can be
lost, so sessions can survive a password reset.

## Why
A route's role guard runs when the request starts. An Administrator
deactivated or demoted a moment later is still past the guard, and the
action then runs with rights the actor no longer has. STORY-006 ticket 04
closed this for deactivate and change Role (`_lock_active_administrators`:
the actor must be among the active Administrators locked by the action,
else "สิทธิ์ของคุณเปลี่ยนไปแล้ว — กรุณาเข้าสู่ระบบใหม่"). The other
Administrator-only actions have the same gap, a few milliseconds wide.

## Scope, in Peter's order (2026-10-23)
1. **Approval** (issues a real Central Code from the Running Register):
   re-check the actor under the request/register locks before a number is
   taken.
2. Reset password (`reset_password`).
3. Reactivate (`reactivate_account`).
4. Code override (`override_code`).
Also look at: re-categorise after a code, reject after approval, register
actions (all Administrator-only).

## Test tidiness from the ticket 04 review (2026-10-23)
- (7) Done in ticket 04's fix: the two-Administrator test now checks A's
  result against the first action's label. Nothing left.
- (9) The "app on this PostgreSQL database" override (`http_on_pg` in
  `tests/test_pg_account_race.py`) repeats one in `tests/test_notify_resend.py`
  and each cleans up differently: move one shared fixture into conftest.

## From the ticket 04 second review (2026-10-23)
1. `deactivate_account` / `change_access` read the target Account before the
   Administrator lock and never lock or refresh it: stale `role` / `active`
   / `session_version` decide and are written back. Two Administrators on
   one Account at once can lose a `session_version` bump (e.g. a reset
   password's, so old sessions survive it) or log two "deactivate" lines.
   Fix: lock and refresh the target after the Administrator lock
   (`db.refresh(account, with_for_update=True)`). Existed before ticket 04.
2. The re-check covers deactivate and change Role only (the rest is this
   story's scope above); a shared `_require_active_administrator(db, acting)`
   for every Administrator service would close the class at once.
3. Deactivate's last-Administrator branch can no longer be reached by a
   legitimate actor (kept as a safety net); the test named for it now
   tests `PERMISSION_CHANGED`, and nothing tests the branch itself.
   Renaming or changing that test needs Peter first.
4. `change_access` validates the target and plant before the actor check:
   a just-removed Administrator gets "ไม่พบบัญชีนี้" / plant errors instead of
   `PERMISSION_CHANGED`. Check the actor first.
5. A refused or no-op change keeps the Administrator row locks until the
   request's session closes (after the page renders). Roll back before
   raising / returning.
6. `change_access` now locks all active Administrator rows even for a
   Requester's plant change; a lighter check (the actor's own row) would do
   for changes that cannot touch the last-Administrator rule.
7. The cycle test hand-rolls what `Race` does for two; generalise `Race` to
   N waiters and share its outcome helper.
8. `_all_done` and the test's `finally` both shut the pool down; `LABEL`
   repeats the labels the actions return.
9. `test_an_administrator_who_lost_the_role_meanwhile_is_refused` has no type
   hints (CLAUDE.md).

## Out of scope
- Actions open to Procurement or Requesters (their guard is a Role every
  Account of that kind keeps; a deactivated Account's session already ends
  through `session_version`).

## Acceptance criteria
_(at triage)_

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
