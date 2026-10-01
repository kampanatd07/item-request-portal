# 02: Microsoft Graph sender

Status: todo
Triage: ready-for-agent
Parent: STORY-002
Blocked by: 01

**What to build:** The real sender. `GraphMailSender` gets an app token with
the OAuth2 client-credentials flow (`MS_TENANT_ID`, `MS_CLIENT_ID`,
`MS_CLIENT_SECRET`), caches it until shortly before it expires, and calls
`POST /users/{MAIL_SENDER}/sendMail` with To, CC, Reply-To, subject, HTML
body (plain text kept for the log/fake senders and future SMTP). Uses httpx
(already a dependency) with short timeouts. `get_mail_sender()` returns it
when all four settings are present.

- A rate limiter keeps sends at or below `MAIL_RATE_PER_MINUTE` (default 25)
  per process; throttling (HTTP 429, honouring `Retry-After` up to a short cap)
  and other HTTP errors become `MailError` with a readable Thai/English reason
  → `notify_failed`.
- Secrets never reach logs or error messages (client secret, tokens).
- `.env.example` documents the four settings, the rate setting and the IT
  steps (App Registration, `Mail.Send` application permission, admin consent,
  Application Access Policy limited to the sender mailbox).
- HANDOFF §7 lists the IT request.

- [ ] Token request and sendMail request match Graph's documented shapes
      (tested against a fake transport, no network)
- [ ] A cached token is reused; an expired one is refreshed
- [ ] 401/403/429/5xx and timeouts become `MailError`; 429 respects a capped
      Retry-After; the message names the status, never the secret or token
- [ ] The rate limiter never lets more than N sends start in a minute
      (tested with the clock seam, not by sleeping)
- [ ] Missing any Graph setting → log sender (AC2)
- [ ] A failed token request (400/401 from the token endpoint, e.g.
      `invalid_client`) gives a clear reason: the Graph credentials do not
      work and the client secret may have expired — check MS_CLIENT_SECRET
      (Peter, 2026-10-01)
