# 03: Postgres race: Approval or re-categorise against an export of the same request

Status: todo
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 01

**What to build:** proof on real PostgreSQL row locks (AC 4, STORY-001
ticket 03) that an export of a Plant's approved requests and a change to one
of those requests (a re-categorise, which can re-issue the code, or an
Approval landing while the export runs) never interleave: the loser waits,
re-checks status after it gets the lock, and no exported request ends up
with a code different from the one in its export file.

- [ ] Export holds the rows, re-categorise waits: after the export commits,
      the re-categorise sees the request is exported and is refused as the
      existing rules say; the request's code equals the code in the file
- [ ] Re-categorise holds the row, export waits: the export includes the
      request with its new code (or leaves it out if its status changed),
      and the file matches the database
- [ ] An Approval committing while an export waits on the rows: the result
      follows the re-check after the lock (in the batch with its code, or
      not in it), never in the file with a different code
- [ ] Waiting is checked; waits bounded
- [ ] No production code change unless a test shows a real race; if one
      does, stop and tell Peter before fixing. No migration
