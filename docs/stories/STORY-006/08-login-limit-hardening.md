# 08: Login limit hardening: count first, refund later; unblock CLI; IPv6 per /64

Status: done (2026-10-23)
Triage: ready-for-agent
Parent: STORY-006 (part A)
Blocked by: 07
Work order (Peter, 2026-10-22): before 04, then 05.

**What to build:** from the ticket 07 review, notes 1–3 (Peter, 2026-10-22).
(1) No login holds a DB lock, transaction or connection while its password
is hashed, so a burst of logins from one plant cannot use up the connection
pool; the count per IP stays exact. (2) The risk that one person behind a
shared plant IP locks the plant out is accepted (they must be on the plant
network, and the block is logged with the IP); an Administrator can lift a
block from the command line. (3) IPv6 clients are counted per /64, so a
sprayer cannot rotate addresses inside their own prefix.

## Plan (proposed 2026-10-23)

### 1. Count first, refund later (`auth.authenticate`)
Three phases, lock order unchanged: IP row → Account row.
1. **Short transaction:** lock the IP row (create if missing). Blocked →
   `IpBlocked` (429). Count (failures + attempts being checked) ≥ 50 →
   `IpBlocked` too, so parallel attempts cannot pass the limit. Otherwise
   +1 and commit: lock and connection released.
2. **Hash, holding nothing:** read the Account's hash without a lock, verify
   (dummy hash for an unknown email, as today). The per-email lockout also
   held the Account row through the hash today; it moves out too, or the
   "no connection held" rule would not be true.
3. **Short transaction:** lock IP row, then Account row.
   - Failure: the IP count stays (counted in 1); if it is ≥ 50 and no block
     runs, start the block and log it once. The Account's own count goes up
     only while it is not locked, so it stops at exactly 10.
   - Success: **check again that the Account was not locked meanwhile**
     (refuse if it was); otherwise IP count −1 (never below 0) and the
     Account's count reset.
- One at a time, nothing changes: the 50th failure gets 401 and starts the
  block; the 51st gets 429.
- **Trade-off:** attempts still being checked hold a slot, so near 50 a
  parallel attempt can get 429 although one of those in flight later
  succeeds and is refunded (blocks slightly early, only near the limit). A
  process that dies mid-hash never refunds: counted as a failure (fails
  closed).

### 2. Unblock CLI
`python -m app.unblock_ip <ip> [--by NAME]`, built like `create_admin`. The
IP goes through the same `_ip_key` (any address of an IPv6 /64 works); the
block and the count are cleared; logged `login_ip_unblocked ip=… by=…`
(`--by`, else the OS user from `getpass.getuser()`: the CLI has no login).
Exit 0 = unblocked, 1 = not an IP, 2 = that IP is not blocked (nothing
changed). README "When things break": find the IP in the
`login_ip_blocked` log line, run the command. decisions.md: the accepted
risk and why.

### 3. IPv6 per /64 (`_ip_key`)
IPv6 stored as its /64 prefix (e.g. `2001:db8:1:2::/64`); an IPv4-mapped
address (`::ffff:1.2.3.4`) as the IPv4. Fits the column: no migration.

### Small, in the same code (if Peter agrees)
- Review 07 note 5: `_lock_ip_row` can return `None` (row deleted between
  the failed insert and the re-read) → 500; retry once.
- Review 07 note 8: `client_ip: str | None`.

### Ticket 04, AC on one email
Still 30 parallel wrong passwords from 30 IPs (one IP would queue on the IP
row). With nothing held through the hash, it now proves the re-check in
phase 3: the count stops at exactly 10 and "locked" is logged once.

## Acceptance criteria
- [x] A right password on an Account locked during the hash gets exactly the
      answer a wrong password on a locked Account gets: status, message,
      headers, no redirect, no cookie (added by Peter, 2026-10-23)
- [x] During the hash no transaction is open and no pooled connection is
      checked out (PostgreSQL test: the hash is replaced by a probe that
      reads the pool and session state when called)
- [x] PostgreSQL: 80 parallel failures from a new IP → exactly 50 counted,
      30 get 429
- [x] PostgreSQL: a correct password whose Account gets locked while it is
      being hashed is refused
- [x] A success refunds its slot; the count never goes below 0; every ticket
      07 test still passes
- [x] `python -m app.unblock_ip`: `--by` required (missing or blank → exit 1
      with a message; Peter, 2026-10-23); unblocks and logs who; bad IP → exit 1; not
      blocked → exit 2, nothing changed; any address of an IPv6 /64 unblocks
      that /64
- [x] README "When things break" and decisions.md updated
- [x] IPv6: same /64 counted together, different /64 apart, IPv4-mapped
      counted as IPv4
- [x] No migration
- [x] CI green (reported by Peter)

## Notes (2026-10-23)

Plan approved by Peter 2026-10-23, both trade-offs accepted; review 07 notes
5 and 8 fixed here; two additions (same answer when locked during the hash;
`--by` required).

- `authenticate` in three phases as planned. Also refused in phase 3: a
  password changed while the old one was being hashed (the stored hash no
  longer matches). `change_own_password` (logged-in only) still holds the
  Account row through its hash: not a login, outside this ticket.
- `ip_key_or_none` (public, used by the CLI) + `_ip_key` (logs `unknown`).
  IPv6 → its /64 (`2001:db8:1:2::/64`), IPv4-mapped → IPv4.
- `_lock_ip_row` retries a vanished row (up to 3 tries) instead of returning
  `None` (review 07 note 5). `client_ip: str | None` (note 8).
- `auth.unblock_ip` + `app/unblock_ip.py` (exit 0 / 1 / 2; argparse's own exit
  code 2 is turned into 1 so 2 keeps meaning "not blocked"; `unknown` lifts
  the shared bucket). README "When things break", decisions.md 2026-10-23.
- Tests: `tests/test_login_ip_hardening.py` (15, SQLite), 2 more cases in
  `test_login_ip_limit.py` (IPv6 /64, IPv4-mapped; one 07 expectation changed
  from per-address to /64), 3 more in `test_pg_login_ip_limit.py`
  (PostgreSQL: pool and transaction during the hash, known and unknown email;
  a right password locked during the hash is refused). The ticket 07 tests
  all still pass. Local: 875 passed, 19 skipped.

CI on `f581518` (Peter, 2026-10-23): green, **894 passed, 0 skipped**, on
Ubuntu 24.04 (includes `040a5b8`).

## Code review (2026-10-23)

Ran `/code-review` on `e5736e9..f581518`. 8 findings, sorted as before
(**(ก)** wrong data, someone acting who should not, data lost, or an
acceptance criterion not met; **(ข)** a note). **One (ก)**, not yet fixed:
the fix needs Peter's decision, and the cleanest one a migration.

### (ก) Must fix — waiting for Peter
1. **The per-email lockout no longer limits how many guesses are checked.**
   Before this ticket the Account row was held through the hash, so at most
   about 10 guesses at one email were ever checked. Now the Account is read
   unlocked in step 1 and only checked in step 3: 200 parallel guesses at one
   email, spread over 5+ IPs (each under 50 in flight), are all hashed, and a
   right one that settles before the 10th wrong one logs in. The stored count
   still stops at 10, but the guesses do not. Someone acting who should not;
   STORY-006 AC 5 ("parallel wrong logins for one email never get past 10")
   not met in its intent. Introduced by this ticket's plan (step 2 moved the
   Account out of the lock without reserving a slot on it). `_lock_row`'s
   docstring is now wrong too.

### (ข) Notes
2. A count full of attempts still being checked (no block set) answers 429
   with "wait 15 minutes" and writes no `login_ip_blocked` line; the CLI calls
   that IP "not blocked". Rare without leaks (51 logins within one hash
   time), lasting with them (3).
3. Slots leak on any exception between step 1 and the refund (DB error in
   step 3, pool timeout), not only a dead process: each counts as a failure.
   Recommend: refund in an `except` for non-login errors.
4. The refund takes 1 off whatever the row holds now; across a window reset
   or an unblock it can cancel another attempt's failure.
5. (Added in this ticket, not in the plan) "password changed during the hash"
   also catches a hash *upgraded* by a parallel successful login (after the
   Argon2 cost is raised): a right password then counts as a failure.
   Recommend: verify again against the new hash instead of failing.
6. (Existing since STORY-001) the rehash-on-login write happens after commit
   without a lock or check, so it can overwrite a password changed at the
   same moment (old password works again). Only when the Argon2 cost is
   raised. Recommend: write only if the hash is still the one checked.
7. Same as 2: the in-flight-full refusal has no audit line.
8. `unblock_ip` leaves `window_started_at`; an expired block whose row still
   counts ≥ 50 cannot be cleared by the CLI.

## Fix of the review (2026-10-23)

Peter's decisions (2026-10-23): (ก) fixed with "being checked" slots on both
the Account and the IP (migration allowed in this ticket, one file); notes
3, 5, 6 fixed too. Added by Peter: slots expire 1 minute after the count went
0 → 1 (not moved by later slots) and are then **written back** as empty
before this login takes slot (1, now); freeing never goes below 0; back at 0
the time is cleared. A full or locked Account gets no slot and its real hash
is never checked: a dummy hash takes the same time.

- Migration `e63600116a2f` (autogenerated, read line by line: only the four
  columns `pending_checks` INTEGER NOT NULL `server_default '0'` and
  `pending_since` DATETIME NULL on `accounts` and `login_ip_failures`).
  **Run on a copy of `dev.db`** (3 Accounts, at `e52ce808c5d5`): upgrade
  head → the 3 Accounts get `pending_checks = 0`, `pending_since = NULL`;
  downgrade -1 → columns gone; upgrade head again → back; every old column
  of all 3 Accounts identical to the original `dev.db`; both CHECK
  constraints of `accounts` kept; seed OK. `dev.db` itself untouched.
- `authenticate`: (1) slots taken under IP row → Account row; (2) hash
  holding nothing; (3) slots freed, outcome recorded (failures counted on
  both rows when the Account had a slot; a success resets only the
  Account's confirmed failures). Any error after (1) frees both slots
  (note 3). A hash changed during the check is checked again, holding
  nothing, at most 3 rounds (note 5). The hash upgrade writes only where the
  hash is still the one checked (note 6). Unblock also clears slots.
- Tests: `tests/test_login_slots.py` (15, SQLite: the limits count slots;
  expiry written back and slot (1, now), account and IP; the limit holds
  again after expiry; slots under a minute still count; never below 0;
  back at 0 the time is cleared; another login's slot stays; an error
  frees both; an upgraded hash is checked again; the upgrade never
  overwrites a changed password) and one PostgreSQL test: 200 parallel
  guesses at one email from 5 IPs, the first 10 held mid-check, the right
  password among the other 190: the real hash is checked exactly 10 times,
  the right password does not get in, the Account ends locked with no slot
  left. Local: 890 passed, 20 skipped.

CI on `a600f87` (Peter, 2026-10-23): green, **910 passed, 0 skipped**.

## Second code review (2026-10-23)

Ran `/code-review` on `3f3db8a..a600f87` (Peter: the fix rewrote
`authenticate()` and added a migration), focused on slot leaks and frees,
expiry, lock order, the locked-during-hash answer, and the migration.
10 findings. **Two (ก)**, both bugs in the fix; not yet fixed (Peter decides
first). Migration: no finding.

### (ก) Must fix — waiting for Peter
A. **A slot is freed twice if the hash upgrade fails after a successful
   login.** The settle commit already freed both slots; an error in
   `_upgrade_hash` (DB error, `hash_password`) then reaches the `except`,
   which frees them again: another login's slot is lost (one guess more
   than the limit), and the user gets a 500 after logging in correctly.
B. **After the third "hash changed" round, the outcome is written without
   locks.** The round commits (releasing the row locks) before `continue`;
   when the loop runs out, the `else` path frees slots and counts the
   failure on rows read before that commit: absolute values written from
   stale rows (lost updates of other logins' counts and slots), outside
   the IP → Account lock order. Needs the hash to change 3 times during one
   check: very rare, but wrong data when it happens.

### (ข) Notes
1. Expiry clears *all* slots 1 minute after the 0 → 1 time, including ones
   just taken by logins still running; their later frees then take others'
   slots. On an Account this needs slots in use for a whole minute, which
   the 10-failure lock prevents (each guess settles in milliseconds and
   counts). On a busy IP (a plant's successful logins keep a slot in use),
   it can let through up to about one extra limit's worth of in-flight
   attempts at the moment of a block. Follows the agreed design (slots
   without identity); the principled fix is one row per slot (below, 10).
2. (4) If an Account is locked during the check *and* its hash changes, a
   right password costs two hashes before the refusal, a wrong one one: a
   timing difference. Fixed with B if "locked" is checked before re-hashing.
3. (5) A full or locked Account is checked against the dummy hash at the
   current Argon2 cost; an Account whose own hash still has the old cost
   (cost raised, not yet upgraded) answers faster while unlocked: timing
   shows the lock. Only after a cost change.
4. (6) The prune ignores slots: an IP row whose failure window started over
   a day ago is deleted even while its logins are being checked (common for
   a plant with only successful logins), so their slots are lost.
   Recommend: skip rows with live slots.
5. (7) Settle does not re-check the IP window: a failure that crosses the
   15-minute boundary while hashing adds to the old window's count and can
   block early. Recommend: re-run the window check in settle.
6. (8) An Account that is full but not yet locked (9 failures + 1 being
   checked) gives the real user's right password no slot: refused, and
   counted against the user's IP. Lasts only until that check settles
   (which then locks the Account anyway).
7. (9) The 3-round re-check loop is the source of B and 2; simpler: re-check
   once, with locks taken again before writing.
8. (10) Slots have no identity (one counter + one time per row); per-slot
   rows (key, token, taken_at) would make freeing and expiry exact and
   remove 1, A and 4. Needs a new table (migration).

## Fix of the second review (2026-10-23)

Peter's decisions (2026-10-23): fix (ก) A and B with tests that cause the
failure for real; fix (ข) 4 and 5; 1 and 8 (one row per slot) not now, an
open item in HANDOFF §2 with the accepted impact; 3 and 6 only noted here.
After this: push → Peter checks CI → `/code-review` of this round's diff
only → no (ก): close 08 at once, the rest to the backlog; (ก): stop and ask.

- **A:** `_check_and_settle` raises nothing after its settling commit: the
  hash upgrade is best-effort (`login_hash_upgrade_failed` warning). Test:
  the upgrade's UPDATE fails (DB error) → the login still answers 303, the
  warning is logged, and another login's slots on the Account and the IP
  are still there.
- **B:** one re-check only; after it the rows are locked again (IP →
  Account, `_lock_rows`) and everything is written on those; a hash that
  changed again is refused; a locked Account is refused *before* any
  re-check (also fixes note 2: no second hash for a right guess). Tests:
  others' writes made during the check and the re-check are kept (IP
  failures 7 → 8, another login's Account slot); a locked Account is checked
  once; a hash changing every time is checked twice, never a third time.
- **(ข) 4:** the prune never deletes a row whose slots are live (not
  expired). Tests: live slots kept, expired slots deleted.
- **(ข) 5: not changed; it does not occur.** `authenticate` reads the time
  once (`now`) and uses that same value when it settles, so one login cannot
  cross the 15-minute window between its own steps: the failure is counted
  at the time the login started, consistently. The review assumed a fresh
  time at settle. My recommendation to fix it (2026-10-23) was wrong.
- Notes kept, no change (Peter): 3 (dummy hash at the current Argon2 cost vs
  an Account hash still at an older cost: timing shows the lock, only after
  a cost change) and 6 (an Account at 9 failures + 1 being checked refuses
  the owner's right password until that check settles, and counts it on
  the owner's IP).
- Local: 896 passed, 20 skipped.

## Third code review and close (2026-10-23)

CI on `77e44ed` (Peter): green, **916 passed, 0 skipped**. Peter agreed not
to change (ข) 5 (one `now` per login: it cannot cross the window).

Ran `/code-review` on `3b49ec8..77e44ed` only (Peter's rule). 7 findings,
**no (ก)**: each needs a race that cannot be caused from outside (a hash
changing twice within one check, a process interrupt right after the
settling commit, a deactivated Account's hash changing during a check) or is
tidiness. Per the rule, 08 closes and the (ข) notes of all three reviews go
to the backlog: **STORY-015** (login limit follow-ups).
