# 01: CI on every push, migrations on a fresh Postgres, schema drift check, AC 2

Status: done (2026-10-22)
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

- [x] A GitHub Actions workflow runs on every push and pull request: Python
      3.12, `postgres:16` service, `requirements-dev.txt`, migrate + seed on
      an empty DB, then `pytest` with `TEST_POSTGRES_URL` set; `APP_ENV=dev`
      (CI is not a deploy; no Graph values in CI)
- [x] The workflow is green on this branch, and the PostgreSQL tests
      actually ran there (not skipped), checked in the run log
- [x] Local `pytest` without `TEST_POSTGRES_URL`: same pass count as before,
      the new PostgreSQL tests skipped, no failures
- [x] Fixture: each test gets its own copy; a write in one test is not seen
      by the next (guard test, like `test_template_db.py`)
- [x] Drift check: Alembic's metadata comparison between the migrated DB and
      the models returns nothing. If it finds drift today: **stop and show
      Peter the diff**; the fix is a new migration in this ticket (the only
      ticket besides 07 allowed to add one), verified on a fresh DB
- [x] AC 2: two Approvals in one Sub-Category, overlapping on real row
      locks, get two different consecutive codes; the second waited for the
      first (checked, not assumed); bounded waits, no 60 s hang on failure
- [x] README: how to run the PostgreSQL tests locally (a `postgres:16`
      container + `TEST_POSTGRES_URL`; the compose `db` publishes no port),
      one command

## Code review (2026-10-21)

Ran `/code-review` on `0a153b3..516b14d` (plus the uncommitted action bump).
10 findings, sorted as before: **(ก)** wrong data, someone acting who should
not, data lost, or an acceptance criterion not met; **(ข)** a note.
**No (ก).** CI on `516b14d`: green, 814 passed, 0 skipped, no schema drift
(Peter, 2026-10-21).

### Not a finding
1. *"checkout@v7 / setup-python@v7 may not exist."* Checked before the
   change: both are published (checkout v7.0.0 2026-06-18, v7.0.1
   2026-07-20; setup-python v7.0.0 2026-07-20) and both `action.yml` say
   `using: node24`. v7 breaking changes do not touch us (setup-python drops
   `pip-install`, checkout blocks fork PRs on `pull_request_target`). Kept.

### (ข) Notes — race helper diagnostics (tests only)
2. `Race.run` waits for A to reach its commit without looking at A's
   future: if A raises first, the test waits 15 s and says "never reached
   its commit", hiding A's error. **Recommend: fix** (check A's future while
   waiting, re-raise its error).
3. On a failure path the sessions are closed from the main thread while the
   worker threads may still use them, and the pool is not waited for; the
   teardown then drops the database under live backends. Noisy secondary
   tracebacks, real cause hidden. **Recommend: fix** (release A, wait for
   both futures with the bound, then close).
4. When B finishes without waiting on a lock, B's own result or error is
   dropped from the message, so a setup error looks like a missing lock.
   **Recommend: fix** (put B's outcome in the message).
5. A killed run (pytest-timeout's thread method ends with `os._exit`, or
   Ctrl-C) leaves `irp_template_<pid>` / `irp_test_<pid>_…` databases on a
   local server for good; the next run has a new pid and never drops them.
   CI's server is thrown away each run. **Recommend: fix** cheaply: at
   session start drop leftover `irp_%` databases.

### (ข) Notes — conventions and tidiness
6. CI runs on `push` (all branches) and `pull_request`, so a push to a
   branch with an open PR runs twice. We merge locally without PRs today.
   **Recommend: leave** until PRs are used.
7. Type hints missing on `_run_on(connection)` in `env.py` and on the new
   fixtures/helpers in `conftest.py` and `test_pg_codes.py` (CLAUDE.md:
   "Type hints on all functions"). **Recommend: fix.**
8. The copy name carries `id(made)`, which adds nothing over pid + counter
   and is not unique across tests. **Recommend: fix** (module-level counter).
9. A third way to run `alembic upgrade head` in tests, next to the
   `alembic.ini` ones in `test_auth.py` and `test_notify_not_applicable.py`.
   **Recommend: leave** — those two test the command-line path on purpose
   (URL from settings); a shared helper can come if env.py changes again.

**Peter's decisions (2026-10-21):** fix 2, 3, 4, 5, 7, 8; leave 6 and 9.
Fixed in one commit:
- 2: while waiting for A, the helper checks A's future; A's own exception
  is raised. Test: an error in A shows A's error (runs on SQLite too).
- 3: on every path A is released and both threads are waited for (bounded)
  before their sessions are closed.
- 4: "finished without waiting on a lock" now includes what B returned or
  raised. Test (PostgreSQL).
- 5: at session start, databases left by earlier runs are dropped: only names
  starting `irp_template_` / `irp_test_`, never this run's own (its pid).
  Test (PostgreSQL): a leftover is dropped, another database is kept, this
  run's copy survives.
- 7: type hints on `_run_on`, the PostgreSQL fixtures/helpers and
  `test_pg_codes.py` helpers. 8: copy names use a module-level counter.

## Closed (2026-10-22)

CI on `0bb327c` (Peter): green; `actions/checkout@v7` and
`actions/setup-python@v7`, no Node 20 warning; migrate + seed on an empty
PostgreSQL 16 ends with `Seed complete.`; **817 passed, 0 skipped**; no schema
drift, so no migration in this ticket. Local: 811 passed, 6 skipped (the
PostgreSQL tests).
