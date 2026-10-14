# Backlog

Each story is self-contained: an agent should be able to implement it from the
story file plus `docs/HANDOFF.md` alone, without chat history.

| ID | Story | Depends on | Parallel with |
|---|---|---|---|
| [001](STORY-001-auth-roles.md) | Login + roles — **done** (merged 2026-09-30) | — | — (foundation) |
| [002](STORY-002-email-notification.md) | Email requester when item is created — **done** (2026-10-14) | 001 | 003, 004 |
| [003](STORY-003-uom-standard.md) | 24-unit UoM standard + Base/Purchase UoM + pack size | — | 002, 004 |
| [004](STORY-004-item-attributes.md) | Legacy No., Scope Owner, Lifecycle State | — | 002, 003 |
| [005](STORY-005-register-sync.md) | Re-sync running register from Decision Sheet | Peter fills D1–D4 | — |
| [006](STORY-006-deploy.md) | Deploy to Render/Railway + Postgres | 001, 002, 009, 010 | — |
| [007](STORY-007-naming-alignment.md) | Names: `mL`, `in`, no `,` (align with standard) | — | 002, 004 |
| [008](STORY-008-classification-flags.md) | Flag Sub-Category 99 (reason required) and possible fixed assets | — | 002, 007 |
| [009](STORY-009-requester-resubmit.md) | Requester edits and resubmits a Needs Info request (before plants open) | 001 | 002 |
| [010](STORY-010-validate-code-override.md) | Validate code override against the Running Register — **done** (2026-10-01) | 001 | 002, 003 |
| [011](STORY-011-account-admin-audit.md) | Account admin audit trail in DB (lower priority) | 001 | any |
| [012](STORY-012-plant-aware-d365-snapshot.md) | Plant-aware D365 snapshot (blocked: waiting for Peter's sample export) | 010 | any |

## Status values
`todo` → `planned` (spec + tickets written) → `in-progress` → `review` → `done`

## Story file template
```
# STORY-NNN: title
Status: todo
## Why           (the user problem, one paragraph)
## Scope         (what is in)
## Out of scope  (what is explicitly not)
## Acceptance criteria   (checkable, each maps to at least one test)
## Files likely touched
## Domain rules that apply   (link HANDOFF §6 traps by number)
## Plan          (filled in by /to-spec + /to-tickets)
## Notes         (filled in during implementation)
```
