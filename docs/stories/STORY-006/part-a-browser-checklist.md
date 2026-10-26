# STORY-006 part A: browser checklist before merge (Peter)

Status: open · Run on Peter's machine, `APP_ENV=dev`, on the real `dev.db`
Backup: `dev.db.bak-2026-10-26` (ignored by git). Keep it until every box
below is ticked.

## dev.db migration (done by Claude, 2026-10-26)

| Step | Result |
|---|---|
| Backup `dev.db` → `dev.db.bak-2026-10-26` | done, byte-identical (`cmp`) |
| `git check-ignore` on the backup | was not ignored → added `*.db.bak-*` to `.gitignore` (`da7bc6e`) |
| Revision before | `e52ce808c5d5` |
| `alembic upgrade head` | 3 migrations: `db44eba12672` (base_name), `d7601fa1002b` (login_ip_failures), `e63600116a2f` (pending checks) |
| Revision after | `e63600116a2f` (head) |
| `python -m app.seed` | "Seed complete." |
| Row counts before → after | all 19 tables the same (accounts 3, item_requests 2, request_events 13, item_snapshot 13391, running_register 130, retired_codes 2, …); new `login_ip_failures` 0 |
| `alembic check` (drift) | "No new upgrade operations detected." |

## Where the log is on the dev machine

There is no log file. `app/main.py` logs with `logging.basicConfig` to
**the PowerShell window running `uvicorn`**. The `unblock_ip` command runs in
a second window and prints to that window.

## Start

```powershell
cd D:\dev\item-request-portal
.\.venv\Scripts\Activate.ps1
$env:APP_ENV = "dev"
uvicorn app.main:app --port 8000
```

Use **http://127.0.0.1:8000** (not `localhost`, which may go over IPv6 `::1`).

## Checklist

- [ ] 1. The app starts with no error in the uvicorn window
- [ ] 2. Log in with your own Administrator Account → the queue shows the 2
      existing requests (data kept through the migration)
- [ ] 3. Open a request, My requests and the Account admin page: each opens
      with no error
- [ ] 4. Log out, log in once with a wrong password, then with the right
      one → you are in (a failed login does not stop the right one)
- [ ] 5. **IP limit:** in a second PowerShell window, fire 50 failed logins:
      ```powershell
      1..50 | ForEach-Object { try { Invoke-WebRequest -Uri http://127.0.0.1:8000/login -Method Post -UseBasicParsing -Body @{ email = "spray$_@test.local"; password = "wrong-password" } | Out-Null } catch {} }
      ```
      → the login page now shows the Thai "wait 15 minutes" message, and the
      uvicorn window shows a line `login_ip_blocked ip=127.0.0.1 until=…`
- [ ] 6. In the second window (`$env:APP_ENV = "dev"` set there too):
      `python -m app.unblock_ip 127.0.0.1` (no `--by`) → `Error: the
      following arguments are required: --by`, and `$LASTEXITCODE` is `1`
- [ ] 7. `python -m app.unblock_ip 127.0.0.1 --by Peter` → `Unblocked
      127.0.0.1.`, `$LASTEXITCODE` is `0`, and the second window shows
      `login_ip_unblocked ip=127.0.0.1 by=Peter`
      **(fails today: see the note below; needs the fix first)**
- [ ] 8. Log in again in the browser → it works

## Note: item 7 fails today (found 2026-10-26)

Checked on a copy of `dev.db`: the command unblocks (exit 0) but prints no
`login_ip_unblocked` line anywhere. `app/unblock_ip.py` never sets up
logging (only `app/main.py` calls `basicConfig`), so the INFO line is
dropped. The ticket 08 test passes because `caplog` captures the line
itself. Ticket 08's "unblocks and logs who" therefore does not hold
outside tests: (ก).
