# STORY-004: Group standard attributes on every item

Status: todo

## Why
The group attribute schema (`docs/group-standard/CBD_NonStock_Restructure_Proposal_v1.md`
§2.4, "Common Core") requires fields the portal does not capture yet. Without
them, items created through the portal are second-class compared with the
migrated master.

## Scope
- `scope_owner`: `SPT` / `GN`, derived from the item group (see
  `docs/rules/D365-rule-summary.md` — 900–905/700–705/709 = SPT, 906–908/706–708 = GN,
  710 = both → ask)
- `lifecycle_state`: `Active` / `Blocked` / `Obsolete`, default `Active`
- `legacy_item_number`: optional text, for requests that replace an old code
- `data_quality_flag`: `Clean` / `Needs Review`, set to `Needs Review` when the
  category was changed by procurement or the name was manually edited
- Show all four on the request detail page; include in export where templates allow

## Out of scope
- Blocking/obsoleting existing items (editing existing items is out of scope per CLAUDE.md)
- Marketing Activity attribute (908/706 only — separate story if needed)

## Acceptance criteria
1. Scope owner is derived automatically; 710 prompts the procurement user to choose
2. Names never contain `(ยกเลิก)` — that meaning lives in `lifecycle_state`
   (naming already strips it; add a test that the state carries it instead)
3. Re-categorising or renaming a request sets `data_quality_flag = Needs Review`
4. Migration is reversible and verified on a fresh DB

## Files likely touched
`app/models/core.py`, `app/services/requests.py`, `app/templates/request_detail.html`,
`app/services/exporter.py`, new migration, tests

## Domain rules that apply
HANDOFF §6.5, §6.8

## Plan
_(architect)_

## Notes
