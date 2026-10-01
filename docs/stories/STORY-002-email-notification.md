# STORY-002: Email the requester when their item is created

Status: planned · Depends on: STORY-001 (done)
Triage: ready-for-agent

## Why
Today Peter tells each requester by hand that their item exists, and that a
request was sent back or rejected. The last manual step of the original flow
should disappear. Deploy (STORY-006) waits for this story.

## Scope
- **Transport: Microsoft Graph `sendMail`** with client credentials (tenant
  id, client id, client secret and the sender mailbox from env), behind a
  `MailSender` interface so another sender (e.g. SMTP) can be added later.
  No SMTP in this story: Exchange Online turns SMTP AUTH Basic Auth off by
  default at the end of December 2026 (Peter, 2026-10-01). Without Graph
  settings the app logs each email instead of sending (dev mode).
- **When:**
  - `created` — "[Item Portal] รหัส X สร้างใน AX แล้ว — ใช้สั่งซื้อได้": the
    item exists in that Plant's AX and the code can be used for PR/PO. A
    "mark created" click on several requests sends **one email per recipient
    per click**, listing every code for that recipient
  - `needs_info` — the reason (review_note); one email per request
  - `rejected` — the reason; when the request already had a code (rejected
    after approval) it says "รหัส X ยกเลิกแล้ว ห้ามใช้"; one email per request
  - not on `approved` (the code cannot be ordered until it is in AX)
- **Recipients:** new columns `originator_name` / `originator_email` on
  `item_requests` (one migration; names backfilled from `ขอแทน:` events;
  `originator_of()` reads the column). Procurement/Administrator may enter
  the originator's email on the form (optional; needs a name; same format
  rule as Account emails; domain must be in `MAIL_ALLOWED_DOMAINS`). With an
  originator email: To the originator, CC the submitting Account; otherwise
  To the submitting Account.
- **Content:** Thai; simple HTML with the code large, plus a plain-text part;
  the code in the subject; link `PUBLIC_BASE_URL/my-requests#request-<id>`
  ("สำหรับผู้มีบัญชีในระบบ"; no link when `PUBLIC_BASE_URL` is unset), and
  "My requests" scrolls to and highlights that row; `Reply-To` from
  `MAIL_REPLY_TO` when set.
- **Delivery:** sent after the status change commits (FastAPI
  `BackgroundTasks`), never blocking it. Before sending, each request row is
  locked and checked atomically (still `created` / not yet notified for this
  status change), so a double click or two resends send one email. Success:
  `created → notified` plus a `notified` event (needs_info / rejected: event
  only). Failure: `notify_failed` event with the error, status unchanged.
  Rate limited to `MAIL_RATE_PER_MINUTE` (default 25; Exchange allows ~30 per
  mailbox per minute); throttling counts as a failure.
- **Retry:** "ส่งอีเมลอีกครั้ง" on the queue detail page and "สร้างแล้วแต่ยัง
  ไม่ได้แจ้ง" with "ส่งซ้ำทั้งหมด" on the Export page (also covers a restart
  that lost pending sends) — Procurement and Administrator only.

## Out of scope
- SMTP sender (kept possible through `MailSender`)
- Teams notifications (CLAUDE.md)
- HTML design beyond a clean simple template; digests / scheduled emails
- A read-only request page for Requesters (the link goes to "My requests")

## Acceptance criteria
1. A failed send never blocks the status change; it is logged as a
   `notify_failed` event with the error and can be retried from the request
   page and from the Export page's "not yet notified" list
2. Without Graph settings no email is sent; the app works and logs each email
   (recipients, subject) instead
3. Emails are in Thai and show the item code prominently (subject and body)
4. Tests use a fake mail sender injected via a dependency; no real network
5. "Mark created" on several requests sends one email per recipient for that
   click, listing all their codes; each request moves to `notified` only when
   its email was sent
6. needs_info and rejected send one email per request with the reason; a
   rejection after approval says the code is cancelled and must not be used
7. With an originator email the email goes To the originator, CC the
   submitting Account; an originator email outside `MAIL_ALLOWED_DOMAINS`, or
   without a name, is refused on the form
8. Sending the same notification twice at the same time (double click, two
   resends) sends exactly one email: the row is locked and its state checked
   before sending
9. The originator migration runs cleanly on a fresh DB and backfills names
   from existing `ขอแทน:` events
10. The Graph sender gets a token with client credentials, sends from the
    configured mailbox, and turns HTTP errors and throttling (429) into
    `notify_failed` with a readable reason; secrets never appear in logs
11. Resend buttons are Procurement/Administrator only (403 for Requesters)

## Files likely touched
new `app/services/notify.py` (+ `MailSender`, Graph/log/fake senders),
`app/services/requests.py`, `app/routes/exports.py`, `app/routes/queue.py`,
`app/routes/requests.py`, `app/config.py`, `.env.example`, one migration,
email templates, `my_requests.html`, tests

## Domain rules that apply
Business logic in services (CLAUDE.md). HANDOFF §6.5/§6.8 for the migration.
Secrets via env only.

## Plan
Tickets in `docs/stories/STORY-002/`:
1. `01-created-email-tracer.md` — MailSender + log/fake senders, created → notified end to end, atomic dedupe
2. `02-graph-sender.md` — Microsoft Graph client-credentials sender, rate limit, error mapping
3. `03-batched-created-email.md` — one email per recipient per "mark created" click
4. `04-needs-info-rejected-email.md` — needs_info and both rejected variants
5. `05-originator-recipients.md` — originator columns + migration/backfill, form field, domain rule, To/CC
6. `06-retry.md` — notify_failed handling, resend button, "not yet notified" list

Build order (Peter): 01 → 05 → 03 → 04 → 06 → 02 — Graph last, so it can be
tried with the real values from IT. Only ticket 05 has a migration; every
other ticket records outcomes as `RequestEvent`s and adds no column.

## Notes

### Grilling (2026-10-01, Peter) — settled
- Q1 Behind a `MailSender` interface. Peter (follow-up): the first real
  sender is **Microsoft Graph `sendMail`** (client credentials), not SMTP —
  Exchange Online disables SMTP AUTH Basic Auth by default at the end of
  December 2026. IT work: App Registration + `Mail.Send` (application) +
  admin consent + Application Access Policy limited to the sender mailbox.
- Q2/Q7 Emails on `created` (worded "created in AX — ready to order"),
  `needs_info` and `rejected` (cancelled-code wording after approval); none
  on `approved`. `created` already is the "created in AX" moment.
- Q3 Link to `/my-requests#request-<id>`; `PUBLIC_BASE_URL` env; no link
  when unset.
- Q4/Q8 Originator email is in scope: new `originator_name` /
  `originator_email` columns (migration, backfill names from events).
- Q5 Send after commit via BackgroundTasks; `notified` / `notify_failed`
  events; resend on the queue page; "not yet notified" list on Export.
- Q6 Thai, simple HTML + plain text, code in the subject.
- Q9 Originator email optional, needs a name, same format rule, domain in
  `MAIL_ALLOWED_DOMAINS` (values from Peter before deploy).
- Q10 To originator, CC submitting Account; otherwise To the submitter.
- Q11 `Reply-To` from `MAIL_REPLY_TO` (value from Peter before deploy).
- Q12 Rate limit `MAIL_RATE_PER_MINUTE` (default 25); throttling →
  `notify_failed`, retried from the list.
- Peter (follow-up): atomic dedupe before each send (lock the row, check
  still `created` / not yet notified) with a test that two concurrent sends
  give one email; one email per recipient per "mark created" click listing
  all codes (needs_info / rejected stay one per request); resend buttons are
  Procurement + Administrator.
- Delivery is **at-least-once** (Peter, 2026-10-01): if Graph accepts an email
  but its reply is lost (timeout), the attempt is recorded as `notify_failed`
  and a resend can deliver a second copy. Accepted behaviour, not a bug.
- The claim before each send is an `UPDATE … WHERE id = :id AND status = …`
  that takes the row's write lock (row lock on PostgreSQL, database write
  lock on SQLite) and is held through the send — so the concurrent-send test
  runs for real on a file SQLite DB with two threads (ticket 01). Postgres
  race is still in STORY-006 AC4.
- `notified` / `notify_failed` events carry the email of the person whose
  action triggered the send (mark-created, resend), not "system".
