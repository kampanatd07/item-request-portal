# 01: CI on every push, migrations on a fresh Postgres, schema drift check, AC 2

Status: todo
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: None (can start immediately)

**What to build:** every push to GitHub runs the whole test suite next to an
empty PostgreSQL 16: first `alembic upgrade head` + seed on that empty
database (the container's start command, minus serving), then `pytest` with
the PostgreSQL tests switched on. Peter sees red or green on each branch
before he approves a merge (no branch protection on GitHub Free, HANDOFF §8).
PostgreSQL tests get their own fixture: one database migrated with Alembic
(not `create_all`) and seeded once per run, copied per test with
`CREATE DATABASE … TEMPLATE …`, dropped after; marked `postgres`, skipped when
`TEST_POSTGRES_URL` is unset, so local `pytest` on Windows stays as today. The
first tests on it: the migrated schema equals the models, and two Approvals
in the same Sub-Category at the same moment get distinct consecutive Central
Codes (AC 2), the first use of the "A holds the lock, B waits" pattern.

- [ ] A GitHub Actions workflow runs on every push and pull request: Python
      3.12, `postgres:16` service, `requirements-dev.txt`, migrate + seed on
      an empty DB, then `pytest` with `TEST_POSTGRES_URL` set; `APP_ENV=dev`
      (CI is not a deploy; no Graph values in CI)
- [ ] The workflow is green on this branch, and the PostgreSQL tests
      actually ran there (not skipped), checked in the run log
- [ ] Local `pytest` without `TEST_POSTGRES_URL`: same pass count as before,
      the new PostgreSQL tests skipped, no failures
- [ ] Fixture: each test gets its own copy; a write in one test is not seen
      by the next (guard test, like `test_template_db.py`)
- [ ] Drift check: Alembic's metadata comparison between the migrated DB and
      the models returns nothing. If it finds drift today: **stop and show
      Peter the diff**; the fix is a new migration in this ticket (the only
      ticket besides 07 allowed to add one), verified on a fresh DB
- [ ] AC 2: two Approvals in one Sub-Category, overlapping on real row
      locks, get two different consecutive codes; the second waited for the
      first (checked, not assumed); bounded waits, no 60 s hang on failure
- [ ] README: how to run the PostgreSQL tests locally (compose `db` +
      `TEST_POSTGRES_URL`), one command
