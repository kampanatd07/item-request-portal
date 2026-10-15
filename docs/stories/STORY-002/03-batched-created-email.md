# 03: One "created" email per recipient per click

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-002
Blocked by: 01, 05

**What to build:** "Mark created" on an Export Batch can cover dozens of
requests. Instead of one email per request, each click sends **one email per
(To, CC set)** (Peter, 2026-10-02 — changed from "per To-recipient"), listing
all of that group's codes (code, name, UoM, Plant) in one table, so a
submitter is never copied on items they did not submit. Grouping uses the recipient rules of
ticket 05. The same grouping applies to "ส่งซ้ำทั้งหมด" (ticket 06).

- Dedupe stays atomic: each group's request rows are locked in id order (one
  transaction per group), only those still `created` are sent; each group's requests move
  to `notified` only when that group's email was sent; a failed group leaves
  its requests `created` with `notify_failed`.
- needs_info / rejected are unaffected (one email per request, ticket 04).

- [x] Five requests for two requesters → exactly two emails, each listing
      that requester's codes; all five `notified` (AC5)
- [x] One group failing leaves only its requests `created` + `notify_failed`
- [x] Originator groups: To the originator, CC only that group's submitter
      (each submitter gets their own email)
- [x] Same person, own requests + one submitted for them by Procurement
      in one click → 2 emails with the right CC (Peter)
- [x] Re-running the click sends nothing more

Implementation notes (2026-10-02, decisions by Peter):
- Grouped by **(To, CC set)**, not To alone (Peter): a submitter is never
  copied on items they did not submit — the same person's own requests and a
  request Procurement submitted for them are two emails. Groups are handled
  in sorted (To, CC) order, the same in every process.
- One transaction per group: read without locks, then claim the group's rows
  (id order), re-check recipients under the locks, send, record, commit.
  A failed group leaves only its requests `created` with `notify_failed`.
- Subject: "[Item Portal] สร้างใน AX แล้ว N รายการ — ใช้สั่งซื้อได้ (c1, c2, c3, …)";
  one request keeps the single-code subject. Greeting is the person's name, or
  "ผู้ขอ" when names in the group differ. No cap on items per email.
- `notified` events say "(ฉบับรวม N รายการ)"; the same function serves
  ticket 06's "ส่งซ้ำทั้งหมด".
- Real race test: two threads with overlapping request sets on a file SQLite
  DB send every code exactly once.
- Code review fixes: a request whose recipients cannot be worked out is
  recorded as `notify_failed` and the others go on (grouping had made one bad
  request abort the click); when the final commit fails, parts that were sent
  say "sent but not recorded" and parts that failed keep their real reason;
  a busy claim (SQLite only) is retried once, then the group stays `created`
  for the "not yet notified" list (ticket 06).
- Peter (2026-10-02): on PostgreSQL the claiming transaction runs
  `SET LOCAL lock_timeout = '30s'`, so a notifier never waits forever for a
  row (default PostgreSQL waits have no timeout); past it the group stays
  `created` for the resend list, same as SQLite. Real-Postgres test: STORY-006 AC4.

