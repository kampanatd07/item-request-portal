# STORY-006: Deploy for the 4 plants

Status: todo · Depends on: STORY-001, STORY-002

## Why
The app only runs on Peter's laptop. Plants need a URL.

## Scope
- GitHub repo (private) with CI: `pytest` on every push; red blocks merge
- CI also runs `alembic upgrade head` against a fresh Postgres service container
  (catches trap HANDOFF §6.8, which SQLite tests miss)
- Deploy the existing `Dockerfile` to Render or Railway with managed Postgres
- `DATABASE_URL`, `SECRET_KEY`, SMTP settings as platform secrets
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
4. **Before go-live:** confirm with Peter that the company data policy allows
   external hosting of item data (flagged in decisions.md 2026-07-24)

## Files likely touched
`.github/workflows/ci.yml`, `Dockerfile`, `README.md`, `docker-compose.yml`, tests

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
