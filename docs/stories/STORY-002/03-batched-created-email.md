# 03: One "created" email per recipient per click

Status: todo
Triage: ready-for-agent
Parent: STORY-002
Blocked by: 01, 05

**What to build:** "Mark created" on an Export Batch can cover dozens of
requests. Instead of one email per request, each click sends **one email per
To-recipient**, listing all of that recipient's codes (code, name, UoM, Plant)
in one table. CC is the union of the submitting Accounts of the listed
requests (minus the To address). Grouping uses the recipient rules of
ticket 05. The same grouping applies to "ส่งซ้ำทั้งหมด" (ticket 06).

- Dedupe stays atomic: all request rows of the click are locked in id order,
  only those still `created` are grouped and sent; each group's requests move
  to `notified` only when that group's email was sent; a failed group leaves
  its requests `created` with `notify_failed`.
- needs_info / rejected are unaffected (one email per request, ticket 04).

- [ ] Five requests for two requesters → exactly two emails, each listing
      that requester's codes; all five `notified` (AC5)
- [ ] One group failing leaves only its requests `created` + `notify_failed`
- [ ] Originator groups: To the originator, CC the union of submitters
- [ ] Re-running the click sends nothing more
