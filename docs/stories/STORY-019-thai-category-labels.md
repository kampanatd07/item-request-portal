# STORY-019: Thai labels and examples for categories

Status: todo · Branch: `story/019-thai-category-labels`
Triage: needs-triage

## Why
The 20 groups and 130 sub-categories are named in English only (for
example `Seal, O-Ring & Gasket`, `Factory Consume`). Plant requesters read
Thai first, so they pick the wrong category more often, and Procurement
must move the request later (STORY-013). The user asked (2026-11-11) for
Thai text that explains each category.

## Scope
Agreed 2026-11-11 (option 1ก):
1. Each group and sub-category gets an optional short Thai name
   (`name_th`) and an optional Thai hint with examples (`hint_th`).
2. Shown to people only: the group and sub-category selects on the request
   form, the hint for the chosen sub-category under its select, the
   suggestion chips, and the request detail page.
3. An Administrator can edit both on the reference data page (taxonomy is
   data, not code).
4. A category without Thai text shows as today (English only), so the
   code can ship before the wording is approved.
5. The Thai wording itself is drafted by Claude
   (`STORY-019/thai-labels-draft.xlsx`, made by `make_thai_draft.py`) and
   is used only after `[BUSINESS-OWNER]` has reviewed it.

## Out of scope
- Changing English names, codes, the Name Prefix, product names or any
  export file. The English name stays the group standard.
- Matching or suggesting categories from Thai text (categorizer).
- Thai labels for code systems, UoM or other reference data.

## Acceptance criteria
- [ ] With `name_th` set, the group and sub-category options read
  `code — English (Thai)`; without it, exactly as today.
- [ ] The chosen sub-category's `hint_th` shows under its select, and
  nothing shows when it has none.
- [ ] Suggestion chips and the request detail page show the Thai name
  when set.
- [ ] An Administrator can set and clear `name_th` / `hint_th`; a
  non-Administrator gets 403.
- [ ] Export files and composed product names are byte-for-byte the same
  with and without Thai labels.
- [ ] The Alembic migration upgrades and downgrades on a fresh database.
- [ ] Re-running the seed does not overwrite Thai text an Administrator
  has edited.
- [ ] The approved wording is loaded only after `[BUSINESS-OWNER]`'s
  review is recorded here (who, date).

## Files likely touched
`app/models/core.py` (`CodeGroup`), a new Alembic migration, `app/seed.py`,
a new `app/data/taxonomy_th.json`, `app/routes/admin.py`,
`app/templates/partials/group_select.html`, `subgroup_select.html`,
`duplicate_list.html`, `config_tables.html`, `request_summary.html`.

## Domain rules that apply
HANDOFF §6 trap 1 (never `\b` next to Thai) for any regex or script on the
Thai text; Thai stored as NFC, never NFKC (CLAUDE.md). Taxonomy wording is
`[BUSINESS-OWNER]`'s call (CLAUDE.md).

## Plan
Not yet confirmed by the user.

## Notes
- Draft wording (2026-11-11): 150 rows, every Thai name ≤ 40 characters.
  Points for the reviewer: 905 vs 906 overlap (cloth gloves in 905-01,
  PPE in 906-03); 904-04 (tools, an Item) vs 703-01 (tool repair, a
  Service); the "เช่น …" examples are guessed from the English names and
  should be replaced with what the plants really buy.
- Reviewer: `[BUSINESS-OWNER]` (IT-HANDOVER C1, no name yet).
