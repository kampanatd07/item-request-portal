# 02: Postgres race: Code Override and Approval never issue one number twice

Status: in-progress (waiting for CI)
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01

**What to build:** proof on real PostgreSQL row locks (AC 4, STORY-010
ticket 03) that a Code Override which moves the Running Register and an
Approval in the same Sub-Category, at the same moment, never end with one
number on two requests. Lock order is request row, then register row; the
loser waits and works from what the winner committed.

- [ ] Override first, Approval waiting: the Approval gets a number after the
      override's moved register, not the override's code
- [ ] Approval first, override waiting: the override's validation sees the
      register as the Approval left it, and the outcome follows the existing
      override rules (no duplicate, no reused Retired Code)
- [ ] Both orders: all issued codes distinct; the register equals the
      highest issued running number
- [ ] Waiting is checked (B still running while A holds its transaction);
      waits bounded
- [ ] No production code change unless a test shows a real race; if one
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
