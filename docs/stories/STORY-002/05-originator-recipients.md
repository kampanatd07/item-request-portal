# 05: Originator email and who gets the email

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-002
Blocked by: 01

**What to build:** When Procurement submits for someone who asked by phone,
that person can get the emails too. New columns `originator_name` and
`originator_email` on `item_requests` in **one** Alembic migration that
backfills `originator_name` from existing `ขอแทน:` lines in `submitted`
events. `originator_of()` reads the column (events stay as history). The
request form (Procurement/Administrator only, next to "ขอแทน") gets an
optional originator email: needs a name, same format rule as Account emails,
domain must be an active row of `mail_domains` (same migration; seeded
apm.co.th, acmf.co.th, apg.co.th, carabao.co.th; Settings page add / switch
off, Administrator only; not tied to a Plant). With no active domain,
originator emails are refused in Thai. Requesters' posted originator fields are still dropped.

Recipient rule (one function, used by tickets 01, 03, 04): with an
originator email → To the originator, CC the submitting Account; otherwise
To the submitting Account.

- [x] Migration adds both columns, backfills names from events, runs cleanly
      on a fresh DB with seed and `alembic check` (AC9)
- [x] Originator email outside the allowed domains, malformed, or without a
      name is refused on the form in Thai (AC7)
- [x] Recipient rule: originator → To originator, CC submitter; none → To
      submitter
- [x] A Requester cannot set originator fields
- [x] The detail page shows the originator name and email

Implementation notes (2026-10-01, decisions by Peter):
- Migration `e52ce808c5d5` adds `originator_name` / `originator_email` and
  backfills names from `ขอแทน:` lines: a line-anchored regex (no `\b` next to
  Thai), NFC + SARA AM recomposition (never NFKC), spaces collapsed, an
  appended `<email>` excluded. Tested with "คำรณ ใจดี" composed and
  decomposed (ํ + า), a first + last name with extra spaces, a full-width
  name NFKC would have changed, and a non-anchored "ขอแทน:" that must not match.
- Found while verifying: printing Thai from a migration crashes `alembic` on a
  Windows console (cp1252); migration output is ASCII only.
- Domains match exactly, case-insensitive; subdomains need their own row.
  Peter (2026-10-02) moved the list from env to the `mail_domains` table so a
  new company domain needs no deploy; seed is insert-only, so a domain an
  Administrator switched off stays off.
- The `submitted` event keeps `ขอแทน: <name> <email>` as history.
- `recipients(req)` in notify.py is the one rule (To originator, CC submitter;
  else To submitter); the created email greets the originator by name.
- dev.db upgraded (backup in scratchpad): no requests had a `ขอแทน:` line.
- Code review fixes: the originator name is NFC + SARA AM like all Thai text
  and checked against the column lengths (100 / 254 → Thai error, not a 500
  on PostgreSQL); the backfill keeps the whole rest of an old "ขอแทน:" line
  (those never carried an email), including "<…>" and a bare "<", and
  tolerates CRLF.
- Code review (domains): the backfill drops only a trailing " <…@…>" (written
  by this feature) so a downgrade + upgrade keeps the name clean; recipients
  re-check the originator's domain at send time — switched off since → the
  submitter gets the email instead (internal data must not leave the
  company); the same address is never in both To and CC.
- Peter (2026-10-02) agreed with the fallback and asked that the `notified`
  event say so: "โดเมน <x> ถูกปิด — ส่งให้ผู้ส่งคำขอแทน".

