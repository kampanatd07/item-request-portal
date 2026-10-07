# 02: Microsoft Graph sender

Status: done with a fake transport — real send waits for IT's values
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

- [x] Token request and sendMail request match Graph's documented shapes
      (tested against a fake transport, no network)
- [x] A cached token is reused; an expired one is refreshed
- [x] 401/403/429/5xx and timeouts become `MailError`; 429 respects a capped
      Retry-After; the message names the status, never the secret or token
- [x] The rate limiter never lets more than N sends start in a minute
      (tested with the clock seam, not by sleeping)
- [x] Missing any Graph setting → log sender (AC2)
- [x] A failed token request (400/401 from the token endpoint, e.g.
      `invalid_client`) gives a clear reason: the Graph credentials do not
      work and the client secret may have expired — check MS_CLIENT_SECRET
      (Peter, 2026-10-01)

Implementation notes (2026-10-02):
- `app/services/graph_mail.py`: `GraphMailSender` + `RateLimiter` (sliding
  60 s window, clock/sleep seams). Settings `MS_TENANT_ID`, `MS_CLIENT_ID`,
  `MS_CLIENT_SECRET` (SecretStr), `MAIL_SENDER`, `MAIL_RATE_PER_MINUTE`;
  `get_mail_sender()` builds one Graph sender per process when all four are
  set, else the log sender (a warning names what is missing when only some
  are set — names, never values).
- Token renewed 5 min before expiry; a 401 from sendMail drops the token and
  tries once more with a fresh one. 429: waits Retry-After once if ≤ 10 s,
  otherwise fails at once (left for resend). Timeouts say the email may
  already have gone (at-least-once).
- Error text: HTTP status + Graph error code / OAuth error + AADSTS number
  only; never Graph's free text, the secret or the token. Token endpoint
  400/401 → "Graph credentials do not work, the client secret may have
  expired — check MS_CLIENT_SECRET" (Thai + English).
- `saveToSentItems: true`: a copy stays in the sender mailbox as an audit trail.
- Not yet tried against real Graph: the first real send (HANDOFF §7) is the
  remaining check.
- Code review fixes: the notifiers call `wait_for_slot(sender)` *before*
  claiming request rows, so the rate limiter's wait (up to a minute) never
  happens under a row lock (on SQLite that lock is the whole database);
  `MAIL_RATE_PER_MINUTE` < 1 stops the app at start instead of failing every
  mark-created click.

