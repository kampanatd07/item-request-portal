# STORY-016: Re-check the acting role under the lock for other Administrator actions

Status: todo · Depends on: STORY-006 ticket 04 · Not a go-live condition (Peter, 2026-10-23)
Triage: needs-triage

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

## Out of scope
- Actions open to Procurement or Requesters (their guard is a Role every
  Account of that kind keeps; a deactivated Account's session already ends
  through `session_version`).

## Acceptance criteria
_(at triage)_

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
