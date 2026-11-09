# STORY-018: UX/UI refresh: fewer input mistakes, status at a glance, a modern look

Status: review · Branch: `story/018-ux-refresh` · Not a go-live condition (Peter, 2026-11-09)
Triage: needs-triage

## Why
Plant requesters open items often but make input mistakes often (wrong
category, brand/size typed into the name, wrong unit), and the current
pages look like default browser boxes with colors hardcoded per page.
Peter asked (2026-11-09) for pages that are easier to use, make mistakes
harder, show status clearly and look modern. Strategy and principles:
`PRODUCT.md`.

## Scope
Agreed 2026-11-09, before Peter leaves on 2026-11-13:
1. One design system in `app/templates/base.html` (tokens for color, Thai
   type, spacing, buttons, inputs, status badges), so every page changes
   with it. Keep the existing green `#0F6E56` as the one brand color.
2. The request form (`request_form.html`): guide input so mistakes are
   harder to make.
3. Then page by page. What is not done by 2026-11-13 becomes follow-up
   stories for the IT team.

## Out of scope
- New features or new workflow steps; business rules (taxonomy, codes,
  naming, UoM) stay as they are.
- A JavaScript framework or build step: stays Jinja2 + HTMX.
- Email templates (`app/templates/email/`).

## Acceptance criteria
- [x] The whole test suite stays green on CI (985 passed, 0 skipped on
  `997dc0f`, Peter from the run, 2026-11-09); no existing test's expectation
  changed (none was: every failure on the way was fixed in the templates).
- [x] One design system in `base.html`; only one page color left hardcoded
  (`partials/item_code.html`, pinned by `test_register_guard`, see Notes).
- [ ] Text contrast ≥ 4.5:1, visible keyboard focus, every form input on
  the request form, queue, admin and snapshot pages has a label.
  (Labels and focus done; contrast was computed from the token values, not
  yet measured on the rendered pages with a tool: open.)
- [x] Every status can be filtered in the queue and the tab counts add up
  to "all" (`tests/test_queue_tabs.py`).
- [x] Each status says what it means and who acts next, from one source
  (`STATUS_HELP`), on the queue, My requests, detail page and `/help`.
- [x] Peter's browser check of every page (pieces A–E) passes (2026-11-09).
- [x] Peter confirms the status wording (`app/templating.py` STATUS_HELP), 2026-11-09.

## Files likely touched
`app/templates/base.html`, `app/templates/*.html`, `app/templates/partials/*.html`.

## Domain rules that apply
UI text stays Thai (CLAUDE.md). HANDOFF §6 trap 1 (`\b` next to Thai) for
any JavaScript that touches Thai text.

## Plan
`/impeccable audit` (2026-11-09) scored the old UI 10/20. Agreed with Peter,
built in pieces, each tested and shown in the browser before the next:
- Step 1: tokens + components in `base.html`; Noto Sans Thai self-hosted
  under `/static` (public, tests in `test_static_font.py`).
- Search-name chips: the name moved from `onclick` to a `data-` attribute
  (a quote in a name could run script); `test_searchname_suggest_escaping.py`.
- A: Notion-like shell (Peter's reference): sidebar by role, page heads.
- B: request form in numbered sections + sticky summary (name preview,
  required-field checklist, submit).
- C: queue tabs with counts (`count_by_status`); two-column detail page.
  Post-export statuses folded into one "export แล้ว" tab with
  sub-filters (`DONE_GROUP`), Peter's choice 2026-11-09. First named
  "ส่งเข้า AX แล้ว"; renamed after review, because an exported request is
  not in AX yet (its sub-filter is marked "รอนำเข้า").
- D + explanations (Peter asked 2026-11-09): progress bar on My requests,
  waiting-for-you first, status legend, badge tooltips, `/help` page.
- E: accounts, reference data, snapshots, exports on the shared system.

## Notes
- Not changed on purpose: `partials/item_code.html` keeps its inline style;
  `test_register_guard.py:393` asserts that exact string is absent for a
  burned code, so restyling it would make the check pass vacuously. Restyle
  it together with that test (ask first).
- Left for later (backlog, none blocks): about 35 layout-only inline styles
  in partials (margins, widths); the group-map form sits inside a `<tr>`
  (works because the parser ties its inputs to it, but is invalid HTML).
- Review of `f0384b4..997dc0f` (2026-11-09): no (ก). Open (ข), for a
  follow-up branch, most useful first:
  1. Queue: double-clicking a code to select it opens the request (the first
     click navigates). Skip row navigation for clicks inside `code`, or wait
     for a second click.
  2. Queue: Ctrl/Cmd/Shift/middle-click on a row does not open a new tab.
  3. Form: `pickCategory` enables the sub-category select even when the
     group has none, so the checklist shows "หมวดย่อย" as required when it
     is not. Enable it only when it has options.
  4. `requests.py` DONE_GROUP comment still says "already in AX/D365".
  5. `WORK_STATUSES` + `DONE_STATUSES` must cover every status by hand;
     `test_every_status_is_reachable_and_the_tabs_add_up` guards it, but an
     import-time check would be firmer.
  6. `.dot.needs_import` and `.dot.in_review` repeat `#B7791F`: make a token.
  7. The sticky asides' `overflow-y: auto` clips focus rings at their edges.
  8. `test_legend_and_help_share_one_status_table` checks only /help, not
     the queue legend.
  Test note: `test_queue_tabs.py` (new in this branch) had its tab label
  changed with the rename; it was never on master.
- `PRODUCT.md` written 2026-11-09 from Peter's answers (desktop users;
  frequent requests, frequent mistakes; modern, friendly, uncomplicated;
  keep the green; WCAG AA).
