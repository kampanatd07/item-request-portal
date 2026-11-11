# STORY-019: Thai labels and examples for categories

Status: in-progress · Code merged 2026-11-11 (`6e11ffd`, branch `story/019-thai-category-labels`); open: the reviewed wording (the xlsx-to-JSON converter is STORY-020)
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
- [ ] Export files hold the same values in every cell, and composed
  product names are the same, with and without Thai labels (cell values,
  not file bytes: an xlsx stores its save time).
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
Confirmed by the user 2026-11-11 (all recommendations taken):
1. `app/data/taxonomy_th.json` (keys `"900"` / `"900-02"`, values
   `{name_th, hint_th}`), kept apart from the group-standard
   `taxonomy.json`; empty until the wording is approved.
2. `CodeGroup.name_th` (100), `hint_th` (300), nullable, and
   `th_edited` (bool, default false); migration
   `3239ab2cf664` (read; up/down/up on a fresh DB; `alembic check` clean).
3. An Administrator's save that changes the text wins over the file: it
   sets `th_edited` (also when clearing), and the seed never touches such
   a row. A save with nothing changed marks nothing. The tab shows
   "แก้เองแล้ว" on such rows, with "ใช้คำจากไฟล์" to give one back to
   the file (unmarks it and takes the file's text at once). Every
   other row follows the file on each seed, so a corrected wording reaches
   it and a key removed from the file clears it (changed after review,
   see Notes). A key not in the taxonomy, or text too long, stops the seed
   before any write.
4. Shown via `category_label()` (`app/templating.py`) in the selects and
   request summary; chips and the category panel append the Thai name;
   the sub-category hint is set with `textContent`.
5. Reference data page: tab "ชื่อไทยของหมวด" with search and an
   empty/filled filter; `POST /admin/config/thai/{id}` (Administrator).
   Stored NFC with SARA AM recomposed (`app/services/thai_labels.py`).
6. Reviewer of the wording: Peter, before 2026-11-13.

## Notes
- Draft wording (2026-11-11): 150 rows, every Thai name ≤ 40 characters.
  Points for the reviewer: 905 vs 906 overlap (cloth gloves in 905-01,
  PPE in 906-03); 904-04 (tools, an Item) vs 703-01 (tool repair, a
  Service); the "เช่น …" examples are guessed from the English names and
  should be replaced with what the plants really buy.
- Reviewer: Peter, before he leaves on 2026-11-13 (user, 2026-11-11);
  afterwards `[BUSINESS-OWNER]` (IT-HANDOVER C1).
- Existing test changed (user approved 2026-11-11):
  `test_config_tabs.py::test_one_tab_per_panel` lists every tab by name;
  `"thai"` added between `"mapping"` and `"terms"`, where the new tab sits.
  It still checks that every tab has a panel, in the same order.
- `dev.db` migrated to `3239ab2cf664` on 2026-11-11 for the browser check,
  backup `dev.db.bak-2026-11-11` (keep until told). Sample Thai labels
  put on 900, 900-01, 900-02 and 905 in `dev.db` only, marked `th_edited`
  so a seed run keeps them.
- Review of `08ac556..53445ea` (2026-11-11; CI on `53445ea`: 1010 passed,
  0 skipped, and the browser check passed, both from the user). One (ก):
  the Dockerfile and `start.bat` run the seed on every start, and the seed
  filled every empty field, so a label an Administrator cleared came back
  from the file on the next start (AC "can clear", and the user's choice
  "the Administrator's edit wins"). Fixed with `th_edited` (user's choice
  2026-11-11, option ก); the unmerged migration `3239ab2cf664` was edited
  and `dev.db` downgraded and upgraded again. The same fix lets a
  corrected wording in the file reach rows nobody edited.
  (ข) fixed in the same round (user's choice): the save checks the central
  system directly instead of listing every group; the Thai tab no longer
  loads each row's parent (one query instead of ~150); one format
  `English (ไทย)` everywhere, and the group's Thai name in the category
  panel and the recode optgroups; `maxlength` from `NAME_TH_MAX` /
  `HINT_TH_MAX`; module-level imports; a row with only a hint counts as
  filled. Branch-only tests changed with it (never on master).
  Correction: the group name inside the panel's existing brackets reads
  `(English · ไทย)`, not `English (ไทย)`.
- Review of `53445ea..21fedb1` (2026-11-11; CI on `21fedb1`: 1012 passed,
  0 skipped; browser check passed; both from the user). One (ก): every
  save set `th_edited`, even with nothing changed, and nothing unset it,
  so an idle click kept approved wording out of that row for good, with
  no sign on screen. Fixed (user's choice ก): only a real change marks
  the row; marked rows show "แก้เองแล้ว" and a "ใช้คำจากไฟล์" button.
  Also fixed (user's choice): a request without a sub-category showed its
  group twice in the category panel; the counter and the
  "ยังไม่กรอก/กรอกแล้ว" filter count only rows with a Thai name (a hint
  alone leaves the selects in English; this reverses the previous round);
  one import block; children grouped once in `list_thai_labels`. The
  file checks moved from `seed.py` to `thai_labels.parse_label_file`, so
  the reset uses the same checks. Branch-only tests changed with it.
  (ข) backlog, by design or theoretical:
  1. The seed makes every unmarked row follow the file, so a Thai label
     set by SQL or a data fix (not through the admin page) is cleared on
     the next start. Set labels through the admin page or the file.
  2. The save accepts any CENTRAL row, also one deeper than group/sub that
     the tab does not list; the taxonomy has only two levels today.
- Tests changed in that round, both written on this branch and never on
  master: `test_a_hint_only_row_counts_as_filled` became
  `test_a_row_without_a_thai_name_counts_as_empty` (expectation reversed,
  the user's choice 3ก: only a Thai name counts); in
  `test_seed_never_touches_a_row_an_administrator_saved` the sub-category
  now starts with a Thai name, because clearing an empty row is no longer
  a change and would not mark it.
- Review of `21fedb1..e1fe1b8` (2026-11-11; CI on `e1fe1b8`: 1018 passed,
  0 skipped; browser check passed; both from the user): no (ก). (ข)
  backlog:
  1. A JSON syntax error in `taxonomy_th.json` makes "ใช้คำจากไฟล์" a 500
     instead of a Thai 422 (`file_labels` catches only `LabelError`;
     nothing is written; the seed already stops at start).
  2. A row edited back to exactly the file's text stays marked; "ใช้คำจาก
     ไฟล์" unmarks it.
  3. The data folder is named in `seed.py` and in `thai_labels.py`, and
     `seed.load_thai_labels` only converts the error type: use one loader.
  4. `test_reset_reads_the_shipped_file` checks the row is unmarked, not
     that it holds the file's text.
  5. The nested `load()` in `file_labels` has no return type hint.
  6. Reset on a row deeper than group/sub would build a wrong key (as (ข)
     2 of the previous round); every reset re-reads both files from disk.
  7. A row with only a hint counts as "ยังไม่กรอก" (the user's choice);
     nothing on the tab says so.
- Status: merged to master 2026-11-11 with the wording still in review
  (Peter, before 2026-11-13). Open: load the approved wording into
  `app/data/taxonomy_th.json` and tick the AC rows from real results.
