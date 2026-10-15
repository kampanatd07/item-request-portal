# STORY-006: Deploy for the 4 plants

Status: todo · Depends on: STORY-001, STORY-002, STORY-009 (requesters must be able to answer Needs Info before the plants get access), STORY-010 (code override must be validated before deploy)

## Why
The app only runs on Peter's laptop. Plants need a URL.

## Scope
- GitHub repo (private) with CI: `pytest` on every push; red blocks merge
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
_(filled by /to-spec + /to-tickets)_

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
  ≤ 2.4 s at the default rate. The worst case is right after a 429: its
  Retry-After wait in `prepare()` (≤ 60 s) + a token (≤ 20 s) + one send
  (≈ 15 s). Check the platform's proxy timeout at deploy; if it is under
  ~100 s, make that button fail fast while a back-off is running.
- A 429 fails that send at once; its Retry-After (seconds or HTTP-date,
  capped at 60 s) pushes the next `prepare()` later, outside any lock. A
  Retry-After longer than 60 s can still draw another 429 after the cap.
- Two notifier threads can pass the spacing wait together and send close
  together (the limiter never refuses). Exchange's ~30/min leaves room at
  1–2 users; a real 429 goes to the resend list.
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
    more than one short call under the lock (see decisions.md).
  - "Send all" of 25+ groups takes about a minute at the default rate
    (spaced 2.4 s apart) — expected, not a hang.
