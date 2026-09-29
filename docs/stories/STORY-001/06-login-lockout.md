# 06: Login lockout

Status: todo
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

- [ ] The 10th consecutive failure locks the email for 15 minutes (AC9)
- [ ] During the lock the correct password fails with the same message as a
      wrong password (AC9, AC6)
- [ ] After 15 minutes the correct password works again
- [ ] A successful login before the 10th failure resets the count
- [ ] Failed logins for an unknown email do not error and look identical

Added 2026-09-29 (Peter): a wrong **current password on the change-password
page** (ticket 05, `change_own_password`) counts toward the same consecutive
failed-login counter and lockout, so that page cannot be used to guess a
password without limit.
