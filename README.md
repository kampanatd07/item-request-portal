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
  start without it, and so do migrations and `create_admin`): the addresses of
  the proxies in front of the app, comma separated (IPs or CIDR ranges); or
  `none` when clients connect directly. The login limit per IP counts the
  address this gives, so get it right:
  - List **every hop that appends to `X-Forwarded-For`** (e.g. a CDN in front
    of the platform's load balancer, *and* the load balancer). A hop left out
    becomes "the client": all plants would share its few IPs, and 50 failed
    logins anywhere would block everyone.
  - List **only proxy addresses**. A range that real clients can also come
    from (a broad private range such as all of `10.0.0.0/8` when users reach
    the app from such addresses) lets those clients write their own IP into
    the header and dodge the limit: when every entry is trusted, uvicorn
    falls back to the leftmost, client-written one.
  - `*` is refused for the same reason.
  The container passes `--no-proxy-headers`; the app reads the header itself
  (a platform "start command" override must keep that flag). After deploy,
  check that two machines are counted as two IPs.

## When things break
- Logs: Render/Railway dashboard
- Backups: platform daily DB snapshot; weekly pg_dump
- Owner: Peter (kampanat.d07@gmail.com)
