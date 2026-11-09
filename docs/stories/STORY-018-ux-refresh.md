# STORY-018: UX/UI refresh: fewer input mistakes, status at a glance, a modern look

Status: todo · Branch: `story/018-ux-refresh` · Not a go-live condition (Peter, 2026-11-09)
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
(Filled in by the plan after the audit of all pages.)
- The whole test suite stays green; any change to an existing test's
  expectation is asked first (CLAUDE.md).
- Text contrast ≥ 4.5:1, visible keyboard focus, every input has a label.

## Files likely touched
`app/templates/base.html`, `app/templates/*.html`, `app/templates/partials/*.html`.

## Domain rules that apply
UI text stays Thai (CLAUDE.md). HANDOFF §6 trap 1 (`\b` next to Thai) for
any JavaScript that touches Thai text.

## Plan
(Filled in after `/impeccable` audit; Peter confirms before any edit.)

## Notes
- `PRODUCT.md` written 2026-11-09 from Peter's answers (desktop users;
  frequent requests, frequent mistakes; modern, friendly, uncomplicated;
  keep the green; WCAG AA).
