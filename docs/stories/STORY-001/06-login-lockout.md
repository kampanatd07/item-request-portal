# 06: Login lockout

Status: done
Triage: ready-for-agent
Parent: STORY-001
Blocked by: 01

**What to build:** Guessing passwords on the public login page stops working.
After 10 consecutive failed logins for one email, that email is locked for
15 minutes; during the lock even the right password fails, with the same Thai
error message as any failed login, so the lock does not reveal that the email
exists. The lock lifts on its own when 15 minutes pass. A successful login
resets the counter. The counter and lock time are stored on the Account (from
01), not in memory, so a restart does not clear them. Time comes from the
clock seam. No migration.

- [x] The 10th consecutive failure locks the email for 15 minutes (AC9)
- [x] During the lock the correct password fails with the same message as a
      wrong password (AC9, AC6)
- [x] After 15 minutes the correct password works again
- [x] A successful login before the 10th failure resets the count
- [x] Failed logins for an unknown email do not error and look identical

Added 2026-09-29 (Peter): a wrong **current password on the change-password
page** (ticket 05, `change_own_password`) counts toward the same consecutive
failed-login counter and lockout, so that page cannot be used to guess a
password without limit.

Implementation notes (2026-09-29, decisions by Peter):
- The Account row is locked (FOR UPDATE) while counting, so parallel guesses
  on Postgres cannot slip past 10 (Postgres test: STORY-006 AC5).
- The password is always hashed/verified, also during a lock, so a locked
  email answers with the same message after the same work.
- A lock that has run out clears itself and the count starts again at 0;
  failures during a lock are not counted and never extend it.
- Change-password page: a wrong current password counts toward the same
  counter; the failure that locks also ends that session (stolen-cookie
  guess). While locked, the change is refused even with the right current
  password.
- Administrator password reset clears the lock; the Accounts table shows
  "ล็อกถึง HH:MM น." in Thai time (UTC+7; the DB keeps UTC) while a lock runs.
- Each lock is logged: `app.accounts` `by=system action=locked target=<email>`.
- Per-IP limiting (password spraying) is STORY-006 AC5: check the platform
  first, build it in the app only if the platform has none.
- Code review fix: on the change-password page the right current password
  resets the count and commits at once, before the new-password checks can
  refuse and roll it back (a mistyped confirmation no longer leaves the count
  at 9).

