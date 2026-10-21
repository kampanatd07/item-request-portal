# 06: Client IP from trusted proxies only; FORWARDED_ALLOW_IPS required outside dev; one worker

Status: todo
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: None (can start immediately)

**What to build:** the app knows each visitor's real IP behind a proxy and
cannot be fooled by a forged header. uvicorn's proxy-headers middleware is
added in the app, its trusted list from the new setting
`FORWARDED_ALLOW_IPS`; the start command passes `--no-proxy-headers` (the
header is handled once, in the app, under test) and `--workers 1` (AC 7: the
mail limiter is per process; Exchange allows about 30 sends a minute per
mailbox). Outside `APP_ENV=dev`, an empty `FORWARDED_ALLOW_IPS` stops the
app at start, like `SECRET_KEY` and the Graph values: the message names the
setting and both choices, the proxy list (IPs/CIDRs, comma separated, or
`*`) or the explicit `none` (no proxy: trust no `X-Forwarded-For`, use the
peer address). In dev, empty means `127.0.0.1`.

- [ ] `X-Forwarded-For` from a trusted peer gives the forwarded client IP
- [ ] The same header from an untrusted peer is ignored; the peer address is
      the client IP
- [ ] `none`: the header is ignored from every peer
- [ ] Outside dev, empty → Settings refuses; the message names
      `FORWARDED_ALLOW_IPS` and both choices. A list, `*` and `none` are
      accepted. In dev, empty is accepted (tests beside the `SECRET_KEY` /
      Graph start-up tests; existing tests that build Settings outside dev
      get the value)
- [ ] Start command test: the Dockerfile runs uvicorn with `--workers 1` and
      `--no-proxy-headers`
- [ ] README: one worker and why (AC 7), and what to set
      `FORWARDED_ALLOW_IPS` to; `.env.example` documents it, noting that
      migrations and `create_admin` need it too outside dev
- [ ] CI: if the workflow from 01 runs anything outside `APP_ENV=dev`, its
      env sets `FORWARDED_ALLOW_IPS` (e.g. `none`). **CI is green after this
      ticket**
- [ ] No migration
