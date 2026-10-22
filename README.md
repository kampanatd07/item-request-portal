# Item Request Portal

Internal web app for requesting and creating purchase items across 4 factories (CBD, APM, APG, ACM). Requesters submit via web form with live duplicate checking; procurement approves, auto-generates item codes per system rules, exports AX/D365 import files, and the system notifies requesters.

## Setup (local)
1. Install Docker Desktop
2. `cp .env.example .env` and fill values
3. `docker compose up`
4. Open http://localhost:8000
5. `alembic upgrade head` runs automatically on start

## Running tests
`pytest`

PostgreSQL tests (row locks, migrations; marked `postgres`) are skipped unless
`TEST_POSTGRES_URL` is set. CI always runs them. Locally, with Docker:

```powershell
docker run -d --name irp-test-pg -p 5432:5432 -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=itemportal postgres:16
$env:TEST_POSTGRES_URL = "postgresql+psycopg://app:app@localhost:5432/itemportal"; pytest -m postgres
```

(The compose `db` service publishes no port, hence a separate container. The
user must be allowed to create databases: each test gets its own copy.)

## Deploying
Push to `main` → GitHub Actions runs tests → deploy to Render/Railway (see docs/architecture.md)

- **One worker process.** The container runs `uvicorn --workers 1`. The mail
  limiter spaces sends per process (`MAIL_RATE_PER_MINUTE`, default 25) and
  Exchange allows about 30 a minute per mailbox, so several workers together
  would exceed it. Keep `MAIL_RATE_PER_MINUTE` × workers (all instances) ≤ 25.
- **`FORWARDED_ALLOW_IPS`** (required outside `APP_ENV=dev`; the app refuses to
  start without it, and so do migrations and `create_admin`): the IPs or CIDR
  ranges of the proxy in front of the app, comma separated, e.g.
  `10.0.0.0/8`; or `none` when clients connect directly. The login limit per
  IP counts the address this gives. `*` is refused: uvicorn would then believe
  the leftmost `X-Forwarded-For` entry, which the client writes itself.
  The container passes `--no-proxy-headers`; the app reads the header itself.
  After deploy, check that two machines are counted as two IPs.

## When things break
- Logs: Render/Railway dashboard
- Backups: platform daily DB snapshot; weekly pg_dump
- Owner: Peter (kampanat.d07@gmail.com)
