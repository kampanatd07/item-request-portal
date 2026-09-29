# 03: Only Administrators consume the Running Register

Status: todo
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

- [ ] Procurement gets 403 on Approval, on re-categorising a coded request,
      and on code override — and the Running Register row is unchanged
      afterwards (AC8)
- [ ] Administrator can approve from submitted and from in_review
- [ ] Procurement can still edit the name, re-categorise an uncoded request,
      send Needs Info, reject and set In Review
- [ ] Every RequestEvent written by request and export actions holds the
      Account's email, including export and mark-created (AC4)
- [ ] Service-level tests cover the refusal directly, not only through HTTP
- [ ] The 19 existing `actor="..."` service calls in tests use a conftest
      helper that returns an Account per Role
- [ ] In Review shows the new Thai label
