# Issue tracker: Local Markdown (docs/stories)

Stories, specs and tickets for this repo live as markdown files in `docs/stories/`.
There is no GitHub Issues workflow (and no `gh` CLI on the dev machine).

## Conventions

- One file per story: `docs/stories/STORY-NNN-<slug>.md`, following the template in
  `docs/stories/README.md`. The next NNN is the highest existing number + 1.
- Every new story also gets a row in the backlog table in `docs/stories/README.md`
  (ID, story, depends on, parallel with).
- The spec goes in the story's `## Plan` section, not a separate file.
- Sub-tickets are one file per ticket: `docs/stories/STORY-NNN/NN-<slug>.md`, numbered
  from `01`, never a single combined tickets file.
- Comments and history go at the bottom of the file under `## Comments`;
  implementation notes go in `## Notes`.
- Branch per story: `story/NNN-short-name`. Merge approval: see `CLAUDE.md` (Working rules, Branch end).

## Status vs Triage

- **`Status:` is the primary state** of every story and ticket:
  `todo` → `planned` → `in-progress` → `review` → `done`.
- **`Triage:` is used only while taking new work in** (see `triage-labels.md`). It sits
  directly under `Status:`. Once a story is accepted and planned, `Status:` is what
  counts; do not use `Triage:` to track progress.

## When a skill says "publish to the issue tracker"

Create a new story file (or a sub-ticket file under `docs/stories/STORY-NNN/`) and
update the backlog table in `docs/stories/README.md`.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will usually give a story number
(e.g. "001"); resolve it with `docs/stories/STORY-001-*.md`.

## Wayfinding operations

Used by `/wayfinder`.

- **Map**: `docs/stories/STORY-NNN/map.md` (Notes / Decisions-so-far / Fog).
- **Child ticket**: `docs/stories/STORY-NNN/NN-<slug>.md` with a `Type:` line
  (`research`/`prototype`/`grilling`/`task`) and a `Status:` line (`claimed`/`resolved`).
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when
  every ticket it lists is `resolved`.
- **Frontier**: open, unblocked, unclaimed tickets; lowest number first.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append `## Answer`, set `Status: resolved`, then add a context pointer
  (gist + link) to Decisions-so-far in `map.md`.
