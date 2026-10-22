# 06: Client IP from trusted proxies only; FORWARDED_ALLOW_IPS required outside dev; one worker

Status: done (2026-10-22)
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

- [x] `X-Forwarded-For` from a trusted peer gives the forwarded client IP
- [x] The same header from an untrusted peer is ignored; the peer address is
      the client IP
- [x] `none`: the header is ignored from every peer
- [x] Outside dev, empty → Settings refuses; the message names
      `FORWARDED_ALLOW_IPS` and both choices. A list, `*` and `none` are
      accepted. In dev, empty is accepted (tests beside the `SECRET_KEY` /
      Graph start-up tests; existing tests that build Settings outside dev
      get the value)
- [x] Start command test: the Dockerfile runs uvicorn with `--workers 1` and
      `--no-proxy-headers`
- [x] README: one worker and why (AC 7), and what to set
      `FORWARDED_ALLOW_IPS` to; `.env.example` documents it, noting that
      migrations and `create_admin` need it too outside dev
- [x] CI: if the workflow from 01 runs anything outside `APP_ENV=dev`, its
      env sets `FORWARDED_ALLOW_IPS` (e.g. `none`). **CI is green after this
      ticket**
- [x] No migration

## Notes (2026-10-22)

**Changed from the spec (Peter, 2026-10-22):**
- `*` is **refused everywhere** (dev too), with the reason in the message:
  in every uvicorn version `*` takes the *leftmost* `X-Forwarded-For` entry,
  which the client writes, so the IP limit of ticket 07 could be dodged.
- uvicorn 0.30 → **0.54** in its own commit (`261d2a9`): 0.30 had no CIDR.
  Release notes 0.31–0.54 read; nothing affects us (one worker, no
  websockets, Python 3.12/3.13; a startup failure now exits with code 3).
- Part B decision recorded in the STORY-006 spec: a platform that does not
  publish its proxy IPs has no correct value; "trust one hop" is the option.

**Built:**
- `Settings.forwarded_allow_ips` + `trusted_proxies()`: outside dev empty is
  refused; `*` refused; every entry must be an IP or CIDR (`ipaddress`,
  strict, so `10.0.0.1/8` is a typo error); `none` must stand alone and
  means no middleware; dev empty → `127.0.0.1`.
- `app/main.py` adds uvicorn's `ProxyHeadersMiddleware` last (outermost)
  with that list. Dockerfile: `--workers 1 --no-proxy-headers`.
- Tests set `FORWARDED_ALLOW_IPS=none` in conftest (like `APP_ENV`), so the
  existing production-Settings tests keep working; the rule's own tests pass
  their value. CI needs nothing: it runs with `APP_ENV=dev`.
- `tests/test_proxy_headers.py`, 23 tests: trusted / untrusted peer, `none`,
  CIDR, a forged leftmost entry loses; the real app (fresh process) has the
  middleware outermost with the configured list, and none for `none`; the
  start-up rule (empty, `*` in dev and production, bad entries, accepted
  values, dev default); the Dockerfile command.
- README (Deploying) and `.env.example` document both.

## Code review (2026-10-22)

Checked first (Peter): the start-up rule is in `Settings`' own
`model_validator` (`_check_forwarded_allow_ips`), not only in `main.py`.
Proof: `test_outside_dev_an_empty_value_refuses_to_start` builds `Settings`
directly; and with `APP_ENV=production` and no value, `alembic upgrade head`
and `python -m app.create_admin` both stop with that `ValidationError` (run
by hand 2026-10-22).

Ran `/code-review` on `261d2a9..0040610` (and the uvicorn bump). 7 findings,
sorted as before (**(ก)** wrong data, someone acting who should not, data
lost, or an acceptance criterion not met; **(ข)** a note).

### (ก) Must fix — fixed
1+2. **The README / `.env.example` guidance could undo the ticket.** They
   suggested `10.0.0.0/8` and spoke of "the proxy" only. (1) A trusted range
   that real clients also come from lets them write their own IP: when every
   `X-Forwarded-For` entry is trusted, uvicorn 0.54 falls back to the
   leftmost, client-written one. (2) A hop that appends to the header but is
   not listed (a CDN in front of the load balancer) becomes "the client", so
   all plants share its IPs and 50 failures block everyone. AC "README: …
   what to set `FORWARDED_ALLOW_IPS` to" not met. **Fixed:** both files now
   say list every appending hop, only proxy addresses, never a range clients
   come from, and that a platform start-command override must keep
   `--no-proxy-headers`. No example range.

### (ข) Notes — not changed
3. If a start command leaves out `--no-proxy-headers` (HANDOFF §4 dev
   command, a platform override), uvicorn adds its own proxy layer reading
   the same env var (not `.env`). Same list → same result in production;
   differs only when the value is in `.env`. Documented in README (above).
4. Dev default trusts `127.0.0.1` only, not `::1` (uvicorn ≥ 0.53 trusts
   both). Only matters for a local proxy over IPv6.
5. `trusted_proxies()` is parsed twice (validator, then `main.py`).
   Recommend: keep the parsed list from validation.
6. The fresh-process test depends on pytest running from the repo root and
   hides the child's stderr on failure. Recommend: `cwd=` repo root and
   stderr in the message.
7. Tests run with `FORWARDED_ALLOW_IPS=none`, so the shared app never has
   the proxy layer; ticket 07's login tests would not cross it. **Carry into
   07:** at least one login-limit test through the real middleware.
8. (Reviewer's 1, code side) A guard for "every entry trusted → leftmost
   wins" (fall back to the peer instead) would make a too-wide range safe.
   Recommend: consider with Part B's "trust one hop" decision.

## Closed (2026-10-22)

CI on `0040610` (Peter): green, **848 passed, 0 skipped**. The (ก) fix is
documentation only (README, `.env.example`); no code or test change.
