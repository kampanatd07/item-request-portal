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

## When things break
- Logs: Render/Railway dashboard
- Backups: platform daily DB snapshot; weekly pg_dump
- Owner: Peter (kampanat.d07@gmail.com)
