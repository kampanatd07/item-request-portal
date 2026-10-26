# 02: Postgres race: Code Override and Approval never issue one number twice

Status: done (2026-10-22)
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01

**What to build:** proof on real PostgreSQL row locks (AC 4, STORY-010
ticket 03) that a Code Override which moves the Running Register and an
Approval in the same Sub-Category, at the same moment, never end with one
number on two requests. Lock order is request row, then register row; the
loser waits and works from what the winner committed.

- [x] Override first, Approval waiting: the Approval gets a number after the
      override's moved register, not the override's code
- [x] Approval first, override waiting: the override's validation sees the
      register as the Approval left it, and the outcome follows the existing
      override rules (no duplicate, no reused Retired Code)
- [x] Both orders: all issued codes distinct; the register equals the
      highest issued running number
- [x] Waiting is checked (B still running while A holds its transaction);
      waits bounded
- [x] No production code change unless a test shows a real race; if one
      does, stop and tell Peter before fixing. No migration

## Notes (2026-10-22)

`tests/test_pg_override_race.py`, 3 tests (PostgreSQL only). Expected values
come from the STORY-010 rules as tested on SQLite (`test_override_checks.py`,
`test_retired_codes.py`): the replaced code retired `overridden`, numbers
between the register and X not in the master retired `skipped`, no
confirmation for ≤ 10. Setup: R1 approved holds code(last), R2 submitted,
X = code(last + 2) in the group master (not last + 1: an Approval refuses a
next number the master holds, so there would be no race).
1. Override first, Approval waits: R2 = last + 3, register last + 3, retired
   {last: overridden, last + 1: skipped}.
2. Approval first, override waits: R2 = last + 1, register last + 2, retired
   only {last: overridden}; **last + 1 (R2's number) not retired**.
3. Preview shown before the Approval, override sent with that preview
   (`expected`) waits: refused "ข้อมูลเปลี่ยนไปหลังตรวจรหัส"; R1 keeps its
   code, nothing retired, register last + 1. (Beyond the ACs; Peter kept it.)
Every test also checks no number is on two requests or on a request and
retired. No production code change, no migration.

## Code review (2026-10-22)

Ran `/code-review` on `6b70139..b5e8d38`. 8 findings, sorted as before
(**(ก)** wrong data, someone acting who should not, data lost, or an
acceptance criterion not met; **(ข)** a note). **No (ก).** The reviewer traced
all three races through `override_code`, `change_status` and the register
allocation: B really waits on the register row in each, every expected value
matches the STORY-010 SQLite tests, and the register equals the highest
issued number in each.

### (ข) Notes — not changed (Peter: fix only (ก))
1. HANDOFF §2 test count was stale (814 on CI). Updated when closing this
   ticket: 811 passed + 9 skipped locally, 820 on CI.
2. Type hints missing on `_setup(engine)`, `_state(engine)` and the test
   functions' `pg_engine` (CLAUDE.md). Recommend: fix with the next race file.
3. `_code(n)` hardcodes 900-01 and copies `codegen.central_code`; the pair
   also appears in `_submit`, `_setup`, `_state`. Recommend: one shared
   group/sub value and `central_code` in the next race files.
4. The register query is written twice (and again in
   `test_override_checks.py` as `_last`). Recommend: a shared helper.
5. `_no_number_twice` and the `last + 1 not in retired` line can never fail on
   their own: the exact `codes` / `retired` checks just before already imply
   them. The note above ("every test also checks…") overstates the coverage.
6. The override-first race does not check the `register_advanced` event
   (`last -> X (ทิ้ง n …)`) that the SQLite test checks.
7. The stale-preview race checks the general message only, not that it names
   "เลขล่าสุดของ register", so a refusal for another reason would also pass.
8. `_state` compares all requests and all Retired Codes in the database with
   exact dicts; a seed that one day adds a sample request or retired code
   breaks the tests though the race is fine. Recommend: filter to r1/r2 and
   the 900-01 codes near `last`.

## Closed (2026-10-22)

CI on `b5e8d38` (Peter): green, **820 passed, 0 skipped**;
`test_pg_override_race.py` 3 passed. No race found, no production code
change, no migration.
