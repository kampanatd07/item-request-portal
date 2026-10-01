# 01: "Created in AX" email, end to end (tracer bullet)

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-002
Blocked by: None (can start immediately)

**What to build:** When Procurement marks a single exported request as
created, the requester gets a Thai email saying the code is in AX and ready to
order, and the request moves to `notified`. This lays the foundation the
other tickets build on:

- `MailSender` interface (`send(message) -> None`, raises `MailError` with a
  readable reason) and an `EmailMessage`-like value (to, cc, reply_to,
  subject, html, text). Two senders here: `LogMailSender` (dev: logs
  recipients and subject, never the body) and `FakeMailSender` for tests.
  `get_mail_sender()` is a FastAPI dependency so tests inject the fake;
  without Graph settings it returns the log sender.
- `app/services/notify.py`: builds the `created` email (Thai, code in subject
  and large in the HTML body, plain-text part, link
  `PUBLIC_BASE_URL/my-requests#request-<id>` only when `PUBLIC_BASE_URL` is
  set, `Reply-To` from `MAIL_REPLY_TO` when set) and sends it.
- **Atomic dedupe:** `notify_created(db, request_ids, sender)` locks each
  request row (request rows in id order) and only sends for rows still
  `created`; after a successful send it moves them to `notified` with a
  `notified` event. A second call finds nothing to do.
- Mark-created schedules the notification with `BackgroundTasks` after its
  commit, using its own DB session; the status change never waits for it.
- Failure: `notify_failed` event with the reason, status stays `created`
  (retry UI is ticket 06).
- "My requests" rows get `id="request-<id>"` and the targeted row is
  highlighted.
- Config + `.env.example`: `PUBLIC_BASE_URL`, `MAIL_REPLY_TO`; the old SMTP
  placeholders are replaced by the Graph settings of ticket 02.

- [x] Mark-created on one request sends one email to the requester (fake
      sender) and the request becomes `notified` with a `notified` event
- [x] Subject and body are Thai and contain the code; no link without
      `PUBLIC_BASE_URL`; Reply-To only when set
- [x] A sender failure leaves the request `created` with a `notify_failed`
      event and the mark-created response is still a success (AC1)
- [x] Calling the notification twice sends one email (second finds the row
      already notified); request rows are locked FOR UPDATE (AC8)
- [x] No Graph settings → the log sender is used and logs recipients and
      subject only (AC2)
- [x] "My requests" has `id="request-<id>"` anchors

Implementation notes (2026-10-01):
- `app/services/mail.py` (MailMessage, MailSender, MailError, LogMailSender,
  `get_mail_sender`), `app/services/notify.py` (`build_created_email`,
  `notify_created`), templates `email/created.html|txt`.
- Claim = `UPDATE item_requests SET status = status WHERE id AND status =
  'created'`, held through the send; proven with a real two-thread race on a
  file SQLite DB (one email). Removing the claim makes that test fail.
- Mark-created schedules `notify_created` with BackgroundTasks and a session
  from `get_session_factory` (the request session is closed by then).
- The STORY-001 audit test now also expects the `notified` event, actor =
  who marked created.
- Code review fixes: any error for one request (render, DB, commit, an
  unexpected sender exception) is rolled back, recorded as `notify_failed`
  in a fresh transaction, and the batch goes on; a lock busy past the
  timeout is skipped (request stays `created`, resend list). Sent-but-not-
  recorded is a third at-least-once case, named in the event. The dev
  SQLite engine waits 30 s for the write lock (a send holds it). Mark-
  created emails the requests it already moved even if a later one fails.
  The plain-text email is not HTML-escaped.
- Known test limit: HTTP tests share one StaticPool connection between the
  request and background sessions; real separation is only exercised by
  the file-SQLite race test.

