# 03: Override checks — only a real group code, and the register keeps up

Status: done (awaiting Peter's review)
Triage: ready-for-agent
Parent: STORY-010
Blocked by: 01, 02

**What to build:** `override_code` accepts a code X only when X is a real
Central Code of the group master, fits the request's category, is not yet in
this Plant's AX, and has never been used or thrown away; the register moves
up when X is above it. Checks run in this order, after the existing
Administrator-only guard and `approved`-status check, **before any change**,
each refusal a Thai `RequestError` with nothing written:

1. reason required (stored in the `code_overridden` event detail)
2. exactly 11 digits; digits 1–3 = request's Group, 4–5 = its Sub-Category,
   6–7 = `00`
3. X exists in `ItemSnapshot` source `CENTRAL` (ticket 02); no CENTRAL load →
   refused ("อัปโหลด Master ที่จัดหมวดแล้วก่อน")
4. X not in this Plant's snapshot (`source_for_factory`: CBD or D365) → else
   refused with advice to reject the request instead; no Plant snapshot →
   allowed, with a warning returned to the caller
5. X not a Retired Code (ticket 01) and not on another request
6. running number of X vs register `last_running` for its Group + Sub:
   - higher → register set to X's running number in the same transaction,
     event `register_advanced` (`old -> new`), and every skipped number in
     between retired with reason `skipped`; if more than 10 numbers are
     skipped, refused unless the caller passes an explicit confirmation
   - lower or equal → register untouched (never backwards)

On success the replaced code Y is retired (`overridden`, ticket 01) and the
request carries X. Split the checks into a read-only `check_override(db,
req, code) -> OverrideCheck` (takes the loaded request; also refuses a
request that is not `approved`) (item name from the master, warnings,
number of skipped numbers, whether confirmation is needed) that ticket 04's
screen calls for its preview, and `override_code(..., reason, confirm_skip)`
that re-runs it under the row lock and applies. The register row is locked
(`FOR UPDATE`) like `_allocate_from_register`.

- [x] Each check has a failing-path test that proves nothing changed (request
      code, register, retired codes, events)
- [x] Happy path at, below and above the register: below/equal leaves the
      register; above moves it to exactly X and retires every skipped number
- [x] Jump of 11 without confirmation is refused; with confirmation succeeds;
      a jump of 10 needs none
- [x] Missing Plant snapshot gives a warning, not a refusal
- [x] `check_override` changes nothing (read-only), and `override_code`
      re-checks rather than trusting an earlier preview
- [x] Register and request rows are locked (Postgres); add the race to
      STORY-006 AC4
- [x] **Minting guard (added by Peter 2026-09-30):** `generate_code` checks,
      before issuing, that the next number is neither a Retired Code nor on
      another request. If it is, it refuses clearly — never skips ahead on its
      own — with a Thai message naming the Group + Sub-Category whose register
      is behind, asking the Administrator to check whether codes were issued
      outside the portal (STORY-005 register sync). Test: the register does
      not move when minting is refused (Approval and re-issue both)
- [x] Service-level tests with `central_ids()` and `account_for(db, "administrator")`

Implementation notes (2026-09-30, decisions by Peter):
- Skipped numbers are split: those the group master holds are real codes in
  use and are never retired (counted in `skipped_in_master`); only the rest
  are retired as `skipped`. Numbers already retired or on a request are left
  alone too (`skipped_already_used`). The confirmation threshold counts only
  numbers that would really be thrown away: more than 10 (`SKIP_CONFIRM_LIMIT`).
- The minting guard also refuses when the next number is in the group master
  (the clearest sign the register is behind); skipped when no master is loaded.
- Lock order is request row, then register row, in Approval, re-issue and
  override (`lock_register` in codegen.py); the register is read only under
  its lock. Tests prove the order and the locked first read.
- The override reason is kept in the `code_overridden` event only, never in
  `review_note` (the requester sees that).
- Interim form: the status panel has a reason field and a confirmation
  checkbox until ticket 04's check-then-confirm screen replaces it.
- Code review fixes: the "already in this Plant's AX" advice now shows the real
  code (half of it was not an f-string); a register jump checks the whole
  skipped range with one query per kind (`retired_among`, `on_requests_among`,
  `retire_many`) instead of ~3 per number — a confirmed 3,000-number jump now
  runs in under 100 selects while the rows are locked; `check_override`
  refuses a request that is not `approved`, so ticket 04's preview cannot
  show one.

