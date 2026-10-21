# 07: Login refuses a client IP after 50 failures in 15 minutes

Status: todo
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01, 06

**What to build:** password spraying (one password across many emails) is
stopped at the door (AC 5; built in the app, decisions.md 2026-10-21). Each
failed login (unknown email, wrong password, locked, deactivated) counts
against the client IP from ticket 06. 50 failures within a 15-minute window
block that IP for 15 minutes; a window older than 15 minutes starts again
from zero; a success does not reset the count. A blocked IP gets HTTP 429
and the login page with "มีการเข้าสู่ระบบผิดจากเครื่องนี้หลายครั้งเกินไป
กรุณารอ 15 นาทีแล้วลองใหม่", before any password hashing. Counts live in a
new table (row locked `FOR UPDATE`; survives restarts and processes); rows
idle for over a day are removed when a failure is recorded. The block is
logged once, with the IP and no password. The per-email lockout stays; both
apply.

The login form is a plain form POST (no HTMX, no `hx-boost`; checked
2026-10-21), so the browser shows the 429 page as it is and
`htmx:beforeSwap` needs no change. If the login form ever moves to HTMX, 429
must be added there.

- [ ] Migration for the counter table (the only migration besides a drift
      fix in 01), read line by line, verified on a fresh DB
      (`alembic upgrade head` + seed) and by the drift check in CI
- [ ] Through `POST /login` with the fake clock: 49 failures get the normal
      error, the 50th blocks; a blocked IP is refused even with the right
      password; another IP is not affected
- [ ] The block lifts after 15 minutes; a window older than 15 minutes
      restarts the count; a success in between does not reset it
- [ ] A blocked IP is refused without hashing (Argon2 not called)
- [ ] The 429 response contains the Thai message
- [ ] Guard test: the login form posts without `hx-` attributes (if it ever
      fails, add 429 to `htmx:beforeSwap` in the same change)
- [ ] The block is logged with the IP, never a password
- [ ] Stale rows are pruned
- [ ] PostgreSQL (`postgres` marker): N parallel failures from one IP (N
      well above 50) count exactly as N sequential ones; the block starts at
      50
- [ ] Browser checklist (Peter, `APP_ENV=dev`): fail 50 times from one
      machine → the Thai message shows on screen; after 15 minutes (or a
      moved clock) login works; a second machine was never blocked
- [ ] CI green
