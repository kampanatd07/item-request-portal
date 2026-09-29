# 05: Password lifecycle + session expiry

Status: done
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

- [x] First login of a must-change Account always lands on change password,
      and other pages redirect there until it is done (AC11)
- [x] A password shorter than 12 characters is refused with a Thai error (AC11)
- [x] After a password change, another session of the same Account is
      rejected (AC10, password part)
- [x] A session older than 8 hours is rejected; one just under 8 hours works
      (AC10, expiry part)
- [x] Wrong current password on change is refused

Implementation notes (2026-09-29, decisions by Peter):
- `session_account` (session only, used by the change-password page) and
  `current_account` (also refuses a must-change Account) in `routes/deps.py`;
  every router uses `current_account`, so the forced change covers new routes.
- 8 hours count from the original login, also after a password change; the
  re-issued cookie's Max-Age is what is left (8 h − elapsed). Login cookie
  Max-Age is 8 h. `SESSION_MAX_HOURS` setting, default 8.
- New password must differ from the current one; confirmation must match.
- Login page (code review, Peter's call): no time-based "expired" message —
  the browser drops the cookie itself at Max-Age, so expiry cannot be told
  apart from "never logged in". Instead a fixed notice "ระบบจะออกจากระบบ
  อัตโนมัติหลังเข้าใช้งาน 8 ชั่วโมง", plus "กรุณาเข้าสู่ระบบใหม่" when a cookie
  was sent but no longer counts (expired, version bumped, deactivated,
  tampered); that dead cookie is deleted so the notice shows once.
- Password change uses Post/Redirect/Get (303 to `?done=1`), so a refresh does
  not resend the old password.
- Guessing the current password on this page is not rate-limited yet — ticket
  06 counts it toward the lockout.
- Found on the way: `migrations/env.py` called `fileConfig()` with the default
  `disable_existing_loggers=True`, which silently disabled `app.accounts`
  whenever migrations ran in the same process; now `False`.

