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

## Deploying
Push to `main` → GitHub Actions runs tests → deploy to Render/Railway (see docs/architecture.md)

## When things break
- Logs: Render/Railway dashboard
- Backups: platform daily DB snapshot; weekly pg_dump
- Owner: Peter (kampanat.d07@gmail.com)
