# 01: Store the Base Name; one validation path for request fields

Status: done
Triage: ready-for-agent
Parent: STORY-009
Blocked by: None (can start immediately)

**What to build:** A new Item Request remembers the Base Name the Requester
typed, so a later resubmit form can be prefilled with it. One Alembic
migration adds a nullable `base_name` column (batch mode); existing rows stay
empty, with no backfill. As a prefactor, the field validation and Item Name
composition of a new submission move into one service function that ticket 02
reuses for resubmit. The duplicate-candidates line written into the
`submitted` event moves into its own function too. Nothing a person sees
changes.

- [x] A new submission stores the Base Name, cleaned the same way the Item
      Name composition cleans it
- [x] Every existing test passes without any change to it; if one has to
      change, behaviour changed: stop and report
- [x] Migration: `upgrade head` → `downgrade -1` → `upgrade head` on a fresh
      DB and on a copy of `dev.db`, then `python -m app.seed`; `alembic check`
      shows no drift (HANDOFF §6 traps 5 and 8)
- [x] Tests use `central_ids()`

Implementation notes (2026-10-16):
- `naming.clean_part` (was `_clean_part`) is the one cleaning rule;
  `compose_name` uses it for every part and the stored Base Name is
  `clean_part(base)`. Tested: composing from the stored fields gives the
  same Item Name character for character.
- The prefactor is `_validated_fields(...) -> RequestFields` (category checks,
  name composition, UoM, Search Name) and `_duplicate_line(...)`. Plant and
  the originator stay in `submit_request`. The signature of `submit_request`
  did not change; 610 existing tests pass untouched, 3 new (613).
- Migration `db44eba12672`: one nullable `String(100)`, no backfill. Round
  trip on a fresh DB and a dev.db copy: 0 drift, dev.db's 2 requests keep
  `base_name` NULL, 3 accounts intact. dev.db itself was not migrated.
- Code review (2026-10-16), fixed: a Base Name that cleans to nothing ("--"
  with a brand, accepted today) was stored as "" rather than NULL; now NULL
  (test first). Also `normalize_size` runs once, so the composed name and the
  stored size cannot differ.
- Code review, not changed:
  - After Procurement types a name, `base_name` no longer composes to
    `item_name`. That is intended: a resubmit recomposes from the fields and
    replaces the typed name (Q16; the warning is ticket 05).
  - `_duplicate_line` takes the Base Name as typed; ticket 02 must pass the
    posted value too, so both queries match.
  - Base Name, like the Item Name and the other name parts, is not NFC +
    fix_thai normalised on submit (only the originator name is). That is
    existing behaviour and changing it would change Item Names. Note for
    STORY-007 (naming alignment).
  - `ItemRequest(**asdict(fields))` assumes every `RequestFields` field is a
    column. Fine while it only holds columns; revisit if it grows.
- A "--" Base Name with a brand still passes (the brand becomes the name).
  Existing behaviour, left as is.
