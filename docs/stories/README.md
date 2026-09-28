# Backlog

Each story is self-contained: an agent should be able to implement it from the
story file plus `docs/HANDOFF.md` alone, without chat history.

| ID | Story | Depends on | Parallel with |
|---|---|---|---|
| [001](STORY-001-auth-roles.md) | Login + roles | — | — (foundation) |
| [002](STORY-002-email-notification.md) | Email requester when item is created | 001 | 003, 004 |
| [003](STORY-003-uom-standard.md) | 24-unit UoM standard + Base/Purchase UoM + pack size | — | 002, 004 |
| [004](STORY-004-item-attributes.md) | Legacy No., Scope Owner, Lifecycle State | — | 002, 003 |
| [005](STORY-005-register-sync.md) | Re-sync running register from Decision Sheet | Peter fills D1–D4 | — |
| [006](STORY-006-deploy.md) | Deploy to Render/Railway + Postgres | 001, 002 | — |

## Status values
`todo` → `planned` (architect wrote a plan) → `in-progress` → `review` → `done`

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
## Plan          (filled in by architect)
## Notes         (filled in during implementation)
```
