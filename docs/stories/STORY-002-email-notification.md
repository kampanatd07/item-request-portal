# STORY-002: Email the requester when their item is created

Status: todo · Depends on: STORY-001

## Why
Today Peter tells each requester by hand that their item exists. The last step of
the original manual flow should disappear.

## Scope
- When a request moves to `created`, email the requester: item code, full name,
  UoM, and a link to the request page
- When a request is `rejected` or `needs_info`, email the reason (review_note)
- SMTP settings from env (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
  `MAIL_FROM`) — already listed in `.env.example`
- After sending, move `created` → `notified` and log a `RequestEvent`
- Batch "mark created" sends one email per request (not one per batch)

## Out of scope
- Teams notifications (explicitly out of scope in CLAUDE.md)
- HTML email design beyond a clean simple template
- Digest / scheduled emails

## Acceptance criteria
1. A failed send never blocks the status change; it is logged as an event
   `notify_failed` with the error and can be retried from the request page
2. No email is sent when SMTP is not configured — the app still works (dev mode logs instead)
3. Emails are in Thai, include the item code prominently
4. Tests use a fake mail sender injected via a dependency; no real network in tests

## Files likely touched
new `app/services/notify.py`, `app/services/requests.py` (status transitions),
`app/routes/exports.py` (mark-created), `app/config.py`, templates for email body

## Domain rules that apply
Keep business logic in services (CLAUDE.md layering rule).

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
