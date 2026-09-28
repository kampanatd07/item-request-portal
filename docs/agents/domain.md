# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: the domain glossary.
- **`docs/decisions.md`**: the decision log. Read the entries that touch the area you're about to work in.
- **`docs/HANDOFF.md` §6**: domain traps already hit (Thai text, names, codes).

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront.

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/
│   ├── decisions.md      ← the only decision log (no docs/adr/)
│   ├── HANDOFF.md
│   └── stories/
└── app/
```

## Use the glossary's vocabulary

When your output names a domain concept (in a story title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Recording decisions

Decisions live in `docs/decisions.md` only. Do not create `docs/adr/`. When a skill says
"write an ADR", add a new entry at the top of `docs/decisions.md` in its existing format:

```
## [YYYY-MM-DD] <decision title>
**Decision:** ...
**Why:** ...
**Implemented by:** STORY-NNN
**Revisit when:** ...
```

## Flag decision conflicts

If your output contradicts an entry in `docs/decisions.md`, surface it explicitly rather than silently overriding:

> _Contradicts [2026-09-28] "Names follow the standard's unit and punctuation forms exactly", but worth reopening because…_
