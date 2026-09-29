# 03: Only Administrators consume the Running Register

Status: done
Triage: ready-for-agent
Parent: STORY-001
Blocked by: 01

**What to build:** Only an Administrator can perform the three actions that
consume the Running Register: Approval, re-categorising a request that already
has a Central Code, and overriding a code (decision 2026-09-29, Governance v1
§3). The request service functions that change a request take the acting
Account instead of an actor string, and refuse those three actions for anyone
but an Administrator **before touching the register**, so a refused attempt
never consumes a Running Number. The check lives in the service so a future
route cannot bypass it. Every `RequestEvent` records the acting Account's
email. Procurement still reviews, edits the name, re-categorises before a
code, sends Needs Info, rejects, and marks In Review; the queue hides the
buttons Procurement cannot use. The `in_review` Thai label becomes
"ตรวจแล้ว รออนุมัติ" (checked, waiting for Approval). No migration.

- [x] Procurement gets 403 on Approval, on re-categorising a coded request,
      and on code override — and the Running Register row is unchanged
      afterwards (AC8)
- [x] Administrator can approve from submitted and from in_review
- [x] Procurement can still edit the name, re-categorise an uncoded request,
      send Needs Info, reject and set In Review
- [x] Every RequestEvent written by request and export actions holds the
      Account's email, including export and mark-created (AC4)
- [x] Service-level tests cover the refusal directly, not only through HTTP
- [x] The 19 existing `actor="..."` service calls in tests use a conftest
      helper that returns an Account per Role
- [x] In Review shows the new Thai label

Implementation notes (2026-09-29):
- Administrator re-categorising a coded request issues a new code from the new
  Sub-Category's register (only while `approved`, i.e. before export); the old
  number is burned, recorded as a `code_reissued` event (Peter's call).
- Re-categorising now also refuses a Sub-Category from another code system.
- Governance §4: once coded, a request may move only between Sub-Categories of
  the same Item Group (Data Steward); an Item Group move needs the Data Owner
  and is refused. Before a code, any move is allowed.
- htmx 1.9 dropped every 4xx response, so 422/403 messages never showed;
  `base.html` now swaps them.
- Override still accepts any code — validation is STORY-010.
- An Administrator may reject an `approved` request (before export) with a
  required reason; the code stays on the request and a `code_burned` event
  records that the number is thrown away for good. This is the way out for a
  coded request in the wrong Item Group (reject, then resubmit).
- Follow-ups recorded: STORY-010 AC6 (burned codes from re-issue), STORY-005
  note (burned numbers in the portal-issued report).
- Code review fixes: every request change loads the row with `FOR UPDATE`
  (`_get_locked`) and `export_pending` locks its rows too, each re-checking
  status after the lock, so re-categorise/override cannot race an export on
  Postgres. htmx errors go to an `.error-slot` inside the sending form when the
  swap target would otherwise replace that form.
