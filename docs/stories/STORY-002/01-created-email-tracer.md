# 01: "Created in AX" email, end to end (tracer bullet)

Status: todo
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

- [ ] Mark-created on one request sends one email to the requester (fake
      sender) and the request becomes `notified` with a `notified` event
- [ ] Subject and body are Thai and contain the code; no link without
      `PUBLIC_BASE_URL`; Reply-To only when set
- [ ] A sender failure leaves the request `created` with a `notify_failed`
      event and the mark-created response is still a success (AC1)
- [ ] Calling the notification twice sends one email (second finds the row
      already notified); request rows are locked FOR UPDATE (AC8)
- [ ] No Graph settings → the log sender is used and logs recipients and
      subject only (AC2)
- [ ] "My requests" has `id="request-<id>"` anchors
