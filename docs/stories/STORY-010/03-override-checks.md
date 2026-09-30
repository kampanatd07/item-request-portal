# 03: Override checks — only a real group code, and the register keeps up

Status: todo
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
request_id, code) -> OverrideCheck` (item name from the master, warnings,
number of skipped numbers, whether confirmation is needed) that ticket 04's
screen calls for its preview, and `override_code(..., reason, confirm_skip)`
that re-runs it under the row lock and applies. The register row is locked
(`FOR UPDATE`) like `_allocate_from_register`.

- [ ] Each check has a failing-path test that proves nothing changed (request
      code, register, retired codes, events)
- [ ] Happy path at, below and above the register: below/equal leaves the
      register; above moves it to exactly X and retires every skipped number
- [ ] Jump of 11 without confirmation is refused; with confirmation succeeds;
      a jump of 10 needs none
- [ ] Missing Plant snapshot gives a warning, not a refusal
- [ ] `check_override` changes nothing (read-only), and `override_code`
      re-checks rather than trusting an earlier preview
- [ ] Register and request rows are locked (Postgres); add the race to
      STORY-006 AC4
- [ ] Service-level tests with `central_ids()` and `account_for(db, "administrator")`
