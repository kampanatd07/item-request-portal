# STORY-006: Deploy for the 4 plants

Status: planned (part A) · part B todo · Depends on: STORY-001, STORY-002, STORY-009 (requesters must be able to answer Needs Info before the plants get access), STORY-010 (code override must be validated before deploy), STORY-013 (a category change must not leave the old prefix in names exported to AX)
Triage: ready-for-agent

## Why
The app only runs on Peter's laptop. Plants need a URL.

## Scope
- GitHub repo (private) with CI: `pytest` on every push; red blocks merge
  (no branch protection set up; GitHub plan not yet checked (Peter): until
  then the rule is "Peter does not merge on red CI", HANDOFF §8)
- CI also runs `alembic upgrade head` against a fresh Postgres service container
  (catches trap HANDOFF §6.8, which SQLite tests miss)
- Deploy the existing `Dockerfile` to Render or Railway with managed Postgres
- `DATABASE_URL`, `SECRET_KEY`, the Graph mail settings (`MS_TENANT_ID`,
  `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MAIL_SENDER`, `MAIL_REPLY_TO`,
  `PUBLIC_BASE_URL`) as platform secrets (STORY-002; no SMTP). Leave
  `APP_ENV` **unset** (or `production`): the app then requires a real
  `SECRET_KEY`, marks the session cookie Secure and hides `/docs`. Never set
  `APP_ENV=dev` on the platform (STORY-001 pre-merge hardening)
- Daily DB backup (platform snapshot) + documented restore steps in README
- Postgres row lock on register allocation is already implemented
  (`with_for_update` in codegen.py) — verify with a concurrency test on Postgres

## Split (2026-10-21, Peter)
- **Part A — now, no Graph values needed:** CI (`pytest` + `alembic upgrade
  head` on fresh Postgres), the Postgres concurrency tests (AC 2, 4), login
  rate limit per IP (AC 5), one worker (AC 7). Start with CI + Postgres.
- **Part B — waits for IT:** deploy, backup/restore (AC 1, 3), real email
  (AC 8). AC 6 (external hosting policy) is asked of IT together with the
  Graph values; the answer decides the platform (HANDOFF §7).
- GitHub repo is private (confirmed 2026-09-28); GitHub plan not yet checked (Peter).
- AC 5: no platform check first (Peter, 2026-10-21) — the platform is not
  settled until the hosting answer, so the per-IP limit is built in the app.

## Out of scope
- Company VM / on-prem hosting (revisit per decisions.md)
- Custom domain

## Acceptance criteria
1. Fresh deploy from `main` comes up with migrations + seed applied automatically
2. Two simultaneous approvals in the same sub-category on Postgres get distinct
   consecutive codes
3. README "When things break" section has real log/backup/restore locations
4. Row locks (`FOR UPDATE`) tested on real Postgres: an approval or a
   re-categorise running at the same time as an export of the same request
   never races — the loser waits, re-checks status after the lock, and no
   exported request ends up with a code different from its export file
   (locks added in STORY-001 ticket 03; SQLite tests cannot run this).
   Same for Accounts: two Administrators deactivating or demoting each other
   at the same moment must leave at least one active Administrator (lock on
   active Administrator rows, taken in id order, STORY-001 ticket 04).
   Same for codes: an override that moves the register and an Approval in the
   same sub-category at the same moment never issue one number twice (request
   row, then register row, STORY-010 ticket 03). And email: two resends of
   the same notification at the same moment send one email (row lock and
   state check before sending, STORY-002); and a notifier that cannot get a
   request row within `lock_timeout` (30 s, `SET LOCAL` in the claiming
   transaction) gives up, leaving the requests `created` for the resend
   list, instead of hanging the background task (STORY-002 ticket 03)
5. Login is rate-limited per client IP (against password spraying: one
   password tried across many emails, which the per-email lockout of
   STORY-001 ticket 06 cannot see). First **check whether the chosen platform
   (Render/Railway, or a proxy/CDN in front) really offers IP rate limiting**
   and record what was found; if it does not, build it in the app (count per
   IP in the DB or a shared store, not in process memory, so it survives
   restarts and several instances). Also: parallel wrong logins for one email
   on Postgres never get past 10 (row lock from ticket 06)
6. **Before go-live:** confirm with Peter that the company data policy allows
   external hosting of item data (flagged in decisions.md 2026-07-24)
7. The app runs as **one worker process**, or `MAIL_RATE_PER_MINUTE` × number
   of worker processes (all instances included) ≤ 25. The mail limiter
   spaces sends per process (≥ 60/rate s apart), while Exchange Online limits sends per mailbox
   (about 30 a minute), so several workers at the default 25 would exceed
   it (STORY-002 ticket 02). Record the worker count chosen in the Dockerfile /
   start command and in README
8. **Before opening to the plants:** with IT's real Graph values on the
   deployed app, send one real email of each kind and check each arrives:
   (a) `created`, batched — one "mark created" click on two requests of the
   same requester gives one email listing both codes; (b) `needs_info` with
   the reason; (c) `rejected` after approval, saying the code is cancelled
   and must not be used. For each, check that Reply-To is `MAIL_REPLY_TO` and
   a copy is in the sender mailbox's Sent Items. Record the date and result
   here (STORY-002 was tested with a fake transport only)

## Files likely touched
`.github/workflows/ci.yml`, `Dockerfile`, `README.md`, `docker-compose.yml`, tests

## Plan

Spec for **part A** only (2026-10-21). Part B (deploy, backup/restore, real
email, AC 1, 3, 6, 8) gets its own spec once IT answers.

Tickets (part A): `docs/stories/STORY-006/01`-`07`. One branch
(`story/006-deploy-part-a`), one ticket at a time, in the order
01 -> 02 -> 03 -> 06 -> 07 -> 08 -> 04 -> 05 (Peter, 2026-10-21; 08 added
2026-10-22 from the ticket 07 review). Migrations: only 01
(if drift is found) and 07; any other ticket that needs one stops and asks.

### Problem Statement

Every safety net today runs on SQLite on Peter's laptop. SQLite ignores
`FOR UPDATE`, so none of the row locks that keep Central Codes unique,
exports consistent, the last Administrator in place and emails single have
ever run for real; and tests build the schema with `create_all`, so a broken
migration passes the whole suite (HANDOFF §6.8). Nothing runs the tests
automatically, so a red suite can be merged unnoticed. Once the portal is on
the internet, the per-Account lockout cannot see password spraying (one
password tried across many emails), and several worker processes would
together exceed the Exchange sending limit.

### Solution

- Every push runs the full test suite on GitHub Actions, next to a fresh
  PostgreSQL: the migrations are applied and seeded there, the migrated
  schema is compared with the models, and the concurrency tests run on real
  row locks. Peter sees red or green before he merges.
- Login refuses a client IP that has made 50 failed logins within 15 minutes,
  for 15 minutes, counted in the database. The client IP is taken from the
  proxy's `X-Forwarded-For` only when the connection comes from a trusted
  proxy.
- The app runs as exactly one worker process, written in the start command
  and in the README.

### User Stories

1. As Peter, I want the test suite to run on every push, so that I never merge a branch whose tests fail.
2. As Peter, I want a red/green result on each branch before I approve its merge, so that the "no merge on red" rule is easy to follow without branch protection.
3. As Peter, I want CI to apply every migration to an empty PostgreSQL database, so that a migration that only works on SQLite is caught before deploy.
4. As Peter, I want CI to seed that migrated database, so that the start command of the container (migrate, seed, serve) is proven end to end.
5. As Peter, I want CI to fail when the migrated schema differs from the models, so that a model change without a migration (or a wrong migration) cannot pass just because tests use `create_all`.
6. As a developer on Windows without PostgreSQL, I want `pytest` to keep passing locally with the PostgreSQL tests skipped, so that local work stays as fast as today.
7. As a developer, I want to run the PostgreSQL tests locally when I do have a PostgreSQL (e.g. the compose `db` service), by setting one environment variable.
8. As a developer, I want each PostgreSQL test to start from its own freshly migrated and seeded database, so that tests cannot leak data into each other.
9. As an Administrator, I want two Approvals in the same Sub-Category at the same moment to get distinct consecutive Central Codes, so that no number is issued twice (AC 2).
10. As an Administrator, I want an Approval or a re-categorise racing an export of the same request to wait for the other and re-check the status, so that no exported request ends up with a code different from its export file (AC 4).
11. As an Administrator, I want a Code Override that moves the register and an Approval in the same Sub-Category at the same moment never to issue one number twice (AC 4).
12. As an Administrator, I want two Administrators deactivating or demoting each other at the same moment to leave at least one active Administrator (AC 4).
13. As a Requester, I want two resends of the same notification at the same moment to send me one email, not two (AC 4).
14. As Procurement, I want a notifier that cannot get a request row within its lock timeout to give up and leave the request on the resend list, so that a background task never hangs (AC 4).
15. As an Account holder, I want parallel wrong logins for my email on PostgreSQL never to get past 10, so that the lockout holds under a parallel attack (AC 5).
16. As Peter, I want login to refuse a client IP after 50 failed logins within 15 minutes, so that password spraying across many emails is stopped (AC 5).
17. As a Requester at a plant where everyone shares one public IP, I want only failed logins to count toward the IP limit, so that normal daily logins never block my plant.
18. As a Requester, I want my own successful login not to reset the IP count, so that an attacker cannot clear the count by logging into their own Account.
19. As a Requester behind a blocked IP, I want a clear Thai message saying to wait 15 minutes, so that I know it is temporary and not my password.
20. As Peter, I want a blocked IP refused before any password hashing, so that a spraying run costs the server almost nothing.
21. As Peter, I want the IP limit to hold across restarts and across processes, so that a restart or deploy does not give an attacker a fresh count.
22. As Peter, I want parallel wrong logins from one IP on PostgreSQL never to get past 50, so that the IP limit holds under a parallel attack.
23. As Peter, I want the client IP read from `X-Forwarded-For` only when the request comes from a trusted proxy, so that an attacker cannot dodge the limit by sending a fake header.
24. As Peter, I want the trusted proxy list to be a setting (env var), so that part B can set it for the chosen platform without a code change.
25. As Peter, I want an IP block written to the log with the IP and no password, so that I can see a spraying attempt in the platform logs.
26. As Peter, I want old IP counter rows to be removed, so that the table does not grow without bound.
27. As Peter, I want the app to run as one worker process, written in the start command and the README, so that the mail limiter stays within Exchange's ~30 sends a minute per mailbox (AC 7).
28. As a developer, I want a test that fails if the start command stops saying one worker, so that a later edit cannot silently break AC 7.
29. As Peter, I want the app to refuse to start outside dev when `FORWARDED_ALLOW_IPS` is not set, so that forgetting it fails the deploy instead of blocking every plant at once after 50 failed logins anywhere.
30. As Peter, I want that start-up error to say what to set (the proxy's IP, or the explicit no-proxy value), so that the fix is clear from the platform log.

### Implementation Decisions

- **CI**: one GitHub Actions workflow, on every push and pull request, Python
  3.12 (as in the Dockerfile), a `postgres:16` service container (as in
  compose). Steps: install `requirements-dev.txt`; `alembic upgrade head` +
  `python -m app.seed` on an empty database; then the full `pytest` with the
  PostgreSQL test URL set. CI sets `APP_ENV=dev`: CI is not a deploy, and
  outside dev Settings demands the four Graph values (they stay out of CI).
- **PostgreSQL test fixture**, beside the SQLite template in the test
  conftest, same idea: once per session, an empty database is migrated with
  Alembic (not `create_all`) and seeded, and kept as a template; each test
  gets its own database copied with `CREATE DATABASE … TEMPLATE …` and
  dropped afterwards. It hands out an engine, so a test opens one session per
  simulated user. Tests using it carry a `postgres` marker and are skipped
  when `TEST_POSTGRES_URL` is unset.
- **Schema drift check**: on the migrated template, Alembic's
  metadata comparison against the models must return no differences. If it
  finds drift today, the fix is a new migration in this story, not a weaker
  check.
- **Concurrency tests** call the existing service functions (Approval via
  `change_status`,
  `change_category`, `override_code`, `export_pending`, `change_access` /
  `deactivate_account`, the notifier's claim, `authenticate`), not HTTP. Pattern:
  session A takes the same lock and holds its transaction open; session B
  runs the service in a thread; the test checks B is still waiting, commits
  A's change, then checks B's outcome (it re-checked status after the lock).
  Same order of locks as in the code (request row, then register row). The
  `lock_timeout` test lowers the notifier's timeout constant to about 1 s.
  No production code changes unless a test finds a real race.
- **Login IP limit** (AC 5, built in the app — no platform check, Peter
  2026-10-21):
  - New table of failed logins per client IP (IP text up to 45 chars for
    IPv6, failure count, window start, blocked-until). Alembic migration,
    verified on a fresh DB and by the drift check.
  - 50 failures within a 15-minute window block the IP for 15 minutes; a
    window older than 15 minutes starts again from zero. Only failures count
    (all kinds: unknown email, wrong password, locked, deactivated); a
    success does not reset the count. Constants beside `MAX_FAILED_LOGINS` /
    `LOCKOUT`.
  - The check runs in the auth service before `authenticate` does any
    hashing; the route passes the client IP and the clock. The IP row is
    locked `FOR UPDATE` (created if missing) so parallel failures are
    counted one after another. Rows whose window and block both ended over a
    day ago are deleted when a failure is recorded.
  - Blocked → HTTP 429, the login page with "มีการเข้าสู่ระบบผิดจากเครื่องนี้
    หลายครั้งเกินไป กรุณารอ 15 นาทีแล้วลองใหม่". This message differs from the
    generic login error on purpose: it is about the IP, so it reveals nothing
    about which emails exist.
  - Logged once at block time with the IP, never a password or email list.
  - Per-email lockout (STORY-001 ticket 06) stays as it is; both apply.
- **Client IP behind a proxy**: uvicorn's proxy-headers middleware is added
  in the app itself, with its trusted proxy list from a new setting
  `FORWARDED_ALLOW_IPS`, and the start command passes
  `--no-proxy-headers` so the header is processed once. Doing it in the app
  rather than only with `--proxy-headers --forwarded-allow-ips` on the
  command line keeps the same rule (Peter's pairing of the two) but puts it
  under test: TestClient does not go through uvicorn's command-line options.
  `.env.example` documents the setting.
- **`FORWARDED_ALLOW_IPS` is required outside dev** (Peter, 2026-10-21),
  the same way as `SECRET_KEY` and the Graph values: a Settings validator
  refuses to start when `APP_ENV` is not `dev` and the value is empty. The
  value is either the trusted proxy list (IPs/CIDRs, comma separated, or
  `*` where only the platform proxy can reach the app) or the explicit
  `none`, meaning no proxy: trust no `X-Forwarded-For` and count the peer
  address. The error message names the setting and both choices. In dev an
  empty value means `127.0.0.1` (uvicorn's default). Migrations and
  `create_admin` load Settings too, so the platform's pre-deploy step needs
  it set as well (as for the Graph values).
- **One worker**: the container start command runs uvicorn with
  `--workers 1` explicitly; README states it and why (AC 7).

### Testing Decisions

- Good tests check what a user or the database sees — codes issued, rows
  saved, HTTP status and page text, emails in the fake outbox — never which
  internal function was called.
- PostgreSQL tests: one module per concern (migrations + drift, codes,
  export races, Administrators, notifier, login), all `postgres`-marked.
  Each waits with a bounded timeout (well under the 60 s pytest timeout) so
  a missing lock fails instead of hanging.
- IP limit on SQLite through `POST /login` with the fake clock: 49 failures
  pass, the 50th blocks, the block lifts after 15 minutes, a success does
  not reset, a blocked IP is refused even with the right password and
  without hashing, another IP is not affected, the window restarts after 15
  minutes, stale rows are pruned, the block is logged without a password.
- Proxy: `X-Forwarded-For` from a trusted peer sets the counted IP; the same
  header from an untrusted peer is ignored and the peer address is counted.
- Start-up check (beside the `SECRET_KEY` / Graph tests): outside dev,
  empty `FORWARDED_ALLOW_IPS` → Settings refuses with a message naming the
  setting and both choices; `none` and a proxy list are accepted; in dev
  empty is accepted. `none` really ignores `X-Forwarded-For`. Existing tests
  that build Settings outside dev get the value set.
- Start command test: reads the Dockerfile and asserts one worker and
  `--no-proxy-headers`.
- Prior art: `tests/test_lockout.py` (fake clock, `/login`, row-lock
  check), `tests/conftest.py` (template + copy, `central_ids()` for every
  new request), `tests/test_template_db.py` (fixture guards),
  `tests/test_hardening.py` (Settings outside dev).

### Out of Scope

- Part B: choosing and deploying to Render/Railway, managed Postgres,
  backups and restore, real email (AC 1, 3, 6, 8); setting
  `FORWARDED_ALLOW_IPS` for the real platform.
- Branch protection (GitHub plan not yet checked (Peter); a private repo on GitHub Free cannot have it).
- The query-cost and mail-limiter notes below (not deploy conditions).
- Rate limiting anything other than `POST /login`.

### Further Notes

- **Part B decision (Peter, 2026-10-22): a platform that does not publish
  its proxy IPs.** `*` is forbidden (uvicorn trusts the *leftmost*
  `X-Forwarded-For` entry with `*`, which the client writes, so the IP limit
  could be dodged), and `none` would make every request look like the
  proxy's single IP. If the chosen platform does not publish its proxy
  addresses, no correct `FORWARDED_ALLOW_IPS` exists. Option to decide then:
  a "trust one hop" mode that takes the rightmost `X-Forwarded-For` entry,
  the one the platform's own proxy appends. Not built now.

- A forgotten `FORWARDED_ALLOW_IPS` is now a deploy error, not a silent
  plant-wide block. A *wrong* value still is not caught (e.g. `none` behind a
  proxy makes every request look like the proxy's IP): part B must check, on
  the deployed app, that two machines are counted as two IPs.
- **Part B: where `python -m app.unblock_ip`'s log line ends up** (review
  of `2ad9b3d..7a0ec12`, 2026-10-26). The command logs who lifted a block
  to its own stderr. On a platform, a command run in a shell session
  (`docker exec`, the platform's web shell) prints there, not into the
  service's log stream where `login_ip_blocked` lands, so the record of who
  unblocked closes with the session. Part B checks it on the chosen
  platform; if it is not kept, write the line where the app's log goes or
  keep an audit row in the DB.
- The drift check may find existing drift; budget a migration for it.
- Local runs of the PostgreSQL tests: start the compose `db` service and set
  `TEST_POSTGRES_URL`; README gets the one-line command.

### Part A close-out and merge (Peter, 2026-10-26)

1. `/code-review` of the whole branch: done, no (ก) (section below).
2. Migrate the real `dev.db`, backup kept: done (record in
   `STORY-006/part-a-browser-checklist.md`).
3. Browser checklist written to that file.
3a. Fix the (ก) found writing it: `python -m app.unblock_ip` drops its
    `login_ip_unblocked` log line. Subprocess test that FAILS first, then
    one logging setup function called by `main.py` and `unblock_ip.py`
    (same format). Then push → Peter checks CI from the real numbers →
    `/code-review` of that diff only → no (ก), go on.
3b. Peter runs the 8 browser checks.
4. Docs before merge: HANDOFF §2 status "Part A done, Part B waits for IT"
   + the `unblock_ip` command + `FORWARDED_ALLOW_IPS` + open work
   (STORY-015/016, CI to Ubuntu 26, Pydantic config); this story's status
   "part A done · part B todo"; the 006 row in `docs/stories/README.md`.
5. Merge: `git merge --no-ff story/006-deploy-part-a` on master → pytest
   locally → push master → Peter checks master's CI from the real numbers →
   the branch stays until Peter says to delete it. Keep
   `dev.db.bak-2026-10-26` until Peter's browser checks pass.

## Part A whole-branch review (2026-10-26)

Ran `/code-review` on `d192b24..0fe08fe` (merge-base with master → part A
done). 10 findings, **no (ก)**. Seven were already recorded: slots without
identity (STORY-015 7, HANDOFF §2), 9 + 1 slot refuses a right password
(015 5), 429 with no block set (015 6), second hash change counts a
failure (015 3), the prune's table scan (ticket 07 review 7), and the
last-Administrator branch + changed test (ticket 04, approved by Peter
2026-10-23). Three new (ข) → STORY-015 21–23.

## Notes

- Query cost found in the STORY-002 review (2026-10-14), not a deploy
  condition; fix if pages feel slow once the plants use it:
  - `app/routes/deps.py` runs the whole `pending_notifications` query on
    every full page load for Procurement/Administrators only to show the
    menu count. A COUNT query (or loading only ids) would do. It also runs
    on POSTs and file downloads that never render the menu, and the query
    sits in the auth dependency (routes → services rule): compute it only
    where `base.html` renders.
  - `switched_off_domain()` queries `active_mail_domains()` every call, and
    `recipients`, `group_key`, `_greeting`, `recipient_note` and the Export
    page all call it: about 4 identical queries per request (≈ 200 for 50
    rows). Load the domain set once per notifier run / page and pass it in.
- Single "ส่งอีเมลอีกครั้ง" button (`routes/queue.py`) sends inside the HTTP
  request. A normal click returns in a second or two: the spacing wait is
  ≤ 2.4 s at the default rate (more if other sends are queued for their
  turn). After a 429 it waits the Retry-After (≤ 60 s per 429) + a token
  (≤ 20 s) + one send (≈ 15 s), and every further 429 meanwhile (e.g. a
  "ส่งซ้ำทั้งหมด" running) pushes the wait later again — no fixed bound.
  Check the platform's proxy timeout at deploy; make that button fail fast
  while a back-off is running if clicks are seen to time out.
- A 429 fails that send at once; its Retry-After (seconds or HTTP-date,
  capped at 60 s) pushes the next `prepare()` later, outside any lock. A
  Retry-After longer than 60 s can still draw another 429 after the cap.
- Each `prepare()` books its own start (token first, then the booking), so
  concurrent bookings are spaced too (tested with 8 threads). The POSTs are
  not: see decisions.md 2026-10-15. `prepare()` runs before the notifier knows
  whether anything will be sent: a superseded change or a group another
  notifier already claimed still waits its turn (2.4 s, longer after a
  429) and books a start it does not use. Harmless at our volume.
- Further notes from the review of 2026-10-14 round 3 (not correctness, not
  deploy conditions):
  - Migrations and `create_admin` load Settings too, so outside dev they
    need the four Graph values as well. On Render/Railway the pre-deploy
    step shares the app's env, so set them before the first deploy.
  - `config.Settings.graph_missing()` and `mail._graph_values()` both list
    the four Graph settings; make `get_mail_sender` use `graph_missing()` so
    the start-up check and the sender choice cannot drift.
  - The dev "Graph settings incomplete" warning is logged while
    `settings = Settings()` is built at import, before uvicorn configures
    logging; it may not show. Dev only.
  - When Entra login is unreachable, each (To, CC) group's `prepare()` waits
    the token timeout again (~20 s each): a 20-group "send all" takes ~7 min
    of a background thread to record 20 identical failures. Stop after the
    first prepare failure per call if this is ever seen.
  - A split "created" group (recipients changed under the lock) and a token
    dropped by another thread's 401 are the two rare paths that still do
    more than one short call under the lock (see decisions.md). The split
    group's extra parts go out back to back, unspaced (send books nothing).
  - "Send all" of 25+ groups takes about a minute at the default rate
    (spaced 2.4 s apart) — expected, not a hang.
- Limiter notes from the review of 2026-10-15 (accepted for v1, Peter;
  see decisions.md 2026-10-15):
  - A notifier that has already booked still sends after another thread's
    429 and may draw a second 429 (also lands on the resend list).
  - No first-come order: the single resend button can lose its turn to a
    running "send all" more than once and wait longer, even without a 429.
    This adds to the proxy-timeout note above.
  - The 8-thread test checks the booked starts on a fake clock, whose sleep
    does not hand control to other threads; it cannot see POSTs bunching.
  - A thread that wakes late books `now + interval`, so the rate drifts a
    little slower than configured, never faster.
  - Retry-After is read with `float()`: "-5" means no back-off, "1e9" is
    capped at 60 s. Both are harmless; the HTTP-date form stays (RFC 9110).
  - `RateLimiter.wait()` returns the booked start only for the tests.
  - **Fix if 429s are frequent after go-live:** one mail worker thread with
    a queue (prepare → claim → send, one job at a time, in order). That
    makes the spacing real and the order fair. It replaces the
    BackgroundTasks setup, so it is its own story.
