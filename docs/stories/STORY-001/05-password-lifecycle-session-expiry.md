# 05: Password lifecycle + session expiry

Status: todo
Triage: ready-for-agent
Parent: STORY-001
Blocked by: 01

**What to build:** Accounts own their password. An Account marked
must-change-password is redirected to a change-password page after login and
cannot reach any other page until it changes the password. Any Account can
change its own password from a Thai change-password page; passwords shorter
than 12 characters are refused. Changing the password bumps the session
version, so every other session of that Account stops working; the current
one continues. Sessions expire 8 hours after login, with no "remember me".
Time comes from the clock seam in 01, so tests move time instead of waiting.
No migration.

- [ ] First login of a must-change Account always lands on change password,
      and other pages redirect there until it is done (AC11)
- [ ] A password shorter than 12 characters is refused with a Thai error (AC11)
- [ ] After a password change, another session of the same Account is
      rejected (AC10, password part)
- [ ] A session older than 8 hours is rejected; one just under 8 hours works
      (AC10, expiry part)
- [ ] Wrong current password on change is refused
