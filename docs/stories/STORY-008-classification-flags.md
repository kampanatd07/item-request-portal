# STORY-008: Flag "Other" (99) and possible fixed-asset requests

Status: todo

## Why
Sub-Category 99 (Other) already holds 21.3% of the central master against a
KPI of ≤ 15%, and nothing in the portal stops it growing. Machines and vehicles
that are really fixed assets also arrive as non-stock requests and would get a
code without anyone checking with Accounting. Peter decided on 2026-09-28:
both are allowed through, but only with a flag that procurement must look at.

## Scope
- Choosing a Sub-Category `99` requires a reason (free text, Thai UI) on
  submit; the request is flagged `other_category` in the review queue.
- A request that looks like a fixed asset (machine, vehicle — keyword list kept
  as data, editable by procurement) is flagged `possible_fixed_asset`.
- Procurement sees the flags in the queue and on the request page.
- Approving a request flagged `possible_fixed_asset` requires procurement to
  tick "ตรวจกับบัญชีแล้ว" (checked with Accounting); the tick is audit-logged
  as a RequestEvent.
- The reasons given for 99 can be exported (CSV) for the yearly taxonomy
  review.

## Out of scope
- Blocking requesters from choosing 99.
- Any integration with Accounting or the fixed-asset register.
- Reporting dashboards (only the CSV export).

## Acceptance criteria
1. Submitting with Sub-Category 99 and no reason fails with a Thai message.
2. Submitting with Sub-Category 99 and a reason succeeds and the request
   carries the `other_category` flag.
3. A request whose name matches the fixed-asset keywords carries
   `possible_fixed_asset`; one that does not, does not.
4. Approving a `possible_fixed_asset` request without the Accounting tick
   fails; with the tick it succeeds and writes a RequestEvent.
5. Queue shows both flags.
6. CSV export lists request id, Item Group, reason, date for all 99 requests.
7. Migration verified on a fresh DB.

## Files likely touched
`app/models/core.py` + migration, `app/services/requests.py`,
`app/services/config_admin.py` (keyword list), queue and request templates,
`app/seed.py`, tests.

## Domain rules that apply
HANDOFF §6.1–6.3 (keyword matching on Thai text: substring, no `\b`, NFC).
Skill `carabao-item-master` §5.

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
