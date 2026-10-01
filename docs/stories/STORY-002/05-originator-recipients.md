# 05: Originator email and who gets the email

Status: todo
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
domain must be in `MAIL_ALLOWED_DOMAINS` (comma-separated env; when unset,
originator emails are refused with a Thai message saying the setting is
missing). Requesters' posted originator fields are still dropped.

Recipient rule (one function, used by tickets 01, 03, 04): with an
originator email → To the originator, CC the submitting Account; otherwise
To the submitting Account.

- [ ] Migration adds both columns, backfills names from events, runs cleanly
      on a fresh DB with seed and `alembic check` (AC9)
- [ ] Originator email outside the allowed domains, malformed, or without a
      name is refused on the form in Thai (AC7)
- [ ] Recipient rule: originator → To originator, CC submitter; none → To
      submitter
- [ ] A Requester cannot set originator fields
- [ ] The detail page shows the originator name and email
