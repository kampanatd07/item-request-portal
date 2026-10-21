# 02: Postgres race: Code Override and Approval never issue one number twice

Status: todo
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
